"""The Buildings layout read off a "Pomocníci v místnostech" sheet: Buildings and
Rooms from the merged header cells, Role counts from the coloured cells."""
import io

import openpyxl
import pytest
from openpyxl.styles import PatternFill
from openpyxl.styles.colors import Color

from rostering.ingest.building_sheet import parse_building_sheet
from rostering.webapp import mutations

NEEDED = "FFFFE599"
GRAY = "FF999999"


def _fill(rgb: str) -> PatternFill:
    return PatternFill("solid", fgColor=rgb)


def _put(ws, cell: str, value=None, fill=None) -> None:
    ws[cell] = value
    if fill:
        ws[cell].fill = fill if isinstance(fill, PatternFill) else _fill(fill)


def _sheet(build) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    build(ws)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _two_buildings(ws) -> None:
    """Alfa: rooms A1, A2 and a large A3 (a merged header over D:E). Beta: B1 and
    B2, whose header is followed by a blank cell. Rows: leaders (ignored),
    Opravovatelé (3 rows), Skenovači, Fotografové, Záloha."""
    ws.merge_cells("B1:E1")
    ws.merge_cells("F1:H1")
    ws.merge_cells("D2:E2")
    _put(ws, "B1", "Alfa")
    _put(ws, "F1", "Beta")
    for cell, name in {"B2": "A1", "C2": "A2", "D2": "A3", "F2": "B1", "G2": "B2"}.items():
        _put(ws, cell, name)
    _put(ws, "A3", "Vedoucí budovy", "FFCCCCCC")
    _put(ws, "B3", "Jiří Cihelka", "FFD9D9D9")
    ws.merge_cells("A4:A6")
    _put(ws, "A4", "Opravovatelé")
    _put(ws, "A7", "Skenovači")
    _put(ws, "A8", "Fotografové")
    _put(ws, "A9", "Záloha")
    # Opravovatelé, top rows coloured and the rest gray: column B 3 of 3, C 2, D 3,
    # E 2, F 1, G 3, H 1 -- so A1 needs 3, A2 2, A3 (D and E) 5, B1 1, B2 (G, H) 4.
    for col, rows in {"B": 3, "C": 2, "D": 3, "E": 2, "F": 1, "G": 3, "H": 1}.items():
        for row in range(4, 7):
            _put(ws, f"{col}{row}", fill=NEEDED if row - 3 <= rows else GRAY)
    for col in "BCDEFGH":
        _put(ws, f"{col}7", fill=NEEDED)
    # Fotografové: one merged slot over A1 and A2 (building-wide), one over A3
    # alone (that Room's), one over all of Beta (building-wide).
    ws.merge_cells("B8:C8")
    ws.merge_cells("D8:E8")
    ws.merge_cells("F8:H8")
    for cell in ("B8", "D8", "F8"):
        _put(ws, cell, fill=NEEDED)
    for col in "BCDEFGH":
        _put(ws, f"{col}9")  # Záloha: unfilled


def _by_name(buildings: list[dict]) -> dict:
    return {b["name"]: {"caps": b["capacities"], "rooms": {r["name"]: r["capacities"] for r in b["rooms"]}} for b in buildings}


def test_buildings_and_rooms_come_from_the_header_cells():
    layout = parse_building_sheet(_sheet(_two_buildings)).buildings
    assert [b["name"] for b in layout] == ["Alfa", "Beta"]
    assert [r["name"] for r in layout[0]["rooms"]] == ["A1", "A2", "A3"]
    # B2's blank neighbour (column H) is part of that Room, not a new one.
    assert [r["name"] for r in layout[1]["rooms"]] == ["B1", "B2"]


