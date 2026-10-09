"""Dragging a Helper out of a Room also takes them out of the Additional role
entries held there (asking first). Mutation-layer tests on a temp-dir workspace
with synthetic Helpers."""
import importlib

import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

CONFIG = [
    {
        "name": "B",
        "rooms": [
            {"name": "R1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "R2", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "R3", "capacities": {"Zaloha": {"minimum": 0}}},
        ],
        "capacities": {},
    },
    {"name": "C", "rooms": [{"name": "C1", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}},
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    ws = Workspace(root=tmp_path / "workspace")
    state = ws.load()
    state["helpers"] = [
        {
            "id": i,
            "name": name,
            "role_preferences": {},
            "building_preferences": [],
            "friends": [],
            "can_bring_notebook": True,
            "can_bring_camera": True,
            "unresolved_friend_names": [],
        }
        for i, name in ((1, "Anna"), (2, "Petr"))
    ]
    ws.save(state)
    mutations.put_config(ws, CONFIG)
    mutations.move_helper(ws, 1, "B", "R1", "Zaloha")
    mutations.move_helper(ws, 2, "B", "R1", "Zaloha")
    return ws


def _entry(role, room, helper_id):
    return {"role": role, "building": "B", "room": room, "helper_id": helper_id, "helper_name": None}


def _overlay(state):
    return [(e["role"], e["room"], e["helper_id"]) for e in state["manual_roles"]["overlay"]]


def _set_overlay(workspace, *entries):
    return mutations.put_manual_roles(workspace, {"structural": [], "overlay": list(entries)})


def test_a_move_out_of_the_room_asks_before_removing_the_room_scoped_entry(workspace):
    _set_overlay(workspace, _entry("UvadeciUcastniku", "R1", 1))
    before = mutations.get_state(workspace)

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")

    assert excinfo.value.lines == ["Manuální role: Uvaděči účastníků (B · R1)"]
    assert "Anna" in str(excinfo.value)
    assert mutations.get_state(workspace) == before  # nothing moved, nothing removed


def test_confirming_moves_the_helper_and_drops_only_their_entry_there(workspace):
    _set_overlay(
        workspace,
        _entry("UvadeciUcastniku", "R1", 1),
        _entry("UvadeciUcastniku", "R1", 2),  # someone else in the same cell
        _entry("FoceniPredavaniCen", "R2", 1),  # a cell elsewhere: not theirs to lose
    )

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha", confirmed=True)

    assert next(a for a in state["assignments"] if a["helper_id"] == 1)["room"] == "R2"
    assert _overlay(state) == [("UvadeciUcastniku", "R1", 2), ("FoceniPredavaniCen", "R2", 1)]
    assert mutations.get_state(workspace) == state  # persisted


def test_a_building_scoped_entry_survives_a_move_within_the_building(workspace):
    _set_overlay(workspace, _entry("Registrace", None, 1))

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")  # no confirmation

    assert _overlay(state) == [("Registrace", None, 1)]


def test_a_building_scoped_entry_goes_when_the_helper_leaves_the_building(workspace):
    _set_overlay(workspace, _entry("Registrace", None, 1))

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.move_helper(workspace, 1, "C", "C1", "Zaloha")
    assert excinfo.value.lines == ["Manuální role: Registrace (B)"]

    state = mutations.move_helper(workspace, 1, "C", "C1", "Zaloha", confirmed=True)
    assert _overlay(state) == []


def test_a_move_within_the_room_to_another_role_changes_nothing_else(workspace):
    _set_overlay(workspace, _entry("UvadeciUcastniku", "R1", 1))

    state = mutations.move_helper(workspace, 1, "B", "R1", "Skenovac")

    assert _overlay(state) == [("UvadeciUcastniku", "R1", 1)]


def test_a_move_between_rooms_the_row_has_merged_keeps_the_entry(workspace):
    _set_overlay(workspace, _entry("UvadeciUcastniku", "R1", 1))
    mutations.set_cell_merges(workspace, "UvadeciUcastniku", "B", [["R1", "R2"]], True)

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")  # still the same cell

    assert _overlay(state) == [("UvadeciUcastniku", "R1", 1)]
    with pytest.raises(mutations.ConfirmationRequired):
        mutations.move_helper(workspace, 1, "B", "R3", "Zaloha")


def test_the_merge_is_judged_per_row_not_for_every_row(workspace):
    _set_overlay(workspace, _entry("FoceniPredavaniCen", "R1", 1))
    mutations.set_cell_merges(workspace, "UvadeciUcastniku", "B", [["R1", "R2"]], True)  # another row

    with pytest.raises(mutations.ConfirmationRequired):
        mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")


def test_an_entry_typed_by_name_or_an_organizer_slot_is_never_touched(workspace):
    manual = {
        "structural": [{"role": "PravaRuka", "building": "B", "room": "R1", "helper_id": 1, "helper_name": None}],
        "overlay": [{"role": "UvadeciUcastniku", "building": "B", "room": "R1", "helper_id": None, "helper_name": "Anna"}],
    }
    mutations.put_manual_roles(workspace, manual)

    state = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")  # no confirmation

    assert state["manual_roles"]["structural"] == manual["structural"]
    assert state["manual_roles"]["overlay"] == manual["overlay"]


def test_placing_an_unplaced_helper_needs_no_confirmation(workspace):
    _set_overlay(workspace, _entry("UvadeciUcastniku", "R1", 1))
    state = mutations.get_state(workspace)
    state["assignments"] = [a for a in state["assignments"] if a["helper_id"] != 1]
    workspace.save(state)

    moved = mutations.move_helper(workspace, 1, "B", "R2", "Zaloha")

    assert _overlay(moved) == [("UvadeciUcastniku", "R1", 1)]
