import importlib
import io
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from rostering.domain import Building, Competition, Helper, Preference, Role, RoleCapacity, Room
from rostering.persistence.serialize import solver_config_from_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.model import RoleCosts, SolverConfig, SolverWeights, solve_competition
from rostering.webapp import mutations

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_2026 = REPO_ROOT / "data" / "seasons" / "2026-jaro" / "raw-response.xlsx"

SMALL_CONFIG = [
    {
        "name": "B",
        "rooms": [
            {
                "name": "R1",
                "capacities": {
                    "Opravovatel": {"minimum": 0},
                    "Zaloha": {"minimum": 0},
                },
            }
        ],
        "capacities": {},
    }
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "workspace")


def _seed_two_helpers(workspace: Workspace) -> None:
    helpers = [
        {
            "id": 1,
            "name": "Anna",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [2],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        },
        {
            "id": 2,
            "name": "Petr",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [1],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        },
    ]
    state = workspace.load()
    state["helpers"] = helpers
    workspace.save(state)


def _seed_helper_with_unresolved_friend(workspace: Workspace) -> None:
    helpers = [
        {
            "id": 1,
            "name": "Anna",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": ["Terka"],
        },
        {
            "id": 2,
            "name": "Tereza",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        },
    ]
    state = workspace.load()
    state["helpers"] = helpers
    workspace.save(state)


def test_initial_state_has_default_config(workspace):
    data = mutations.get_state(workspace)
    assert data["helpers"] == []
    assert data["assignments"] == []
    # Seeded from the bundled default (a copy of the latest season's
    # roster), not empty — see rostering/persistence/config_store.py.
    assert {b["name"] for b in data["config"]} == {"Mala Strana", "Karlov", "Troja", "Karlin"}


def test_config_persists_across_reset(workspace, tmp_path):
    mutations.put_config(workspace, SMALL_CONFIG)
    assert mutations.reset_workspace(workspace)["config"][0]["name"] == "B"
    assert (tmp_path / "buildings-config.yaml").exists()


@pytest.mark.skipif(not RAW_2026.exists(), reason="real season data not present on this machine")
def test_upload_ingests_real_survey(workspace):
    data = mutations.upload_responses(workspace, RAW_2026.read_bytes(), "raw-response.xlsx", label="2026-jaro")
    assert len(data["helpers"]) > 100
    assert isinstance(data["ingestion_warnings"], list)


def test_config_round_trip(workspace):
    mutations.put_config(workspace, SMALL_CONFIG)
    state = mutations.get_state(workspace)
    assert state["config"][0]["name"] == "B"
    assert state["config"][0]["rooms"][0]["name"] == "R1"


