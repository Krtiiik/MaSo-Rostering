"""Tall cells in the mutation layer: two adjacent leadership rows (or Fotograf and
Focení předávání cen) merged top-to-bottom into one slot for all their roles."""
import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations
from rostering.webapp.mutations import RosteringError

CONFIG = [
    {"name": "Alfa", "capacities": {}, "rooms": [{"name": "A1", "capacities": {}}, {"name": "A2", "capacities": {}}]},
    {"name": "Beta", "capacities": {}, "rooms": [{"name": "B1", "capacities": {}}]},
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    workspace = Workspace()
    workspace.create_season("2026-jaro")
    mutations.put_config(workspace, CONFIG)
    return workspace


def _organizer(workspace, name) -> int:
    return mutations.add_organizer(workspace, name)["organizers"][-1]["id"]


def _holders(workspace) -> set[tuple[str, str, object, str]]:
    state = mutations.get_state(workspace)
    names = {o["id"]: o["name"] for o in state["organizers"]}
    return {
        (e["role"], e["building"], e.get("room"), names[e["organizer_id"]])
        for e in state["manual_roles"]["structural"]
    }


def _merge_whole_alfa(workspace) -> None:
    """Pravá ruka over both Alfa Rooms as one cell, so it can meet Vedoucí budovy."""
    mutations.set_cell_merges(workspace, "PravaRuka", "Alfa", [["A1", "A2"]], True)


def test_merging_vedouci_budovy_with_prava_ruka_gives_everyone_both_roles_at_building_level(workspace):
    anna, bob = _organizer(workspace, "Anna"), _organizer(workspace, "Bob")
    mutations.assign_organizer(workspace, anna, "VedouciBudovy", "Alfa")
    mutations.assign_organizer(workspace, bob, "PravaRuka", "Alfa", "A2")
    _merge_whole_alfa(workspace)

    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)

    assert _holders(workspace) == {
        ("VedouciBudovy", "Alfa", None, "Anna"),
        ("PravaRuka", "Alfa", None, "Anna"),
        ("VedouciBudovy", "Alfa", None, "Bob"),
        ("PravaRuka", "Alfa", None, "Bob"),
    }
    state = mutations.get_state(workspace)
    assert [(o["name"], o["building"], o["room"]) for o in state["organizers"]] == [
        ("Anna", "Alfa", None),
        ("Bob", "Alfa", None),
    ]
    assert state["row_merges"] == [{"building": "Alfa", "room": "A1", "row": "VedouciBudovy"}]


def test_splitting_a_tall_cell_leaves_everyone_in_the_upper_role_only(workspace):
    anna = _organizer(workspace, "Anna")
    mutations.assign_organizer(workspace, anna, "VedouciBudovy", "Alfa")
    _merge_whole_alfa(workspace)
    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)

    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", False)

    assert _holders(workspace) == {("VedouciBudovy", "Alfa", None, "Anna")}
    assert mutations.get_state(workspace)["row_merges"] == []


def test_two_room_level_roles_are_filed_under_the_first_room_of_the_cell(workspace):
    anna, bob = _organizer(workspace, "Anna"), _organizer(workspace, "Bob")
    mutations.assign_organizer(workspace, anna, "PravaRuka", "Alfa", "A2")
    mutations.assign_organizer(workspace, bob, "VedouciMistnosti", "Alfa", "A1")
    for row in ("PravaRuka", "VedouciMistnosti"):
        mutations.set_cell_merges(workspace, row, "Alfa", [["A1", "A2"]], True)

    mutations.set_row_merge(workspace, "PravaRuka", "Alfa", "A1", True)

    assert _holders(workspace) == {
        ("PravaRuka", "Alfa", "A1", "Anna"),
        ("VedouciMistnosti", "Alfa", "A1", "Anna"),
        ("PravaRuka", "Alfa", "A1", "Bob"),
        ("VedouciMistnosti", "Alfa", "A1", "Bob"),
    }


