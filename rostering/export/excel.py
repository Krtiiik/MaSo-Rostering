"""Formatted Excel roster export.

Reproduces the layout and styling of the historical hand-built rosters
(`data/rosters/Rozdělení pomocníků Praha - *.xlsx`): a single sheet with one
column per room, grouped under merged building headers, and one row-block
per role. The organizer can additionally merge two or more adjacent rooms'
*cells* within a single row of the roster grid (see
`rostering.domain.group_adjacent_rooms`) — like merging cells in a
spreadsheet, this only affects that one row (e.g. one solved role, Pravá
ruka, or Vedoucí místností); the room header row and every other row still
show those rooms as separate columns. Row-block order top to bottom:
Vedoucí budovy (building-wide), Pravá ruka and Vedoucí místností (per room,
each with its own merges), the 6 solved roles (Opravovatel/Měnič/.../
Fotograf; Záloha is deferred to the bottom to match the historical layout),
the overlay roles (Uvaděči účastníků, Focení předávání cen, Registrace),
then Záloha and Technická podpora. See CLAUDE.md for the role glossary.

A Large room (see `_large_rooms` and CONTEXT.md) is drawn across two adjacent
columns in every Role band, chosen automatically at each export: the band's
first column fills to a sheet-wide height and the second takes the rest. A
merged Room group stays one wide cell and may stretch its own band, and a
Large room in that band fills its first column down to the stretched height;
a Room merged with a neighbour in any room-scoped row is never Large. Export
only; the in-app grid keeps one column per Room.

A second sheet, "Trička", follows the roster sheet: T-shirt counts per size
and Building for the shirt order (who is counted lives in
`rostering.export.people`). One helper-list sheet per Building follows it, in
config order, for the Building lead to print (sorted by
`rostering.export.collation`).
"""
from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Optional

import xlsxwriter

from rostering.domain import (
    TSHIRT_SIZES,
    UNKNOWN_TSHIRT_SIZE,
    Competition,
    Helper,
    ManualRoles,
    OverlayRole,
    Role,
    SolveResult,
    StructuralRole,
    group_adjacent_rooms,
)
from rostering.export.collation import czech_sort_key
from rostering.export.people import CountedPerson, counted_people, without_absent

_SHEET_NAME = "Pomocníci v místnostech"
_TSHIRT_SHEET_NAME = "Trička"

# Per-Building helper-list sheets: column titles and Excel's worksheet-name rules.
_LIST_HEADER = ("Jméno", "Velikost trička", "Místnost", "Role")
_FORBIDDEN_SHEET_CHARS = frozenset("/\\?*[]:")
_MAX_SHEET_NAME = 31
_FALLBACK_SHEET_NAME = "Budova"  # for a Building whose name is nothing but forbidden characters

# (label-column color, data-cell color) per solved role.
_ROLE_COLORS: dict[Role, tuple[str, str]] = {
    Role.Opravovatel: ("#FFD966", "#FFE599"),
    Role.Menic: ("#F6B26B", "#F9CB9C"),
    Role.Skenovac: ("#E06666", "#EA9999"),
    Role.Kreslic: ("#6D9EEB", "#9FC5E8"),
    Role.Fotograf: ("#93C47D", "#B6D7A8"),
}
_ROLE_ORDER = [Role.Opravovatel, Role.Menic, Role.Skenovac, Role.Kreslic, Role.Fotograf]

# Plural/collective group-header text, matching the historical roster wording
# (the Role enum values themselves are singular, used elsewhere for per-helper display).
_ROLE_LABELS: dict[Role, str] = {
    Role.Opravovatel: "Opravovatelé",
    Role.Menic: "Měniči",
    Role.Skenovac: "Skenovači",
    Role.Kreslic: "Kresliči",
    Role.Fotograf: "Fotografové",
    Role.Zaloha: "Záloha",
}

_STRUCTURAL_COLOR = ("#CCCCCC", "#D9D9D9")

# Fill for a helper slot that exists (row-block sized for it) but has no
# helper assigned, so an empty slot reads as "empty" rather than as if it
# were just another same-colored cell in the role's block.
_EMPTY_SLOT_COLOR = "#F2F2F2"

