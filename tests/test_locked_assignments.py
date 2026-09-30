"""Locked Assignments: the per-Helper lock flag in the Season's saved state,
carried by the Assignment serialization, kept by a full Solve and by hand
moves. Runs against a temp-dir workspace seeded with synthetic Helpers (never
anything from data/)."""
import importlib

import pytest

from rostering.domain import Assignment, Role
from rostering.persistence.serialize import assignment_from_dict, assignment_to_dict
from rostering.persistence.workspace import Workspace
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


def _helper(helper_id: int, name: str, prefs: dict) -> dict:
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": prefs,
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
    }


def _seed(workspace: Workspace, config=TWO_ROOMS) -> None:
    """Anna and Petr both dearly want Opravovatel and refuse every other role."""
    prefs = {role: "Ne" for role in ("Menic", "Skenovac", "Kreslic", "Fotograf", "Zaloha")}
    prefs["Opravovatel"] = "Ano"
    state = workspace.load()
    state["helpers"] = [_helper(1, "Anna", dict(prefs)), _helper(2, "Petr", dict(prefs))]
    workspace.save(state)
    mutations.put_config(workspace, config)


def _assignment(state, helper_id):
    return next(a for a in state["assignments"] if a["helper_id"] == helper_id)


def test_the_lock_flag_round_trips_through_assignment_serialization():
    locked = Assignment(helper_id=1, helper_name="A", building="B", room="R1", role=Role.Kreslic, locked=True)

    assert assignment_from_dict(assignment_to_dict(locked)).locked is True


def test_a_saved_assignment_without_a_lock_flag_is_unlocked():
    data = {"helper_id": 1, "helper_name": "A", "building": "B", "room": "R1", "role": "Kreslic"}

    assert assignment_from_dict(data).locked is False
    assert "locked" not in assignment_to_dict(assignment_from_dict(data))


def test_a_placed_helper_can_be_locked_and_unlocked(workspace):
    _seed(workspace)
    mutations.solve(workspace)

    locked = mutations.set_lock(workspace, 1, True)
    assert _assignment(locked, 1).get("locked") is True
    assert not _assignment(locked, 2).get("locked")
    assert mutations.get_state(workspace) == locked  # persisted

    unlocked = mutations.set_lock(workspace, 1, False)
    assert not _assignment(unlocked, 1).get("locked")


def test_only_placed_helpers_can_be_locked(workspace):
    _seed(workspace)  # not solved yet: nobody is placed

    with pytest.raises(mutations.RosteringError):
        mutations.set_lock(workspace, 1, True)
    with pytest.raises(mutations.RosteringError):
        mutations.set_lock(workspace, 999, True)


def test_a_full_solve_keeps_a_locked_assignment_and_replaces_the_others(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    # Anna is hand-placed against her preferences and locked; Petr is placed
    # against his too but left unlocked.
    mutations.move_helper(workspace, 1, "B", "R2", "Kreslic")
    mutations.move_helper(workspace, 2, "B", "R2", "Kreslic")
    mutations.set_lock(workspace, 1, True)

    state = mutations.solve(workspace)

    anna = _assignment(state, 1)
    assert (anna["building"], anna["room"], anna["role"]) == ("B", "R2", "Kreslic")
    assert anna["locked"] is True
    petr = _assignment(state, 2)
    assert petr["role"] == "Opravovatel"
    assert not petr.get("locked")


def test_a_full_solve_with_no_locks_is_unchanged(workspace):
    _seed(workspace)

    state = mutations.solve(workspace)

    assert {a["role"] for a in state["assignments"]} == {"Opravovatel"}
    assert not any(a.get("locked") for a in state["assignments"])


def test_moving_a_locked_helper_moves_the_lock_with_them(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")

    moved = _assignment(state, 1)
    assert (moved["room"], moved["role"]) == ("R2", "Zaloha")
    assert moved["locked"] is True


def test_moving_an_unlocked_helper_never_locks_it(workspace):
    _seed(workspace)
    mutations.solve(workspace)

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")

    assert not _assignment(state, 1).get("locked")


def test_a_lock_on_a_room_that_no_longer_exists_is_dropped_at_the_next_solve(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.move_helper(workspace, 1, "B", "R2", "Kreslic")
    mutations.set_lock(workspace, 1, True)
    one_room = [{"name": "B", "rooms": [TWO_ROOMS[0]["rooms"][0]], "capacities": {}}]
    mutations.put_config(workspace, one_room)

    state = mutations.solve(workspace)

    anna = _assignment(state, 1)
    assert anna["room"] == "R1"
    assert anna["role"] == "Opravovatel"
    assert not anna.get("locked")


def test_locks_are_saved_and_restored_with_a_version(workspace):
    _seed(workspace)
    workspace.create_season("2026-jaro")
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)
    saved = mutations.save_version(workspace, "Locked")
    mutations.set_lock(workspace, 1, False)

    restored = mutations.restore_version(workspace, saved["slug"])

    assert _assignment(restored, 1).get("locked") is True