def test_a_drop_on_a_tall_cell_gives_both_roles_and_moving_the_chip_out_takes_both(workspace):
    anna = _organizer(workspace, "Anna")
    _merge_whole_alfa(workspace)
    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)

    mutations.move_organizer(workspace, anna, "VedouciBudovy", "Alfa", None)
    assert _holders(workspace) == {("VedouciBudovy", "Alfa", None, "Anna"), ("PravaRuka", "Alfa", None, "Anna")}

    source = {"role": "VedouciBudovy", "building": "Alfa", "room": None}
    mutations.move_organizer(workspace, anna, "VedouciMistnosti", "Beta", "B1", source)
    assert _holders(workspace) == {("VedouciMistnosti", "Beta", "B1", "Anna")}


def test_removing_a_name_from_a_tall_cell_removes_it_from_both_roles(workspace):
    _merge_whole_alfa(workspace)
    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)
    mutations.set_slot_holders(workspace, "VedouciBudovy", "Alfa", None, ["Anna", "Bob"])
    assert {h[:2] + h[3:] for h in _holders(workspace)} == {
        ("VedouciBudovy", "Alfa", "Anna"),
        ("PravaRuka", "Alfa", "Anna"),
        ("VedouciBudovy", "Alfa", "Bob"),
        ("PravaRuka", "Alfa", "Bob"),
    }

    mutations.set_slot_holders(workspace, "VedouciBudovy", "Alfa", None, ["Bob"])

    assert {h[:2] + h[3:] for h in _holders(workspace)} == {("VedouciBudovy", "Alfa", "Bob"), ("PravaRuka", "Alfa", "Bob")}


def test_a_merge_needs_the_rows_to_have_the_same_cell(workspace):
    with pytest.raises(RosteringError, match="stejné místnosti"):
        mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)  # Pravá ruka has A1 and A2 apart
    with pytest.raises(RosteringError, match="neexistuje"):
        mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", False)


def test_a_sideways_merge_that_would_break_a_tall_cell_is_refused(workspace):
    _merge_whole_alfa(workspace)
    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)
    with pytest.raises(RosteringError, match="Nejdřív ji rozdělte"):
        mutations.set_cell_merges(workspace, "PravaRuka", "Alfa", [["A1", "A2"]], False)
    assert len(mutations.get_state(workspace)["row_merges"]) == 1


def test_a_layout_that_cannot_hold_a_tall_cell_splits_it(workspace, tmp_path):
    anna = _organizer(workspace, "Anna")
    mutations.assign_organizer(workspace, anna, "VedouciBudovy", "Alfa")
    _merge_whole_alfa(workspace)
    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)

    renamed = [{**CONFIG[0], "rooms": [{"name": "X1", "capacities": {}}, {"name": "A2", "capacities": {}}]}, CONFIG[1]]
    mutations.put_config(workspace, renamed)

    state = mutations.get_state(workspace)
    assert state["row_merges"] == []
    assert _holders(workspace) == {("VedouciBudovy", "Alfa", None, "Anna")}  # upper role keeps them


def test_merging_fotograf_with_focení_folds_away_its_own_entries_over_those_rooms(workspace):
    state = mutations.get_state(workspace)
    state["helpers"] = [
        {"id": 1, "name": "Cyril", "role_preferences": {}, "building_preferences": [], "friends": [],
         "can_bring_notebook": False, "can_bring_camera": True, "unresolved_friend_names": []},
    ]
    workspace.save(state)
    mutations.put_manual_roles(
        workspace,
        {
            "structural": [],
            "overlay": [
                {"role": "FoceniPredavaniCen", "building": "Alfa", "room": "A1", "helper_id": 1, "helper_name": None},
                {"role": "FoceniPredavaniCen", "building": "Beta", "room": "B1", "helper_id": 1, "helper_name": None},
            ],
        },
    )
    for row in ("Fotograf", "FoceniPredavaniCen"):
        mutations.set_cell_merges(workspace, row, "Alfa", [["A1", "A2"]], True)

    mutations.set_row_merge(workspace, "Fotograf", "Alfa", "A1", True)

    overlay = mutations.get_state(workspace)["manual_roles"]["overlay"]
    assert [(o["building"], o["room"]) for o in overlay] == [("Beta", "B1")]
    assert mutations.get_state(workspace)["row_merges"] == [{"building": "Alfa", "room": "A1", "row": "Fotograf"}]
