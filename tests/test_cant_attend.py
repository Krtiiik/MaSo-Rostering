"""Can't attend: the per-Helper flag in the Season's saved state, its confirmed
cascade (Assignment, lock and Manual role entries) and the stale-roster flag it
raises. Mutation-layer tests run against a temp-dir workspace seeded with
synthetic Helpers (never anything from data/); the solver and export are also
exercised on plain domain objects."""
import importlib
import io
from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    ManualRoles,
    OverlayAssignment,
    OverlayRole,
    Role,
    RoleCapacity,
    Room,
    SolveResult,
    StructuralAssignment,
    StructuralRole,
)
from rostering.export.excel import write_roster
from rostering.export.people import counted_people
from rostering.persistence.serialize import helper_from_dict, helper_to_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.streamlit_app import mutations

TWO_ROOMS = [
    {
        "name": "B",
        "rooms": [
            {"name": "R1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "R2", "capacities": {"Zaloha": {"minimum": 0}}},
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


def _helper(helper_id: int, name: str, friends=(), **extra) -> dict:
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": list(friends),
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
        **extra,
    }


def _seed(workspace: Workspace, config=TWO_ROOMS, helpers=None) -> None:
    state = workspace.load()
    state["helpers"] = helpers or [_helper(1, "Anna"), _helper(2, "Petr"), _helper(3, "Jana")]
    workspace.save(state)
    mutations.put_config(workspace, config)


def _assignment(state, helper_id):
    return next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)


def _flagged(state, helper_id) -> bool:
    return next(h for h in state["helpers"] if h["id"] == helper_id).get("cant_attend", False)


def _manual(workspace, structural=(), overlay=()):
    return mutations.put_manual_roles(workspace, {"structural": list(structural), "overlay": list(overlay)})


# -- the flag on the Helper record ----------------------------------------------------


def test_the_flag_defaults_to_off_and_round_trips_through_helper_serialization():
    assert Helper(id=1, name="A").cant_attend is False
    flagged = Helper(id=1, name="A", cant_attend=True)

    assert helper_from_dict(helper_to_dict(flagged)).cant_attend is True
    assert helper_from_dict({"id": 1, "name": "A"}).cant_attend is False  # saved before the flag existed


# -- flagging and un-flagging ---------------------------------------------------------


def test_flagging_a_helper_with_nothing_to_clear_applies_at_once_without_staleness(workspace):
    _seed(workspace)

    state = mutations.set_cant_attend(workspace, 1, True)

    assert _flagged(state, 1)
    assert _flagged(mutations.get_state(workspace), 1)  # persisted
    assert mutations.stale_reasons(state) == []


def test_flagging_an_unplaced_helper_applies_at_once_even_when_a_roster_exists(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    state = workspace.load()
    state["helpers"].append(_helper(4, "Eva"))  # registered after the solve, so unplaced
    workspace.save(state)
    roster_before = mutations.get_state(workspace)["assignments"]

    state = mutations.set_cant_attend(workspace, 4, True)

    assert _flagged(state, 4)
    assert state["assignments"] == roster_before
    assert mutations.stale_reasons(state) == []  # nothing was cleared, so the roster is not stale


def test_unknown_helper_is_rejected(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError):
        mutations.set_cant_attend(workspace, 99, True)


def test_a_flagged_helper_is_excluded_from_the_solve(workspace):
    _seed(workspace)
    mutations.set_cant_attend(workspace, 2, True)

    state = mutations.solve(workspace)

    assert sorted(a["helper_id"] for a in state["assignments"]) == [1, 3]


def test_a_solve_with_every_helper_flagged_is_refused(workspace):
    _seed(workspace)
    for helper_id in (1, 2, 3):
        mutations.set_cant_attend(workspace, helper_id, True)

    with pytest.raises(mutations.RosteringError, match="zúčastnit"):
        mutations.solve(workspace)


def test_unflagging_returns_the_helper_to_the_next_solve_without_solving(workspace):
    _seed(workspace)
    mutations.set_cant_attend(workspace, 2, True)
    solved = mutations.solve(workspace)

    state = mutations.set_cant_attend(workspace, 2, False)

    assert not _flagged(state, 2)
    assert state["assignments"] == solved["assignments"]  # no automatic re-solve
    assert mutations.stale_reasons(state) == []
    assert sorted(a["helper_id"] for a in mutations.solve(workspace)["assignments"]) == [1, 2, 3]


def test_a_friend_preference_naming_a_flagged_helper_stops_scoring_silently(workspace):
    _seed(workspace, helpers=[_helper(1, "Anna", friends=[2]), _helper(2, "Petr"), _helper(3, "Jana")])
    mutations.set_cant_attend(workspace, 2, True)

    state = mutations.solve(workspace)

    assert state["diagnostics"]["satisfied_friend_pairs"] == []
    assert state["diagnostics"]["unsatisfied_friend_pairs"] == []
    assert state["ingestion_warnings"] == []
    assert _helper_friends(state, 1) == [2]  # the request itself is kept, so un-flagging restores it


def _helper_friends(state, helper_id):
    return next(h for h in state["helpers"] if h["id"] == helper_id)["friends"]


def test_hand_moves_do_not_score_friend_pairs_naming_a_flagged_helper(workspace):
    _seed(workspace, helpers=[_helper(1, "Anna", friends=[2]), _helper(2, "Petr"), _helper(3, "Jana")])
    mutations.set_cant_attend(workspace, 2, True)
    mutations.solve(workspace)

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")

    assert state["diagnostics"]["unsatisfied_friend_pairs"] == []


# -- confirmation and the cascade -----------------------------------------------------


def test_flagging_a_placed_helper_asks_for_confirmation_naming_what_is_cleared(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)
    before = mutations.get_state(workspace)

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.set_cant_attend(workspace, 1, True)

    placed = _assignment(before, 1)
    message = str(excinfo.value)
    assert "Anna" in message
    assert placed["building"] in message and placed["room"] in message
    assert "uzamčeno" in message.lower()
    assert excinfo.value.lines  # the per-item list the dialog shows
    assert mutations.get_state(workspace) == before  # nothing changed


def test_the_confirmation_names_manual_role_entries_too(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    _manual(
        workspace,
        structural=[{"role": "VedouciBudovy", "building": "B", "room": None, "helper_id": 1, "helper_name": None}],
        overlay=[{"role": "Registrace", "building": "B", "room": None, "helper_id": 1, "helper_name": None}],
    )

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.set_cant_attend(workspace, 1, True)

    assert "Vedoucí budovy" in str(excinfo.value)
    assert "Registrace" in str(excinfo.value)


def test_confirming_clears_the_assignment_its_lock_and_every_manual_role_entry(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)
    _manual(
        workspace,
        structural=[
            {"role": "VedouciBudovy", "building": "B", "room": None, "helper_id": 1, "helper_name": None},
            {"role": "TechnickaPodpora", "building": "B", "room": None, "helper_id": 2, "helper_name": None},
            {"role": "PravaRuka", "building": "B", "room": "R1", "helper_id": None, "helper_name": "Anna"},
        ],
        overlay=[
            {"role": "Registrace", "building": "B", "room": None, "helper_id": 1, "helper_name": None},
            {"role": "UvadeciUcastniku", "building": "B", "room": "R1", "helper_id": 2, "helper_name": None},
        ],
    )
    petr_before = _assignment(mutations.get_state(workspace), 2)

    state = mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    assert _flagged(state, 1)
    assert _assignment(state, 1) is None
    assert _assignment(state, 2) == petr_before  # nobody else moves
    assert [(s["role"], s["helper_id"]) for s in state["manual_roles"]["structural"]] == [
        ("TechnickaPodpora", 2),
        ("PravaRuka", None),  # a hand-typed name is not matched by id
    ]
    assert [(o["role"], o["helper_id"]) for o in state["manual_roles"]["overlay"]] == [("UvadeciUcastniku", 2)]
    assert mutations.get_state(workspace) == state  # persisted


def test_a_helper_with_only_manual_role_entries_still_needs_confirmation(workspace):
    _seed(workspace)
    _manual(workspace, overlay=[{"role": "Registrace", "building": "B", "room": None, "helper_id": 3, "helper_name": None}])

    with pytest.raises(mutations.ConfirmationRequired):
        mutations.set_cant_attend(workspace, 3, True)

    state = mutations.set_cant_attend(workspace, 3, True, confirmed=True)
    assert state["manual_roles"]["overlay"] == []


def test_unflagging_never_restores_the_assignment_or_its_lock_or_role_entries(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)
    _manual(workspace, overlay=[{"role": "Registrace", "building": "B", "room": None, "helper_id": 1, "helper_name": None}])
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    state = mutations.set_cant_attend(workspace, 1, False)

    assert not _flagged(state, 1)
    assert _assignment(state, 1) is None
    assert state["manual_roles"]["overlay"] == []


def test_flagging_an_already_flagged_helper_changes_nothing(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)
    before = mutations.get_state(workspace)

    assert mutations.set_cant_attend(workspace, 1, True) == before


# -- the stale-roster flag ------------------------------------------------------------


def test_clearing_raises_the_stale_flag_with_a_reason_naming_the_helper(workspace):
    _seed(workspace)
    mutations.solve(workspace)

    state = mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    [reason] = mutations.stale_reasons(state)
    assert "Anna" in reason


def test_export_is_refused_while_stale_with_the_reason_and_allowed_after_the_next_solve(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    assert mutations.export_xlsx_bytes(workspace)[:2] == b"PK"
    state = mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    with pytest.raises(mutations.RosteringError) as excinfo:
        mutations.export_xlsx_bytes(workspace)
    assert mutations.stale_reasons(state)[0] in str(excinfo.value)

    solved = mutations.solve(workspace)
    assert mutations.stale_reasons(solved) == []
    assert mutations.stale_reasons(mutations.get_state(workspace)) == []
    assert mutations.export_xlsx_bytes(workspace)[:2] == b"PK"


def test_the_stale_flag_is_reusable_and_keeps_every_reason(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)
    state = mutations.set_cant_attend(workspace, 2, True, confirmed=True)

    reasons = mutations.stale_reasons(state)
    assert len(reasons) == 2
    assert "Anna" in reasons[0] and "Petr" in reasons[1]

    edited = mutations.mark_stale(workspace, "A Forced friends group changed")
    assert mutations.stale_reasons(edited)[-1] == "A Forced friends group changed"
    assert mutations.mark_stale(workspace, "A Forced friends group changed") == edited  # not duplicated


def test_a_failed_solve_leaves_the_stale_flag_up(workspace, monkeypatch):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    def _no_roster(comp, config=None, **kwargs):
        raise mutations.NoRosterFound(config.time_limit_seconds)

    monkeypatch.setattr(mutations, "solve_competition", _no_roster)
    with pytest.raises(mutations.RosteringError):
        mutations.solve(workspace)

    assert mutations.stale_reasons(mutations.get_state(workspace))


def test_hand_moves_do_not_clear_the_stale_flag(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    state = mutations.move_helper(workspace, 2, "B", "R2", "Zaloha")

    assert mutations.stale_reasons(state)


def test_the_flag_and_the_stale_state_round_trip_through_versions(workspace):
    _seed(workspace)
    workspace.create_season("2026-jaro")
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)
    version = mutations.save_version(workspace, "flagged")
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, False)

    restored = mutations.restore_version(workspace, version["slug"])

    assert _flagged(restored, 1)
    assert mutations.stale_reasons(restored)
    with pytest.raises(mutations.RosteringError):
        mutations.export_xlsx_bytes(workspace)


def test_a_state_saved_before_the_stale_flag_existed_is_not_stale(workspace):
    _seed(workspace)
    state = workspace.load()
    state.pop("stale_reasons", None)
    workspace.save(state)

    assert mutations.stale_reasons(mutations.get_state(workspace)) == []


# -- re-upload and seasons ------------------------------------------------------------

_NAME = "Tvoje jméno a příjmení"
_EMAIL = "E-mailová adresa"


def _survey(rows) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 2, 1)] * len(rows),
            _NAME: [name for name, _ in rows],
            _EMAIL: [email for _, email in rows],
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


def _helper_named(state, name):
    return next(h for h in state["helpers"] if h["name"] == name)


def test_the_flag_survives_the_helper_resubmitting_the_survey(workspace):
    rows = [("Anna Nováková", "anna@example.test"), ("Petr Svoboda", "petr@example.test")]
    state = mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label="2026-jaro")
    mutations.set_cant_attend(workspace, _helper_named(state, "Anna Nováková")["id"], True)

    # A later export: Anna re-submitted (a new row, another position) and Petr is unchanged.
    later = [("Petr Svoboda", "petr@example.test"), ("Anna Nováková", "ANNA@example.test ")]
    state = mutations.upload_responses(workspace, _survey(later), "s.xlsx")

    assert _flagged(state, _helper_named(state, "Anna Nováková")["id"])
    assert not _flagged(state, _helper_named(state, "Petr Svoboda")["id"])


def test_the_flag_is_per_season(workspace):
    rows = [("Anna Nováková", "anna@example.test")]
    state = mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label="2025-podzim")
    mutations.set_cant_attend(workspace, state["helpers"][0]["id"], True)

    mutations.new_season(workspace)
    state = mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label="2026-jaro")

    assert not _flagged(state, state["helpers"][0]["id"])


