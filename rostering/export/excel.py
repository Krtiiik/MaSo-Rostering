"""Formatted Excel roster export.

Reproduces the layout and styling of the historical hand-built rosters
(`data/rosters/Rozdělení pomocníků Praha - *.xlsx`): a single sheet with one
column per room (grouped under merged building headers) and one row-block
per role. Row-block order top to bottom: the building-wide structural roles
(Vedoucí budovy, Pravá ruka), Vedoucí místností (per room), the 6 solved
roles (Opravovatel/Měnič/.../Fotograf; Záloha is deferred to the bottom to
match the historical layout), the overlay roles (Uvaděči účastníků, Focení
předávání cen, Registrace), then Záloha and Technická podpora. See
CLAUDE.md for the role glossary.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import xlsxwriter

from rostering.domain import (
    Competition,
    Helper,
    ManualRoles,
    OverlayRole,
    Role,
    SolveResult,
    StructuralRole,
)

_SHEET_NAME = "Pomocníci v místnostech"

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


def write_roster(
    comp: Competition,
    result: SolveResult,
    manual: ManualRoles,
    out_path: str | Path,
) -> None:
    helper_by_id = {h.id: h for h in comp.helpers}
    buildings = [b for b in comp.buildings.values() if b.rooms]

    room_col: dict[tuple[str, str], int] = {}
    building_span: dict[str, tuple[int, int]] = {}
    col = 1
    for b in buildings:
        start = col
        for room in b.rooms:
            room_col[(b.name, room.name)] = col
            col += 1
        building_span[b.name] = (start, col - 1)
    num_cols = max(col - 1, 1)

    col_group_of: dict[int, tuple[int, int]] = {}
    for start, end in [(0, 0), *building_span.values()]:
        for c in range(start, end + 1):
            col_group_of[c] = (start, end)

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

    def per_room_borders(row_start: int, row_end: int, row: int, col_idx: int) -> tuple[str, str, str, str]:
        top = "medium" if row == row_start else "thin"
        bottom = "medium" if row == row_end else "thin"
        gstart, gend = col_group_of.get(col_idx, (col_idx, col_idx))
        left = "medium" if col_idx == gstart else "thin"
        right = "medium" if col_idx == gend else "thin"
        return top, bottom, left, right

    def write_building_row(row: int, building_name: str, text: str, fmt, track: bool = True) -> None:
        start, end = building_span[building_name]
        if start == end:
            if track:
                track_width(start, text)
            ws.write(row, start, text, fmt)
        else:
            ws.merge_range(row, start, row, end, text, fmt)

    def annotate_id(helper_id: int, fallback_name: str = "") -> str:
        return _annotate(helper_by_id.get(helper_id), fallback_name)

    # ---- Header rows: row 0 building names, row 1 room names ----
    corner_fmt = cell_format(bold=True, top="medium", bottom="medium", left="medium", right="medium")
    ws.merge_range(0, 0, 1, 0, " ", corner_fmt)
    header_fmt_merged = cell_format(bold=True, top="medium", bottom="thin", left="medium", right="medium")
    for b in buildings:
        write_building_row(0, b.name, b.name, header_fmt_merged)
    for b in buildings:
        start, end = building_span[b.name]
        for i, room in enumerate(b.rooms):
            c = start + i
            _, _, left, right = per_room_borders(1, 1, 1, c)
            fmt = cell_format(bold=True, top="thin", bottom="medium", left=left, right=right)
            track_width(c, room.name)
            ws.write(1, c, room.name, fmt)
    row = 2

    # ---- Structural roles that apply building-wide: Vedoucí budovy, Pravá ruka ----
    structural_building: dict[tuple[StructuralRole, str], list[str]] = defaultdict(list)
    structural_room: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in manual.structural:
        name = annotate_id(entry.helper_id, entry.helper_name or "")
        if entry.role is StructuralRole.VedouciMistnosti and entry.room:
            structural_room[(entry.building, entry.room)].append(name)
        else:
            structural_building[(entry.role, entry.building)].append(name)

    label_color, data_color = _STRUCTURAL_COLOR
    for structural_role in (StructuralRole.VedouciBudovy, StructuralRole.PravaRuka):
        track_width(0, structural_role.value)
        ws.write(row, 0, structural_role.value, cell_format(fill=label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium"))
        filled_fmt = cell_format(fill=data_color, wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
        empty_fmt = cell_format(fill=_EMPTY_SLOT_COLOR, wrap=True, valign="center", top="medium", bottom="medium", left="medium", right="medium")
        ws.set_row(row, _WRAP_ROW_HEIGHT)
        for b in buildings:
            names = structural_building.get((structural_role, b.name), [])
            write_building_row(row, b.name, ", ".join(names), filled_fmt if names else empty_fmt, track=False)
        row += 1

    # ---- Vedoucí místností: per room ----
    track_width(0, StructuralRole.VedouciMistnosti.value)
    ws.write(row, 0, StructuralRole.VedouciMistnosti.value, cell_format(fill=label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium"))
    for b in buildings:
        start, end = building_span[b.name]
        for i, room in enumerate(b.rooms):
            c = start + i
            names = structural_room.get((b.name, room.name), [])
            _, _, left, right = per_room_borders(row, row, row, c)
            if names:
                text = ", ".join(names)
                fmt = cell_format(fill=data_color, top="medium", bottom="medium", left=left, right=right)
                track_width(c, text)
                ws.write(row, c, text, fmt)
            else:
                ws.write_blank(row, c, None, cell_format(fill=_EMPTY_SLOT_COLOR, top="medium", bottom="medium", left=left, right=right))
    row += 1

    # ---- Solved roles: Opravovatel, Menic, Skenovac, Kreslic, Fotograf ----
    # Row-block height must fit both the configured minimum headcount *and*
    # whatever the solver actually placed in any single room — capacities are
    # typically unbounded above (minimum-only), so a room's actual count can
    # exceed its configured minimum, and undersizing the block would let the
    # overflow bleed into the next role's rows.
    assignment_counts: dict[tuple[Role, str, str], int] = defaultdict(int)
    for a in result.assignments:
        assignment_counts[(a.role, a.building, a.room)] += 1

    role_row_start: dict[Role, int] = {}
    role_row_end: dict[Role, int] = {}
    for solved_role in _ROLE_ORDER:
        max_min = 1
        for b in buildings:
            for r in b.rooms:
                cap = r.capacities.get(solved_role)
                if cap:
                    max_min = max(max_min, cap.minimum)
                max_min = max(max_min, assignment_counts.get((solved_role, b.name, r.name), 0))
        role_row_start[solved_role] = row
        role_label_color, role_data_color = _ROLE_COLORS[solved_role]
        label_fmt = cell_format(fill=role_label_color, bold=True, top="medium", bottom="medium", left="medium", right="medium")
        track_width(0, _ROLE_LABELS[solved_role])
        if max_min > 1:
            ws.merge_range(row, 0, row + max_min - 1, 0, _ROLE_LABELS[solved_role], label_fmt)
        else:
            ws.write(row, 0, _ROLE_LABELS[solved_role], label_fmt)
        for r_offset in range(max_min):
            data_row = row + r_offset
            for b in buildings:
                start, end = building_span[b.name]
                for i in range(len(b.rooms)):
                    c = start + i
                    top, bottom, left, right = per_room_borders(row, row + max_min - 1, data_row, c)
                    ws.write_blank(data_row, c, None, cell_format(fill=_EMPTY_SLOT_COLOR, top=top, bottom=bottom, left=left, right=right))
        role_row_end[solved_role] = row + max_min - 1
        row += max_min

    placement_counters: dict[tuple[Role, str, str], int] = {}
    for a in result.assignments:
        if a.role not in role_row_start:
            continue
        col_idx = room_col.get((a.building, a.room))
        if col_idx is None:
            continue
        key = (a.role, a.building, a.room)
        placed = placement_counters.get(key, 0)
        target_row = role_row_start[a.role] + placed
        _, role_data_color = _ROLE_COLORS[a.role]
        top, bottom, left, right = per_room_borders(role_row_start[a.role], role_row_end[a.role], target_row, col_idx)
        text = annotate_id(a.helper_id, a.helper_name)
        track_width(col_idx, text)
        ws.write(
            target_row,
            col_idx,
            text,
            cell_format(fill=role_data_color, top=top, bottom=bottom, left=left, right=right),
        )
        placement_counters[key] = placed + 1

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
            tech_lists[entry.building].append(annotate_id(entry.helper_id, entry.helper_name or ""))
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

    workbook.close()
