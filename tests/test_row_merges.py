"""Which tall merges hold, and which could be made."""
from rostering.row_merges import TallCell, candidates, find_cell, tall_cells, to_record

CONFIG = [
    {"name": "Alfa", "rooms": [{"name": "A1"}, {"name": "A2"}, {"name": "A3"}]},
    {"name": "Beta", "rooms": [{"name": "B1"}]},
]


def _merge(building, room, row):
    return {"building": building, "room": room, "row": row}


def test_vedouci_budovy_and_prava_ruka_merge_only_over_the_whole_building():
    assert candidates(CONFIG, {}, []) == [
        TallCell("Alfa", ("A1",), ("PravaRuka", "VedouciMistnosti")),
        TallCell("Alfa", ("A2",), ("PravaRuka", "VedouciMistnosti")),
        TallCell("Alfa", ("A3",), ("PravaRuka", "VedouciMistnosti")),
        TallCell("Alfa", ("A1",), ("Fotograf", "FoceniPredavaniCen")),
        TallCell("Alfa", ("A2",), ("Fotograf", "FoceniPredavaniCen")),
        TallCell("Alfa", ("A3",), ("Fotograf", "FoceniPredavaniCen")),
        TallCell("Beta", ("B1",), ("VedouciBudovy", "PravaRuka")),
        TallCell("Beta", ("B1",), ("PravaRuka", "VedouciMistnosti")),
        TallCell("Beta", ("B1",), ("Fotograf", "FoceniPredavaniCen")),
    ]
    merges = {"PravaRuka": {"Alfa": [["A1", "A2"], ["A2", "A3"]]}}
    assert TallCell("Alfa", ("A1", "A2", "A3"), ("VedouciBudovy", "PravaRuka")) in candidates(CONFIG, merges, [])


def test_two_rows_need_exactly_the_same_cell_to_merge():
    merges = {"PravaRuka": {"Alfa": [["A1", "A2"]]}}
    found = candidates(CONFIG, merges, [])
    # Pravá ruka has A1+A2 but Vedoucí místností still has A1 and A2 alone.
    assert not any(c.rows == ("PravaRuka", "VedouciMistnosti") and c.building == "Alfa" and "A1" in c.rooms for c in found)
    both = {**merges, "VedouciMistnosti": {"Alfa": [["A1", "A2"]]}}
    assert TallCell("Alfa", ("A1", "A2"), ("PravaRuka", "VedouciMistnosti")) in candidates(CONFIG, both, [])


def test_a_saved_merge_holds_while_both_rows_keep_the_same_cell():
    saved = [_merge("Beta", "B1", "VedouciBudovy")]
    assert tall_cells(CONFIG, {}, saved) == [TallCell("Beta", ("B1",), ("VedouciBudovy", "PravaRuka"))]
    # A sideways merge in the lower row that the upper row cannot share ends it.
    one_room = [{"name": "Gamma", "rooms": [{"name": "G1"}, {"name": "G2"}]}]
    saved = [_merge("Gamma", "G1", "PravaRuka")]
    assert tall_cells(one_room, {"PravaRuka": {"Gamma": [["G1", "G2"]]}}, saved) == []


def test_a_merge_of_a_vanished_room_or_building_or_unknown_pair_is_dropped():
    assert tall_cells(CONFIG, {}, [_merge("Nowhere", "X", "PravaRuka")]) == []
    assert tall_cells(CONFIG, {}, [_merge("Alfa", "A9", "PravaRuka")]) == []
    assert tall_cells(CONFIG, {}, [_merge("Alfa", "A1", "Registrace")]) == []


def test_no_row_is_in_two_tall_cells_over_the_same_rooms():
    # Beta's single Room: Vedoucí budovy+Pravá ruka and Pravá ruka+Vedoucí místností
    # would put Pravá ruka in a chain; the first saved one wins.
    saved = [_merge("Beta", "B1", "VedouciBudovy"), _merge("Beta", "B1", "PravaRuka")]
    assert [c.rows for c in tall_cells(CONFIG, {}, saved)] == [("VedouciBudovy", "PravaRuka")]
    found = candidates(CONFIG, {}, saved[:1])
    assert not any(c.building == "Beta" and c.rows[0] == "PravaRuka" for c in found)


def test_a_cell_over_vedouci_budovy_is_filed_at_building_level():
    whole = TallCell("Alfa", ("A1", "A2", "A3"), ("VedouciBudovy", "PravaRuka"))
    rooms = TallCell("Alfa", ("A1", "A2"), ("PravaRuka", "VedouciMistnosti"))
    assert whole.address_room is None and rooms.address_room == "A1"
    assert to_record(rooms) == {"building": "Alfa", "room": "A1", "row": "PravaRuka"}
    assert find_cell([whole, rooms], "PravaRuka", "Alfa", None) is whole
    assert find_cell([whole, rooms], "VedouciMistnosti", "Alfa", "A2") is rooms
    assert find_cell([whole, rooms], "VedouciMistnosti", "Alfa", "A3") is None