_OVERLAY_COLORS: dict[OverlayRole, tuple[str, str]] = {
    OverlayRole.UvadeciUcastniku: ("#D5A6BD", "#EAD1DC"),
    OverlayRole.FoceniPredavaniCen: ("#C27BA0", "#D9A6C2"),
    OverlayRole.Registrace: ("#B4A7D6", "#D9D2E9"),
}
_OVERLAY_ORDER = [OverlayRole.UvadeciUcastniku, OverlayRole.FoceniPredavaniCen, OverlayRole.Registrace]

_WRAP_ROW_HEIGHT = 30

# Structural roles whose row is per room (each Room has its own cell, with the
# row's own adjacent-room merges); the other structural roles are building-wide.
_ROOM_SCOPED_STRUCTURAL_ROLES = (StructuralRole.PravaRuka, StructuralRole.VedouciMistnosti)

# A Room is a candidate for two-column overflow ("Large room" in CONTEXT.md)
# when its size is at least this multiple of the sheet-wide median Room size.
_LARGE_ROOM_THRESHOLD = Fraction(3, 2)
# With fewer Rooms than this holding Helpers, a median means nothing: no Room
# overflows.
_LARGE_ROOM_MIN_ROOMS = 3
# Suffix of the solver's synthetic fallback Rooms, ignored by the detection.
_UNCONFIGURED_SUFFIX = "(unconfigured)"

RoomKey = tuple[str, str]  # (building name, room name)