# -- the solver, on domain objects ----------------------------------------------------


def _building(*room_names):
    rooms = [Room(name=n, capacities={Role.Zaloha: RoleCapacity(0)}) for n in room_names]
    return Building(name="B", rooms=rooms)


def test_the_solver_gives_a_flagged_helper_no_assignment():
    comp = Competition(
        buildings={"B": _building("R1")},
        helpers=[Helper(id=1, name="A"), Helper(id=2, name="B", cant_attend=True)],
    )

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert [a.helper_id for a in result.assignments] == [1]


def test_a_friend_preference_naming_a_flagged_helper_contributes_nothing_to_the_objective():
    building = _building("R1", "R2")
    with_flagged_friend = Competition(
        buildings={"B": building},
        helpers=[Helper(id=1, name="A", friends=[2]), Helper(id=2, name="B", cant_attend=True)],
    )
    without_friend = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="A")])

    result = solve_competition(with_flagged_friend, SolverConfig(time_limit_seconds=5))
    baseline = solve_competition(without_friend, SolverConfig(time_limit_seconds=5))

    assert result.satisfied_friend_pairs == [] and result.unsatisfied_friend_pairs == []
    assert result.objective_value == baseline.objective_value


def test_the_broken_rule_check_does_not_count_a_flagged_helper():
    comp = Competition(
        buildings={"B": Building(name="B", rooms=[Room(name="R1", capacities={Role.Opravovatel: RoleCapacity(1)})])},
        helpers=[Helper(id=1, name="A", cant_attend=True)],
    )
    placed = [Assignment(helper_id=1, helper_name="A", building="B", room="R1", role=Role.Opravovatel)]

    assert [b.family for b in check_roster(comp, placed)] == ["minimums"]


