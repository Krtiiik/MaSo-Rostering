"""Dragging an Organizer's chip in the roster grid (``mutations.move_organizer``):
an unplaced Organizer takes a slot, a chip dragged out of another slot cell moves
instead of adding a second slot, and a drop on the chip's own cell changes nothing.
Runs against a temp-dir workspace with synthetic data only."""
import importlib

import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

CONFIG = [
    {"name": "Karlín", "rooms": [{"name": "K1", "capacities": {}}, {"name": "K2", "capacities": {}}], "capacities": {}},
    {"name": "Impakt", "rooms": [{"name": "I1", "capacities": {}}], "capacities": {}},
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    ws = Workspace(root=tmp_path / "seasons")
    mutations.put_config(ws, CONFIG)
    return ws


def _create(workspace, name) -> int:
    return mutations.add_organizer(workspace, name)["organizers"][-1]["id"]


def _slots(state):
    return [(e["organizer_id"], e["role"], e["building"], e.get("room")) for e in state["manual_roles"]["structural"]]


def test_an_unplaced_organizer_takes_the_slot_they_are_dropped_on(workspace):
    boss = _create(workspace, "Boss")

    state = mutations.move_organizer(workspace, boss, "VedouciBudovy", "Karlín")

    assert _slots(state) == [(boss, "VedouciBudovy", "Karlín", None)]
    organizer = state["organizers"][0]
    assert (organizer["building"], organizer["room"]) == ("Karlín", None)


def test_a_chip_dragged_from_another_slot_moves_instead_of_adding(workspace):
    boss = _create(workspace, "Boss")
    mutations.assign_organizer(workspace, boss, "VedouciMistnosti", "Karlín", "K1")

    state = mutations.move_organizer(
        workspace,
        boss,
        "PravaRuka",
        "Karlín",
        "K1",
        source={"role": "VedouciMistnosti", "building": "Karlín", "room": "K1"},
    )

    assert _slots(state) == [(boss, "PravaRuka", "Karlín", "K1")]


def test_a_drag_to_another_building_moves_the_placement(workspace):
    boss = _create(workspace, "Boss")
    mutations.assign_organizer(workspace, boss, "TechnickaPodpora", "Karlín")

    state = mutations.move_organizer(
        workspace, boss, "TechnickaPodpora", "Impakt", source={"role": "TechnickaPodpora", "building": "Karlín", "room": None}
    )

    assert _slots(state) == [(boss, "TechnickaPodpora", "Impakt", None)]
    assert state["organizers"][0]["building"] == "Impakt"


def test_dropping_a_chip_on_its_own_cell_changes_nothing(workspace):
    boss = _create(workspace, "Boss")
    before = mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")

    state = mutations.move_organizer(
        workspace, boss, "VedouciBudovy", "Karlín", source={"role": "VedouciBudovy", "building": "Karlín", "room": None}
    )

    assert state["manual_roles"] == before["manual_roles"]


def test_dropping_an_organizer_on_a_held_cell_adds_them_beside_the_holder(workspace):
    old = _create(workspace, "Old")
    new = _create(workspace, "New")
    mutations.assign_organizer(workspace, old, "VedouciBudovy", "Karlín")

    state = mutations.move_organizer(workspace, new, "VedouciBudovy", "Karlín")

    assert _slots(state) == [
        (old, "VedouciBudovy", "Karlín", None),
        (new, "VedouciBudovy", "Karlín", None),
    ]


def test_a_slot_address_that_does_not_fit_is_refused(workspace):
    boss = _create(workspace, "Boss")

    with pytest.raises(mutations.RosteringError):
        mutations.move_organizer(workspace, boss, "VedouciMistnosti", "Karlín")