def test_config_rejects_invalid_shape(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.put_config(workspace, [{"rooms": []}])  # missing "name"


def test_solver_config_round_trips_the_unit_and_role_costs(workspace):
    mutations.put_solver_config(
        workspace,
        {
            "weights": {"role_cost_unit": 3, "building_mismatch": 7, "friend_unsatisfied": 9},
            "role_costs": {"ano": 1, "klidne": 2, "nevadi": 3, "zaloha": 9, "spise_ne": 5, "ne": 20},
        },
    )
    config = solver_config_from_dict(mutations.get_state(workspace)["solver_config"])

    assert config.weights == SolverWeights(role_preference=3, building_mismatch=7, friend_unsatisfied=9)
    assert config.role_costs == RoleCosts(ano=1, klidne=2, nevadi=3, zaloha=9, spise_ne=5, ne=20)


def test_a_fresh_workspace_saves_the_solver_defaults(workspace):
    saved = mutations.get_state(workspace)["solver_config"]

    assert solver_config_from_dict(saved) == SolverConfig()


def test_a_saved_legacy_role_preference_weight_is_ignored():
    config = solver_config_from_dict({"weights": {"role_preference": 4, "building_mismatch": 3}})

    assert config.weights.role_preference == 1
    assert config.weights.building_mismatch == 3


def test_missing_solver_config_keys_load_as_the_solver_defaults():
    defaults = SolverConfig()

    assert solver_config_from_dict({}) == defaults
    assert solver_config_from_dict(None) == defaults
    assert solver_config_from_dict({"weights": {}, "role_costs": {}, "friend_scoring": {}}) == defaults
    assert solver_config_from_dict({"role_costs": {"zaloha": 8}}).role_costs == RoleCosts(zaloha=8)


@pytest.mark.parametrize(
    "bad",
    [
        {"weights": {"role_cost_unit": -1}},
        {"role_costs": {"ne": -2}},
        {"role_costs": {"ano": "many"}},
    ],
)
def test_solver_config_rejects_negative_or_non_integer_costs(workspace, bad):
    with pytest.raises(mutations.RosteringError):
        mutations.put_solver_config(workspace, bad)


def test_a_saved_zaloha_cost_above_spise_ne_changes_the_solved_landing_spot(workspace):
    building = Building(name="B", rooms=[Room(name="R1", capacities={Role.Zaloha: RoleCapacity(minimum=0)})])
    helper = Helper(id=1, name="H", role_preferences={role: Preference.Spise_ne for role in Role if role is not Role.Zaloha})
    comp = Competition(buildings={"B": building}, helpers=[helper])

    def landing_spot(solver_config: dict) -> Role:
        mutations.put_solver_config(workspace, {"time_limit_seconds": 5, **solver_config})
        config = solver_config_from_dict(mutations.get_state(workspace)["solver_config"])
        return solve_competition(comp, config).assignments[0].role

    assert landing_spot({}) == Role.Zaloha
    assert landing_spot({"role_costs": {"zaloha": 8}}) != Role.Zaloha


def test_solve_requires_helpers_and_config(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.solve(workspace)


def test_solve_end_to_end_and_export(workspace):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)

    state = mutations.solve(workspace)
    assert len(state["assignments"]) == 2
    assert state["diagnostics"]["status"] in ("OPTIMAL", "FEASIBLE")

    export_bytes = mutations.export_xlsx_bytes(workspace)
    assert export_bytes[:2] == b"PK"  # xlsx zip magic


def test_export_is_saved_into_the_season_folder(workspace):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)
    workspace.create_season("2026-podzim")
    mutations.solve(workspace)

    path = mutations.save_export_to_season(workspace)

    assert path == workspace.root / "2026-podzim" / "Rozdělení pomocníků Praha - 2026 Podzim.xlsx"
    assert path.read_bytes()[:2] == b"PK"


def test_saving_the_export_needs_an_open_season(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.save_export_to_season(workspace, b"PK")


OVER_CONSTRAINED_CONFIG = [
    {
        "name": "B",
        "rooms": [
            {
                "name": "R1",
                "capacities": {"Skenovac": {"minimum": 3}, "Zaloha": {"minimum": 0}},
            }
        ],
        "capacities": {},
    }
]


def test_solve_of_an_over_constrained_competition_returns_a_roster_and_the_bent_rules(workspace):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, OVER_CONSTRAINED_CONFIG)

    state = mutations.solve(workspace)

    assert len(state["assignments"]) == 2
    assert state["diagnostics"]["status"] in ("OPTIMAL", "FEASIBLE")
    assert state["diagnostics"]["broken_rules"] == [
        {"family": "minimums", "amount": 1, "line": "Místnost R1 · Skenovač: 2 z 3 požadovaných (chybí 1)"}
    ]
    # A roster with a bent rule is still exportable.
    assert mutations.export_xlsx_bytes(workspace)[:2] == b"PK"


def test_solve_reports_no_broken_rules_when_all_hold(workspace):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)

    state = mutations.solve(workspace)

    assert state["diagnostics"]["broken_rules"] == []


def test_solve_with_no_roster_within_the_time_limit_says_so_and_keeps_the_old_roster(workspace, monkeypatch):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)
    mutations.put_solver_config(workspace, {"time_limit_seconds": 0})

    def _no_roster(comp, config=None, **kwargs):
        raise mutations.NoRosterFound(config.time_limit_seconds)

    monkeypatch.setattr(mutations, "solve_competition", _no_roster)

    with pytest.raises(mutations.RosteringError) as excinfo:
        mutations.solve(workspace)

    message = str(excinfo.value)
    assert message.startswith("Rozdělení se nepodařilo najít do 0 s.")
    assert "INFEASIBLE" not in message
    state = mutations.get_state(workspace)
    assert len(state["assignments"]) == 2
    assert state["diagnostics"]["status"] != "INFEASIBLE"