# -- export counts, on domain objects -------------------------------------------------


def test_the_export_counts_leave_out_a_flagged_helper_however_they_are_placed():
    comp = Competition(
        buildings={"B": _building("R1")},
        helpers=[
            Helper(id=1, name="Anna", tshirt_size="M"),
            Helper(id=2, name="Petr", tshirt_size="L", cant_attend=True),
        ],
    )
    result = SolveResult(
        assignments=[
            Assignment(helper_id=1, helper_name="Anna", building="B", room="R1", role=Role.Zaloha),
            Assignment(helper_id=2, helper_name="Petr", building="B", room="R1", role=Role.Zaloha),
        ],
        status="OPTIMAL",
        objective_value=0,
    )
    manual = ManualRoles(
        structural=[StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="B", helper_id=2)],
        overlay=[OverlayAssignment(role=OverlayRole.Registrace, helper_id=2, building="B")],
    )

    assert [p.name for p in counted_people(comp, result, manual)] == ["Anna"]


def test_the_exported_roster_workbook_does_not_name_a_flagged_helper(tmp_path):
    comp = Competition(
        buildings={"B": _building("R1")},
        helpers=[Helper(id=1, name="Anna"), Helper(id=2, name="Petr", cant_attend=True)],
    )
    result = SolveResult(
        assignments=[
            Assignment(helper_id=1, helper_name="Anna", building="B", room="R1", role=Role.Zaloha),
            Assignment(helper_id=2, helper_name="Petr", building="B", room="R1", role=Role.Zaloha),
        ],
        status="OPTIMAL",
        objective_value=0,
    )
    out = tmp_path / "roster.xlsx"

    write_roster(comp, result, ManualRoles(), out)

    text = " ".join(
        str(cell.value)
        for sheet in openpyxl.load_workbook(out).worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    )
    assert "Anna" in text and "Petr" not in text


def test_a_flagged_helper_cannot_be_placed_by_hand(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    with pytest.raises(mutations.RosteringError, match="Nemůže se zúčastnit"):
        mutations.move_helper(workspace, 1, "B", "R1", "Zaloha")

    assert _assignment(mutations.get_state(workspace), 1) is None