def test_a_coloured_cell_is_one_helper_and_a_gray_or_empty_one_is_none():
    layout = _by_name(parse_building_sheet(_sheet(_two_buildings)).buildings)
    minimum = lambda caps, role: caps.get(role, {}).get("minimum", 0)  # noqa: E731
    rooms = layout["Alfa"]["rooms"]
    assert [minimum(rooms[r], "Opravovatel") for r in ("A1", "A2", "A3")] == [3, 2, 5]  # A3 is two columns wide
    assert [minimum(layout["Beta"]["rooms"][r], "Opravovatel") for r in ("B1", "B2")] == [1, 4]
    assert minimum(rooms["A1"], "Skenovac") == 1 and minimum(rooms["A3"], "Skenovac") == 2
    assert "Zaloha" not in rooms["A1"]  # an unfilled row asks for nobody


def test_a_merged_slot_counts_once_for_one_room_or_for_the_building():
    layout = _by_name(parse_building_sheet(_sheet(_two_buildings)).buildings)
    assert layout["Alfa"]["caps"] == {"Fotograf": {"minimum": 1}}  # B8:C8 over A1 and A2
    assert layout["Alfa"]["rooms"]["A3"]["Fotograf"] == {"minimum": 1}  # D8:E8 over A3 alone
    assert "Fotograf" not in layout["Alfa"]["rooms"]["A1"]
    assert layout["Beta"]["caps"] == {"Fotograf": {"minimum": 1}}  # F8:H8 over both Rooms


def test_a_theme_gray_is_not_needed_and_a_theme_accent_is():
    def build(ws) -> None:
        ws.merge_cells("B1:C1")
        _put(ws, "B1", "Alfa")
        _put(ws, "B2", "A1")
        _put(ws, "C2", "A2")
        _put(ws, "A3", "Skenovači")
        ws.merge_cells("A3:A4")
        _put(ws, "B3", fill=PatternFill("solid", fgColor=Color(theme=0, tint=-0.35)))  # darker white
        _put(ws, "B4", fill=PatternFill("solid", fgColor=Color(theme=5)))  # an accent
        _put(ws, "C3", fill=PatternFill("solid", fgColor=Color(indexed=22)))  # indexed gray
        _put(ws, "C4", fill=PatternFill("solid", fgColor=Color(indexed=13)))  # indexed yellow

    rooms = parse_building_sheet(_sheet(build)).buildings[0]["rooms"]
    assert [r["capacities"] for r in rooms] == [{"Skenovac": {"minimum": 1}}, {"Skenovac": {"minimum": 1}}]


def test_a_room_with_no_coloured_cell_is_reported():
    def build(ws) -> None:
        _put(ws, "B1", "Alfa")
        _put(ws, "B2", "A1")
        _put(ws, "C2", "A2")
        _put(ws, "A3", "Kresliči")
        _put(ws, "B3", fill=NEEDED)
        _put(ws, "C3", fill=GRAY)

    sheet = parse_building_sheet(_sheet(build))
    assert [r["capacities"] for r in sheet.buildings[0]["rooms"]] == [{"Kreslic": {"minimum": 1}}, {}]
    assert sheet.warnings == ["Místnost „A2“ (budova Alfa) nemá v tabulce žádnou barevnou buňku."]


def test_a_sheet_without_role_rows_is_refused():
    def build(ws) -> None:
        _put(ws, "B1", "Alfa")
        _put(ws, "B2", "A1")
        _put(ws, "A3", "Vedoucí budovy")

    with pytest.raises(ValueError, match="řádky rolí"):
        parse_building_sheet(_sheet(build))


def test_a_file_that_is_not_a_workbook_is_refused():
    with pytest.raises(ValueError, match="přečíst"):
        parse_building_sheet(b"not a spreadsheet")


def test_the_mutation_raises_a_rostering_error_instead():
    with pytest.raises(mutations.RosteringError, match="přečíst"):
        mutations.read_building_sheet(b"not a spreadsheet")
    buildings, warnings = mutations.read_building_sheet(_sheet(_two_buildings))
    assert [b["name"] for b in buildings] == ["Alfa", "Beta"] and warnings == []