def _tshirt_sheet(export_bytes: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(export_bytes))
    return [[c.value for c in row] for row in wb["Trička"].iter_rows()]


def test_tshirt_size_survives_upload_reload_solve_and_export(workspace):
    survey = io.BytesIO()
    pd.DataFrame(
        {"Tvoje jméno a příjmení": ["Anna", "Petr"], "Tvoje velikost trička": ["xl ", "?"]}
    ).to_excel(survey, index=False)
    state = mutations.upload_responses(workspace, survey.getvalue(), "survey.xlsx", label="2026-jaro")
    assert [h["tshirt_size"] for h in state["helpers"]] == ["XL", "Unknown"]
    assert any("Petr" in w and "'?'" in w for w in state["ingestion_warnings"])

    # Persisted, not just returned.
    assert [h["tshirt_size"] for h in mutations.get_state(workspace)["helpers"]] == ["XL", "Unknown"]

    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)
    rows = _tshirt_sheet(mutations.export_xlsx_bytes(workspace))
    by_label = {r[0]: r for r in rows}
    assert by_label["XL"][1] == 1
    assert by_label["Unknown"][1] == 1


def test_workspace_saved_before_tshirt_sizes_loads_as_unknown(workspace):
    # _seed_two_helpers writes helper dicts exactly as older versions did:
    # with no "tshirt_size" key at all.
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)
    rows = _tshirt_sheet(mutations.export_xlsx_bytes(workspace))
    by_label = {r[0]: r for r in rows}
    assert by_label["Unknown"][1] == 2
    assert by_label["XS"][1] == 0


def test_set_tshirt_size_persists_and_shows_in_next_export(workspace):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)

    state = mutations.set_tshirt_size(workspace, 1, "L")
    assert state["helpers"][0]["tshirt_size"] == "L"

    # Persisted, not just returned.
    assert mutations.get_state(workspace)["helpers"][0]["tshirt_size"] == "L"

    export_bytes = mutations.export_xlsx_bytes(workspace)
    by_label = {r[0]: r for r in _tshirt_sheet(export_bytes)}
    assert by_label["L"][1] == 1
    assert by_label["Unknown"][1] == 1
    wb = openpyxl.load_workbook(io.BytesIO(export_bytes))
    building_list = [[c.value for c in row] for row in wb["B"].iter_rows()]
    assert ["Anna", "L"] == building_list[1][:2]


def test_set_tshirt_size_can_change_and_clear_a_size(workspace):
    _seed_two_helpers(workspace)
    mutations.set_tshirt_size(workspace, 1, "S")
    state = mutations.set_tshirt_size(workspace, 1, "XXL")
    assert state["helpers"][0]["tshirt_size"] == "XXL"
    state = mutations.set_tshirt_size(workspace, 1, "Unknown")
    assert state["helpers"][0]["tshirt_size"] == "Unknown"


def test_set_tshirt_size_normalizes_case_and_whitespace(workspace):
    _seed_two_helpers(workspace)
    state = mutations.set_tshirt_size(workspace, 2, " xl ")
    assert state["helpers"][1]["tshirt_size"] == "XL"


@pytest.mark.parametrize("bad", ["", "XXXL", "medium", "?", "42"])
def test_set_tshirt_size_rejects_an_invalid_size(workspace, bad):
    _seed_two_helpers(workspace)
    mutations.set_tshirt_size(workspace, 1, "M")
    with pytest.raises(mutations.RosteringError):
        mutations.set_tshirt_size(workspace, 1, bad)
    # The rejected edit changed nothing.
    assert mutations.get_state(workspace)["helpers"][0]["tshirt_size"] == "M"