def _large_rooms(
    room_role_counts: dict[RoomKey, dict[Role, int]],
    merged_rooms: set[RoomKey],
    merged_heights: dict[Role, int],
    room_role_minimums: Optional[dict[RoomKey, dict[Role, int]]] = None,
) -> set[RoomKey]:
    """The Rooms drawn across two columns in the export: Large rooms that
    actually need the second column.

    ``room_role_counts`` holds, for every configured Room, how many Helpers it
    has in each of the five Room-band Roles (Záloha and Manual roles are not
    part of a Room's size). ``merged_rooms`` are Rooms the user merged with a
    neighbour in any row; they never overflow. ``merged_heights`` is, per
    Role band, the rows the tallest merged Room group needs there: a group is
    one wide cell that can stretch the band, and a Large room that fits the
    stretched band needs no second column. ``room_role_minimums`` are the
    configured minimum headcounts: a Room's band is as tall as its minimum or
    its placed Helpers, whichever is larger, exactly as ``write_roster`` sizes
    it, so a Room is only given a second column when that column will hold
    someone. See CONTEXT.md, "Large room"."""
    minimums = room_role_minimums or {}
    rooms = {k: v for k, v in room_role_counts.items() if not k[1].endswith(_UNCONFIGURED_SUFFIX)}
    size = {k: sum(v.values()) for k, v in rooms.items()}
    sizes = sorted(s for s in size.values() if s > 0)
    if len(sizes) < _LARGE_ROOM_MIN_ROOMS:
        return set()

    mid = len(sizes) // 2
    twice_median = sizes[mid] * 2 if len(sizes) % 2 else sizes[mid - 1] + sizes[mid]
    threshold = _LARGE_ROOM_THRESHOLD * Fraction(twice_median, 2)
    candidates = {k for k, s in size.items() if s > 0 and s >= threshold and k not in merged_rooms}

    def need(key: RoomKey, role: Role) -> int:
        return max(rooms[key].get(role, 0), minimums.get(key, {}).get(role, 0))

    # A band's first-column height K is what write_roster draws: the tallest
    # non-overflow Room (its minimum or placed Helpers), the tallest merged
    # group, or half the need of an overflow Room, whichever is greatest. A
    # candidate needs a second column only where it stands taller than K.
    # Dropping a candidate makes it an ordinary, full-height Room and so can
    # raise K, hence the loop until the set holds still.
    while True:
        first_column = {
            role: max(
                [merged_heights.get(role, 0)]
                + [-(-need(k, role) // 2) if k in candidates else need(k, role) for k in rooms]
            )
            for role in _ROLE_ORDER
        }
        needing = {k for k in candidates if any(rooms[k].get(role, 0) > first_column[role] for role in _ROLE_ORDER)}
        if needing == candidates:
            return candidates
        candidates = needing


def _annotate(helper: Helper | None, fallback_name: str = "") -> str:
    """Append the historical roster's "(n)"/"(f)" equipment tags to a helper's name."""
    if helper is None:
        return fallback_name
    tags = []
    if helper.can_bring_notebook:
        tags.append("n")
    if helper.can_bring_camera:
        tags.append("f")
    suffix = f" ({', '.join(tags)})" if tags else ""
    return f"{helper.name}{suffix}"


def _write_tshirt_sheet(workbook: xlsxwriter.Workbook, building_names: list[str], people: list[CountedPerson]) -> None:
    """The "Trička" sheet: T-shirt sizes as rows, Buildings (config order) as
    columns, then a Celkem column and a total row. Counted per Building only;
    the Unknown row is shown only when someone counted is Unknown."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for person in people:
        if person.building in building_names:
            counts[(person.tshirt_size, person.building)] += 1

    sizes = list(TSHIRT_SIZES)
    if any(size == UNKNOWN_TSHIRT_SIZE for size, _ in counts):
        sizes.append(UNKNOWN_TSHIRT_SIZE)

    ws = workbook.add_worksheet(_TSHIRT_SHEET_NAME)
    base = {"font_name": "Arial", "align": "center", "border": 1}
    header_fmt = workbook.add_format({**base, "bold": True})
    body_fmt = workbook.add_format(base)
    total_fmt = workbook.add_format({**base, "bold": True})

    ws.write(0, 0, "Velikost", header_fmt)
    for c, name in enumerate(building_names, start=1):
        ws.write(0, c, name, header_fmt)
    celkem_col = len(building_names) + 1
    ws.write(0, celkem_col, "Celkem", header_fmt)

    column_totals = [0] * len(building_names)
    for r, size in enumerate(sizes, start=1):
        ws.write(r, 0, size, header_fmt)
        row_total = 0
        for c, name in enumerate(building_names):
            n = counts.get((size, name), 0)
            ws.write_number(r, c + 1, n, body_fmt)
            row_total += n
            column_totals[c] += n
        ws.write_number(r, celkem_col, row_total, total_fmt)

    total_row = len(sizes) + 1
    ws.write(total_row, 0, "Celkem", header_fmt)
    for c, n in enumerate(column_totals, start=1):
        ws.write_number(total_row, c, n, total_fmt)
    ws.write_number(total_row, celkem_col, sum(column_totals), total_fmt)

    ws.set_column(0, 0, 10)
    ws.set_column(1, celkem_col, max([len(n) for n in building_names] + [8]) + 2)


def _list_sheet_names(building_names: list[str], taken: list[str]) -> list[str]:
    """One valid, unique worksheet name per Building, in the given order.

    Forbidden characters (``/ \\ ? * [ ] :``) are removed and the name cut to
    Excel's 31 characters; a name that comes out blank, or starting/ending with
    an apostrophe (also invalid), is repaired. Names are compared ignoring case,
    as Excel does, and a clash — with an earlier list sheet or with the
    ``taken`` sheets (the roster and "Trička") — gets a " (2)", " (3)", ...
    suffix, the name cut so the suffix still fits."""
    used = {name.lower() for name in taken}
    names = []
    for building in building_names:
        base = "".join(ch for ch in building if ch not in _FORBIDDEN_SHEET_CHARS)
        base = base[:_MAX_SHEET_NAME].strip("'")
        if not base.strip():
            base = _FALLBACK_SHEET_NAME
        name, n = base, 1
        while name.lower() in used:
            n += 1
            suffix = f" ({n})"
            name = base[: _MAX_SHEET_NAME - len(suffix)].rstrip("'") + suffix
        used.add(name.lower())
        names.append(name)
    return names


def _write_building_list_sheets(
    workbook: xlsxwriter.Workbook, building_names: list[str], people: list[CountedPerson]
) -> None:
    """One helper-list sheet per Building (config order), for the Building
    lead to print: Jméno, Velikost trička, Místnost, Role, sorted by Czech
    collation on the name exactly as entered. No phone numbers, no equipment
    tags. Who is listed is the same set as the "Trička" counts."""
    sheet_names = _list_sheet_names(building_names, [_SHEET_NAME, _TSHIRT_SHEET_NAME])
    base = {"font_name": "Arial", "border": 1}
    header_fmt = workbook.add_format({**base, "bold": True, "align": "center"})
    body_fmt = workbook.add_format(base)
    centered_fmt = workbook.add_format({**base, "align": "center"})

    for building, sheet_name in zip(building_names, sheet_names):
        listed = sorted(
            (p for p in people if p.building == building),
            key=lambda p: czech_sort_key(p.name),
        )
        ws = workbook.add_worksheet(sheet_name)
        for c, title in enumerate(_LIST_HEADER):
            ws.write(0, c, title, header_fmt)
        for r, person in enumerate(listed, start=1):
            ws.write_string(r, 0, person.name, body_fmt)
            ws.write_string(r, 1, person.tshirt_size, centered_fmt)
            if person.room:
                ws.write_string(r, 2, person.room, body_fmt)
            else:
                ws.write_blank(r, 2, None, body_fmt)
            ws.write_string(r, 3, person.role, body_fmt)

        rows = [[p.name, p.tshirt_size, p.room, p.role] for p in listed]
        for c, title in enumerate(_LIST_HEADER):
            longest = max([len(title)] + [len(row[c]) for row in rows])
            ws.set_column(c, c, min(longest + 2, 50))
        ws.freeze_panes(1, 0)
        ws.repeat_rows(0)
        ws.fit_to_pages(1, 0)


def write_roster(
    comp: Competition,
    result: SolveResult,
    manual: ManualRoles,
    out_path: str | Path,
    cell_merges: Optional[dict[str, dict[str, list[list[str]]]]] = None,
) -> None:
    comp, result, manual = without_absent(comp, result, manual)
    helper_by_id = {h.id: h for h in comp.helpers}
    buildings = [b for b in comp.buildings.values() if b.rooms]
    cell_merges = cell_merges or {}

    def row_groups(row_key: str, building_name: str, room_names: list[str]) -> list[list[str]]:
        pairs = cell_merges.get(row_key, {}).get(building_name, [])
        return group_adjacent_rooms(room_names, pairs)

    def annotate_id(helper_id: int, fallback_name: str = "") -> str:
        return _annotate(helper_by_id.get(helper_id), fallback_name)

    organizer_names = {o.id: o.name for o in comp.organizers}

    def slot_name(entry) -> str:
        """The name an Organizer role slot shows: the tracked Organizer's, else
        (a legacy entry, see StructuralAssignment) the Helper's, with the
        equipment tags, or the hand-typed text."""
        if entry.organizer_id is not None:
            return organizer_names.get(entry.organizer_id, f"#{entry.organizer_id}")
        return annotate_id(entry.helper_id, entry.helper_name or "")

    room_obj = {(b.name, r.name): r for b in buildings for r in b.rooms}

    # Each solved Role's row-groups per Building (a merged group is one wide
    # cell for that Role only) and the Helpers placed in each, worked out
    # before any cell is written.
    role_groups_by_building: dict[Role, dict[str, list[list[str]]]] = {
        solved_role: {b.name: row_groups(solved_role.name, b.name, [r.name for r in b.rooms]) for b in buildings}
        for solved_role in _ROLE_ORDER
    }
    room_to_group: dict[tuple[Role, str, str], tuple[str, ...]] = {}
    for solved_role in _ROLE_ORDER:
        for b in buildings:
            for group in role_groups_by_building[solved_role][b.name]:
                group_id = tuple(group)
                for n in group:
                    room_to_group[(solved_role, b.name, n)] = group_id

    group_placements: dict[tuple[Role, str, tuple[str, ...]], list[str]] = defaultdict(list)
    for a in result.assignments:
        group_id = room_to_group.get((a.role, a.building, a.room))
        if group_id is None:
            continue
        group_placements[(a.role, a.building, group_id)].append(annotate_id(a.helper_id, a.helper_name))

    def group_need(solved_role: Role, building_name: str, group: list[str]) -> int:
        """Rows a cell (a Room, or a merged group of Rooms) needs in its
        Role's band: the configured minimum headcount and the number of
        Helpers actually placed, whichever is larger. A merged cell must fit
        the *sum* across its Rooms — they share one cell — not the max of any
        single Room."""
        group_min = 0
        for n in group:
            cap = room_obj[(building_name, n)].capacities.get(solved_role)
            if cap:
                group_min += cap.minimum
        group_count = len(group_placements.get((solved_role, building_name, tuple(group)), []))
        return max(group_min, group_count)

    # Which Rooms are drawn across two columns (a Large room that needs it),
    # judged from the roster as it stands. A Room the user merged with a
    # neighbour in any of its room-scoped rows never overflows, whichever row
    # it is merged in and whichever Role band the merge stretches.
    room_role_counts: dict[RoomKey, dict[Role, int]] = {key: defaultdict(int) for key in room_obj}
    for a in result.assignments:
        if a.role in _ROLE_ORDER and (a.building, a.room) in room_role_counts:
            room_role_counts[(a.building, a.room)][a.role] += 1
    merged_rooms: set[RoomKey] = set()
    merged_heights: dict[Role, int] = {}
    for b in buildings:
        room_names = [r.name for r in b.rooms]
        for structural_role in _ROOM_SCOPED_STRUCTURAL_ROLES:
            for group in row_groups(structural_role.name, b.name, room_names):
                if len(group) > 1:
                    merged_rooms.update((b.name, n) for n in group)
        for solved_role in _ROLE_ORDER:
            for group in role_groups_by_building[solved_role][b.name]:
                if len(group) > 1:
                    merged_rooms.update((b.name, n) for n in group)
                    merged_heights[solved_role] = max(merged_heights.get(solved_role, 0), group_need(solved_role, b.name, group))
    room_role_minimums: dict[RoomKey, dict[Role, int]] = {
        (b.name, r.name): {role: cap.minimum for role, cap in r.capacities.items() if cap and role in _ROLE_ORDER}
        for b in buildings
        for r in b.rooms
    }
    overflow_rooms = _large_rooms(room_role_counts, merged_rooms, merged_heights, room_role_minimums)

    # Column layout: one column per physical room — merging only ever
    # collapses *cells within one row*, never the column layout itself — except
    # that an overflow Room owns two adjacent columns.
    room_cols: dict[RoomKey, tuple[int, int]] = {}
    building_span: dict[str, tuple[int, int]] = {}
    col = 1
    for b in buildings:
        start = col
        for room in b.rooms:
            width = 2 if (b.name, room.name) in overflow_rooms else 1
            room_cols[(b.name, room.name)] = (col, col + width - 1)
            col += width
        building_span[b.name] = (start, col - 1)
    num_cols = max(col - 1, 1)

    col_group_of: dict[int, tuple[int, int]] = {}
    for start, end in [(0, 0), *building_span.values()]:
        for c in range(start, end + 1):
            col_group_of[c] = (start, end)

    def group_col_range(group: list[str], building_name: str) -> tuple[int, int]:
        return room_cols[(building_name, group[0])][0], room_cols[(building_name, group[-1])][1]

    workbook = xlsxwriter.Workbook(str(out_path))
    ws = workbook.add_worksheet(_SHEET_NAME)
    ws.freeze_panes(0, 1)

    # Column widths are set at the end, sized to the longest single-cell
    # text actually written to each column (comma-joined multi-name
    # aggregate cells are excluded — they're wrapped and shouldn't force
    # the whole column wide).
    col_width_chars: dict[int, int] = {}

    def track_width(col_idx: int, text: str) -> None:
        if text:
            col_width_chars[col_idx] = max(col_width_chars.get(col_idx, 0), len(text))

    fmt_cache: dict[tuple, object] = {}
    _BORDER_STYLE = {"none": 0, "thin": 1, "medium": 2}

    def cell_format(*, fill=None, bold=False, wrap=False, valign="bottom", top="thin", bottom="thin", left="thin", right="thin"):
        key = (fill, bold, wrap, valign, top, bottom, left, right)
        fmt = fmt_cache.get(key)
        if fmt is None:
            spec = {
                "font_name": "Arial",
                "bold": bold,
                "align": "center",
                "valign": valign,
                "text_wrap": wrap,
                "top": _BORDER_STYLE[top],
                "bottom": _BORDER_STYLE[bottom],
                "left": _BORDER_STYLE[left],
                "right": _BORDER_STYLE[right],
            }
            if fill:
                spec["bg_color"] = fill
            fmt = workbook.add_format(spec)
            fmt_cache[key] = fmt
        return fmt

    def borders(row_start: int, row_end: int, row: int, col_start: int, col_end: int) -> tuple[str, str, str, str]:
        top = "medium" if row == row_start else "thin"
        bottom = "medium" if row == row_end else "thin"
        gstart, _ = col_group_of.get(col_start, (col_start, col_start))
        _, gend = col_group_of.get(col_end, (col_end, col_end))
        left = "medium" if col_start == gstart else "thin"
        right = "medium" if col_end == gend else "thin"
        return top, bottom, left, right

    def write_cell(row: int, col_start: int, col_end: int, text: Optional[str], fmt, track: bool = True) -> None:
        """Write one row's cell, merging across `col_start..col_end` (a
        single row-scoped cell merge, like Excel's) when it spans more than
        one column. `text=None` writes a blank cell/range."""
        if text is None:
            if col_start == col_end:
                ws.write_blank(row, col_start, None, fmt)
            else:
                ws.merge_range(row, col_start, row, col_end, "", fmt)
            return
        if col_start == col_end:
            if track:
                track_width(col_start, text)
            ws.write(row, col_start, text, fmt)
        else:
            ws.merge_range(row, col_start, row, col_end, text, fmt)

    def write_building_row(row: int, building_name: str, text: str, fmt, track: bool = True) -> None:
        start, end = building_span[building_name]
        write_cell(row, start, end, text, fmt, track=track)

    # ---- Header rows: row 0 building names, row 1 room names (never
    # merged — cell merges are always scoped to one specific row below) ----
    corner_fmt = cell_format(bold=True, top="medium", bottom="medium", left="medium", right="medium")
    ws.merge_range(0, 0, 1, 0, " ", corner_fmt)
    header_fmt_merged = cell_format(bold=True, top="medium", bottom="thin", left="medium", right="medium")
    for b in buildings:
        write_building_row(0, b.name, b.name, header_fmt_merged)
    for b in buildings:
        for room in b.rooms:
            c_start, c_end = room_cols[(b.name, room.name)]
            _, _, left, right = borders(1, 1, 1, c_start, c_end)
            fmt = cell_format(bold=True, top="thin", bottom="medium", left=left, right=right)
            write_cell(1, c_start, c_end, room.name, fmt)
    row = 2

    # ---- Structural roles: Vedoucí budovy is building-wide; Pravá ruka and
    # Vedoucí místností are per room (each room can have its own deputy/lead,
    # with any of that row's own cell merges) ----
    structural_building: dict[tuple[StructuralRole, str], list[str]] = defaultdict(list)
    structural_room: dict[tuple[StructuralRole, str, str], list[str]] = defaultdict(list)
    for entry in manual.structural:
        name = slot_name(entry)
        if entry.role in _ROOM_SCOPED_STRUCTURAL_ROLES and entry.room:
            structural_room[(entry.role, entry.building, entry.room)].append(name)
        else:
            structural_building[(entry.role, entry.building)].append(name)

    label_color, data_color = _STRUCTURAL_COLOR
    track_width(0, StructuralRole.VedouciBudovy.value)
    ws.write(row, 0, StructuralRole.VedouciBudovy.value, cell_format(fill=label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium"))
    filled_fmt = cell_format(fill=data_color, wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
    empty_fmt = cell_format(fill=_EMPTY_SLOT_COLOR, wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
    ws.set_row(row, _WRAP_ROW_HEIGHT)
    for b in buildings:
        names = structural_building.get((StructuralRole.VedouciBudovy, b.name), [])
        write_building_row(row, b.name, ", ".join(names), filled_fmt if names else empty_fmt, track=False)
    row += 1

    # ---- Pravá ruka, Vedoucí místností: per room, each with its own merges ----
    for structural_role in _ROOM_SCOPED_STRUCTURAL_ROLES:
        track_width(0, structural_role.value)
        ws.write(row, 0, structural_role.value, cell_format(fill=label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium"))
        for b in buildings:
            for group in row_groups(structural_role.name, b.name, [r.name for r in b.rooms]):
                col_start, col_end = group_col_range(group, b.name)
                names = [n for room_name in group for n in structural_room.get((structural_role, b.name, room_name), [])]
                top, bottom, left, right = borders(row, row, row, col_start, col_end)
                if names:
                    text = ", ".join(names)
                    fmt = cell_format(fill=data_color, top=top, bottom=bottom, left=left, right=right)
                    write_cell(row, col_start, col_end, text, fmt)
                else:
                    fmt = cell_format(fill=_EMPTY_SLOT_COLOR, top=top, bottom=bottom, left=left, right=right)
                    write_cell(row, col_start, col_end, None, fmt)
        row += 1

    # ---- Solved roles: Opravovatel, Menic, Skenovac, Kreslic, Fotograf ----
    # Row-block height must fit both the configured minimum headcount *and*
    # whatever the solver actually placed in any single room — capacities are
    # typically unbounded above (minimum-only), so a room's actual count can
    # exceed its configured minimum, and undersizing the block would let the
    # overflow bleed into the next role's rows.
    #
    # Placements are precomputed per (role, building, group) at the top of
    # `write_roster`, *before* any cell is written, then each row of a block
    # is written exactly once — either with a placed helper's name or blank —
    # rather than blank-filling the whole block first and overwriting specific
    # cells after. A merged (multi-room) cell uses `merge_range`, which errors
    # if a range is merged twice, so it can't be blanked and then re-merged
    # with content.
    role_row_start: dict[Role, int] = {}
    role_row_end: dict[Role, int] = {}
    for solved_role in _ROLE_ORDER:
        groups_by_building = role_groups_by_building[solved_role]

        # An overflow Room stacks its Helpers over two columns instead, so it
        # only asks for half its need (rounded up) in rows; `max_min` is then
        # K, the height the first column fills to. A Room needing more than
        # twice the height of the others raises K rather than getting a third
        # column. A merged group (never an overflow Room) keeps its one name
        # per row and may stretch the band, and an overflow Room then fills
        # its first column down to that taller height.
        max_min = 1
        for b in buildings:
            for group in groups_by_building[b.name]:
                need = group_need(solved_role, b.name, group)
                if (b.name, group[0]) in overflow_rooms:
                    need = math.ceil(need / 2)
                max_min = max(max_min, need)

        role_row_start[solved_role] = row
        role_label_color, role_data_color = _ROLE_COLORS[solved_role]
        label_fmt = cell_format(fill=role_label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium")
        track_width(0, _ROLE_LABELS[solved_role])
        if max_min > 1:
            ws.merge_range(row, 0, row + max_min - 1, 0, _ROLE_LABELS[solved_role], label_fmt)
        else:
            ws.write(row, 0, _ROLE_LABELS[solved_role], label_fmt)
        for b in buildings:
            for group in groups_by_building[b.name]:
                col_start, col_end = group_col_range(group, b.name)
                names = group_placements.get((solved_role, b.name, tuple(group)), [])
                for r_offset in range(max_min):
                    data_row = row + r_offset
                    if (b.name, group[0]) in overflow_rooms:
                        # One cell per column: the first column takes the
                        # first K names, the second the rest.
                        slots = [(col_start, col_start, r_offset), (col_end, col_end, max_min + r_offset)]
                    else:
                        slots = [(col_start, col_end, r_offset)]
                    for slot_start, slot_end, name_idx in slots:
                        top, bottom, left, right = borders(row, row + max_min - 1, data_row, slot_start, slot_end)
                        if name_idx < len(names):
                            fmt = cell_format(fill=role_data_color, top=top, bottom=bottom, left=left, right=right)
                            write_cell(data_row, slot_start, slot_end, names[name_idx], fmt)
                        else:
                            fmt = cell_format(fill=_EMPTY_SLOT_COLOR, top=top, bottom=bottom, left=left, right=right)
                            write_cell(data_row, slot_start, slot_end, None, fmt)
        role_row_end[solved_role] = row + max_min - 1
        row += max_min

    # ---- Zaloha assignments, gathered per room from the solved result ----
    zaloha_by_building: dict[str, list[str]] = defaultdict(list)
    for a in result.assignments:
        if a.role is Role.Zaloha:
            zaloha_by_building[a.building].append(annotate_id(a.helper_id, a.helper_name))

    # ---- Overlay roles: Uvaděči účastníků, Focení předávání cen, Registrace ----
    helper_location: dict[int, str] = {}
    for a in result.assignments:
        helper_location.setdefault(a.helper_id, a.building)

    overlay_by_building: dict[tuple[OverlayRole, str], list[str]] = defaultdict(list)
    for entry in manual.overlay:
        building = helper_location.get(entry.helper_id)
        if building is None:
            continue
        overlay_by_building[(entry.role, building)].append(annotate_id(entry.helper_id))

    for overlay_role in _OVERLAY_ORDER:
        overlay_label_color, overlay_data_color = _OVERLAY_COLORS[overlay_role]
        track_width(0, overlay_role.value)
        ws.write(row, 0, overlay_role.value, cell_format(fill=overlay_label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium"))
        filled_fmt = cell_format(fill=overlay_data_color, wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
        empty_fmt = cell_format(fill=_EMPTY_SLOT_COLOR, wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
        ws.set_row(row, _WRAP_ROW_HEIGHT)
        for b in buildings:
            names = overlay_by_building.get((overlay_role, b.name), [])
            write_building_row(row, b.name, ", ".join(names), filled_fmt if names else empty_fmt, track=False)
        row += 1

    # ---- Zaloha (no fill, building-wide, matching the historical layout) ----
    track_width(0, _ROLE_LABELS[Role.Zaloha])
    ws.write(row, 0, _ROLE_LABELS[Role.Zaloha], cell_format(bold=True, top="medium", bottom="medium", left="medium", right="medium"))
    fmt = cell_format(wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
    ws.set_row(row, _WRAP_ROW_HEIGHT)
    for b in buildings:
        names = zaloha_by_building.get(b.name, [])
        write_building_row(row, b.name, ", ".join(names), fmt, track=False)
    row += 1

    # ---- Technicka podpora (no fill, building-wide) ----
    tech_lists: dict[str, list[str]] = defaultdict(list)
    for entry in manual.structural:
        if entry.role is StructuralRole.TechnickaPodpora:
            tech_lists[entry.building].append(slot_name(entry))
    track_width(0, StructuralRole.TechnickaPodpora.value)
    ws.write(row, 0, StructuralRole.TechnickaPodpora.value, cell_format(bold=True, top="medium", bottom="medium", left="medium", right="medium"))
    fmt = cell_format(wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
    ws.set_row(row, _WRAP_ROW_HEIGHT)
    for b in buildings:
        names = tech_lists.get(b.name, [])
        write_building_row(row, b.name, ", ".join(names), fmt, track=False)

    for c in range(0, num_cols + 1):
        chars = col_width_chars.get(c, 8)
        ws.set_column(c, c, min(max(chars + 2, 8), 40))

    people = counted_people(comp, result, manual)
    _write_tshirt_sheet(workbook, [b.name for b in buildings], people)
    _write_building_list_sheets(workbook, [b.name for b in buildings], people)

    workbook.close()
