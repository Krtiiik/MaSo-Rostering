"""Tall cells: two adjacent grid rows merged top-to-bottom over the same Rooms.

The roster grid's sideways merges (``state["cell_merges"]``) join neighbouring
Rooms inside one row. A *tall merge* (``state["row_merges"]``) joins a row with
the one under it, and is only possible where both rows already have exactly the
same cell over the same Rooms: Vedoucí budovy with Pravá ruka, Pravá ruka with
Vedoucí místností, Fotograf with Focení předávání cen. The merged cell is one
slot for all its roles (see CONTEXT.md "Tall cell"). A Room belongs to at most
one tall cell per row, so a chain of three rows is never formed.

A tall merge is saved as ``{"building", "room", "row"}``: ``row`` is the upper
row's key and ``room`` the first Room of the cell's group. Pure functions only;
the data effect of merging and unmerging lives in ``webapp.mutations``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from rostering.domain import group_adjacent_rooms

# Upper row key -> the row under it that it may be merged with.
TALL_PAIRS: dict[str, str] = {
    "VedouciBudovy": "PravaRuka",
    "PravaRuka": "VedouciMistnosti",
    "Fotograf": "FoceniPredavaniCen",
}

# Rows with one cell per Building however the Rooms are merged.
BUILDING_WIDE_ROWS = frozenset({"VedouciBudovy", "TechnickaPodpora", "Registrace"})


@dataclass(frozen=True)
class TallCell:
    """One valid tall merge: ``rows`` (upper, lower) over ``rooms`` of ``building``."""

    building: str
    rooms: tuple[str, ...]
    rows: tuple[str, str]

    @property
    def upper(self) -> str:
        return self.rows[0]

    @property
    def lower(self) -> str:
        return self.rows[1]

    @property
    def address_room(self) -> Optional[str]:
        """The Room the cell's slot entries are filed under: none when the cell is
        Building-level (it holds Vedoucí budovy), else its group's first Room."""
        return None if "VedouciBudovy" in self.rows else self.rooms[0]


def row_groups(row_key: str, building: str, rooms: Sequence[str], cell_merges: dict) -> list[list[str]]:
    """The cell groups of one row over one Building's Rooms."""
    if row_key in BUILDING_WIDE_ROWS:
        return [list(rooms)]
    pairs = (cell_merges or {}).get(row_key, {}).get(building, [])
    return group_adjacent_rooms(list(rooms), pairs)


def _rooms_by_building(config: Sequence[dict]) -> dict[str, list[str]]:
    return {b["name"]: [r["name"] for r in b["rooms"]] for b in config}


def tall_cells(config: Sequence[dict], cell_merges: dict, row_merges: Sequence[dict]) -> list[TallCell]:
    """The saved tall merges that still hold, in saved order. One is dropped
    when its Building or Room is gone, its pair is not allowed, either row no
    longer has a cell over exactly its Rooms, or a row of it is already in an
    earlier tall cell over the same Rooms."""
    rooms_of = _rooms_by_building(config)
    taken: set[tuple[str, str, str]] = set()
    cells: list[TallCell] = []
    for merge in row_merges or []:
        building, room, upper = merge.get("building"), merge.get("room"), merge.get("row")
        lower = TALL_PAIRS.get(upper)
        rooms = rooms_of.get(building)
        if lower is None or rooms is None:
            continue
        upper_group = next((g for g in row_groups(upper, building, rooms, cell_merges) if g[0] == room), None)
        if upper_group is None or upper_group not in row_groups(lower, building, rooms, cell_merges):
            continue
        slots = {(row, building, name) for row in (upper, lower) for name in upper_group}
        if slots & taken:
            continue
        taken |= slots
        cells.append(TallCell(building, tuple(upper_group), (upper, lower)))
    return cells


def candidates(config: Sequence[dict], cell_merges: dict, row_merges: Sequence[dict]) -> list[TallCell]:
    """The tall merges that could be made now: a cell of an upper row whose
    lower row has a cell over exactly the same Rooms, with neither already in a
    tall cell."""
    existing = tall_cells(config, cell_merges, row_merges)
    taken = {(row, c.building, name) for c in existing for row in c.rows for name in c.rooms}
    found: list[TallCell] = []
    for building, rooms in _rooms_by_building(config).items():
        for upper, lower in TALL_PAIRS.items():
            lower_groups = row_groups(lower, building, rooms, cell_merges)
            for group in row_groups(upper, building, rooms, cell_merges):
                if group not in lower_groups:
                    continue
                if any((row, building, name) in taken for row in (upper, lower) for name in group):
                    continue
                found.append(TallCell(building, tuple(group), (upper, lower)))
    return found


def find_cell(cells: Sequence[TallCell], row_key: str, building: str, room: Optional[str]) -> Optional[TallCell]:
    """The tall cell whose upper or lower row is ``row_key`` and that holds the
    address ``building``/``room``: one of its Rooms, or (``room=None``) the
    Building-level address of a cell over Vedoucí budovy."""
    for cell in cells:
        if cell.building != building or row_key not in cell.rows:
            continue
        if (room is None and cell.address_room is None) or (room is not None and room in cell.rooms):
            return cell
    return None


def to_record(cell: TallCell) -> dict[str, Any]:
    return {"building": cell.building, "room": cell.rooms[0], "row": cell.upper}