def test_set_tshirt_size_unknown_helper_raises(workspace):
    _seed_two_helpers(workspace)
    with pytest.raises(mutations.RosteringError):
        mutations.set_tshirt_size(workspace, 999, "M")


def test_set_tshirt_size_only_touches_the_named_helper(workspace):
    _seed_two_helpers(workspace)
    before = mutations.get_state(workspace)
    state = mutations.set_tshirt_size(workspace, 1, "S")
    assert state["helpers"][1] == before["helpers"][1]
    assert {k: v for k, v in state["helpers"][0].items() if k != "tshirt_size"} == {
        k: v for k, v in before["helpers"][0].items() if k != "tshirt_size"
    }


def test_manual_move_updates_assignment_and_recomputes_friend_pairs(workspace):
    _seed_two_helpers(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)

    state = mutations.move_helper(workspace, 1, "B", "R1", "Zaloha")
    moved = next(a for a in state["assignments"] if a["helper_id"] == 1)
    assert moved["role"] == "Zaloha"


def test_manual_move_unknown_helper_raises(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.move_helper(workspace, 999, "B", "R1", "Zaloha")


def test_manual_roles_round_trip(workspace):
    _seed_two_helpers(workspace)
    manual = {
        "structural": [{"role": "VedouciBudovy", "building": "B", "room": None, "helper_id": 1}],
        "overlay": [{"role": "Registrace", "helper_id": 2}],
    }
    mutations.put_manual_roles(workspace, manual)
    state = mutations.get_state(workspace)
    assert state["manual_roles"]["structural"][0]["helper_id"] == 1
    assert state["manual_roles"]["overlay"][0]["role"] == "Registrace"


TWO_ROOM_CONFIG = [
    {
        "name": "B",
        "rooms": [
            {"name": "R1", "capacities": {}},
            {"name": "R2", "capacities": {}},
            {"name": "R3", "capacities": {}},
        ],
        "capacities": {},
    }
]


def test_cell_merge_round_trip(workspace):
    mutations.put_config(workspace, TWO_ROOM_CONFIG)
    state = mutations.set_cell_merges(workspace, "Opravovatel", "B", [["R1", "R2"]], merged=True)
    assert state["cell_merges"] == {"Opravovatel": {"B": [["R1", "R2"]]}}

    # Extending the merge to a third room appends rather than replaces, and
    # is scoped to this row only — a different row_key is untouched.
    state = mutations.set_cell_merges(workspace, "Opravovatel", "B", [["R2", "R3"]], merged=True)
    assert state["cell_merges"] == {"Opravovatel": {"B": [["R1", "R2"], ["R2", "R3"]]}}
    state = mutations.set_cell_merges(workspace, "Zaloha", "B", [["R2", "R3"]], merged=True)
    assert state["cell_merges"] == {
        "Opravovatel": {"B": [["R1", "R2"], ["R2", "R3"]]},
        "Zaloha": {"B": [["R2", "R3"]]},
    }

    # Unmerging clears the listed pairs and drops empty building/row_key
    # entries entirely (not just an empty list).
    state = mutations.set_cell_merges(workspace, "Opravovatel", "B", [["R1", "R2"], ["R2", "R3"]], merged=False)
    state = mutations.set_cell_merges(workspace, "Zaloha", "B", [["R2", "R3"]], merged=False)
    assert state["cell_merges"] == {}


def test_put_config_prunes_stale_cell_merges(workspace):
    mutations.put_config(workspace, TWO_ROOM_CONFIG)
    mutations.set_cell_merges(workspace, "Opravovatel", "B", [["R1", "R2"]], merged=True)

    # Re-configuring without R2 makes the R1/R2 pair stale — it must not
    # linger in state and silently misapply if R2 is ever reintroduced.
    single_room_config = [{"name": "B", "rooms": [{"name": "R1", "capacities": {}}], "capacities": {}}]
    state = mutations.put_config(workspace, single_room_config)
    assert state["cell_merges"] == {}


def test_version_lifecycle(workspace):
    _seed_two_helpers(workspace)
    workspace.create_season("2026-jaro")  # Versions belong to an open Season
    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)

    created = mutations.save_version(workspace, "Draft 1")
    assert created["name"] == "Draft 1"

    versions = mutations.list_versions(workspace)
    assert any(v["slug"] == created["slug"] for v in versions)

    # Mutate current state, then restore the saved version and confirm the
    # mutation is gone.
    mutations.move_helper(workspace, 1, "B", "R1", "Skenovac")
    restored = mutations.restore_version(workspace, created["slug"])
    moved = next(a for a in restored["assignments"] if a["helper_id"] == 1)
    assert moved["role"] != "Skenovac"

    mutations.delete_version(workspace, created["slug"])
    with pytest.raises(mutations.RosteringError):
        mutations.restore_version(workspace, created["slug"])


