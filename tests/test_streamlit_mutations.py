import importlib
from pathlib import Path

import pytest

from rostering.persistence.workspace import Workspace
from rostering.streamlit_app import mutations

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
    data = mutations.upload_responses(workspace, RAW_2026.read_bytes(), "raw-response.xlsx")
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