def test_resolve_friend_matches_to_helper(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    state = mutations.resolve_friend(workspace, 1, "Terka", "resolve", [2])
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == [2]
    assert helper["unresolved_friend_names"] == []
    assert helper["friend_name_decisions"] == {"Terka": [2]}


def test_resolve_friend_matches_to_multiple_helpers(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    state = workspace.load()
    state["helpers"].append(
        {
            "id": 3,
            "name": "Terezka",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        }
    )
    workspace.save(state)

    state = mutations.resolve_friend(workspace, 1, "Terka", "resolve", [2, 3])
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == [2, 3]
    assert helper["unresolved_friend_names"] == []
    assert helper["friend_name_decisions"] == {"Terka": [2, 3]}


def test_resolve_friend_dismiss_marks_not_attending(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    state = mutations.resolve_friend(workspace, 1, "Terka", "dismiss")
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == []
    assert helper["unresolved_friend_names"] == []
    assert helper["friend_name_decisions"] == {"Terka": None}


def test_resolve_friend_reset_takes_a_dismissal_back(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    mutations.resolve_friend(workspace, 1, "Terka", "dismiss")
    state = mutations.resolve_friend(workspace, 1, "Terka", "reset")
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["unresolved_friend_names"] == ["Terka"]
    assert helper["friend_name_decisions"] == {}


def test_resolve_friend_reset_unlinks_a_resolved_name(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    mutations.resolve_friend(workspace, 1, "Terka", "resolve", [2])
    state = mutations.resolve_friend(workspace, 1, "Terka", "reset")
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == []
    assert helper["unresolved_friend_names"] == ["Terka"]


def test_resolve_friend_can_be_changed_after_first_decision(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    mutations.resolve_friend(workspace, 1, "Terka", "resolve", [2])
    # Re-picking a different helper for the same name should update, not
    # duplicate, the friend link, and should still be revisitable afterwards.
    state = mutations.resolve_friend(workspace, 1, "Terka", "dismiss")
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == []
    assert helper["friend_name_decisions"] == {"Terka": None}

    state = mutations.resolve_friend(workspace, 1, "Terka", "resolve", [2])
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == [2]
    assert helper["friend_name_decisions"] == {"Terka": [2]}


def test_resolve_friend_tolerates_legacy_int_decision(workspace):
    # State saved before friend_name_decisions became list-valued stored a
    # single int per name; re-resolving it must not crash.
    _seed_helper_with_unresolved_friend(workspace)
    state = workspace.load()
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    helper["friends"] = [2]
    helper["unresolved_friend_names"] = []
    helper["friend_name_decisions"] = {"Terka": 2}
    workspace.save(state)

    state = mutations.resolve_friend(workspace, 1, "Terka", "dismiss")
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    assert helper["friends"] == []
    assert helper["friend_name_decisions"] == {"Terka": None}


def test_resolve_friend_unknown_name_raises(workspace):
    _seed_helper_with_unresolved_friend(workspace)
    with pytest.raises(mutations.RosteringError):
        mutations.resolve_friend(workspace, 1, "Nobody", "dismiss")


def test_resolve_friend_unknown_helper_raises(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.resolve_friend(workspace, 999, "Terka", "dismiss")


def test_reset_clears_workspace(workspace):
    _seed_two_helpers(workspace)
    data = mutations.reset_workspace(workspace)
    assert data["helpers"] == []
