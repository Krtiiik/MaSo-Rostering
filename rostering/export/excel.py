"""Formatted Excel roster export.

Main "Roster" sheet: one column per room (grouped under merged building
headers), one row-block per solved role (Opravovatel/Měnič/.../Záloha), plus
appended row-blocks for the manual structural roles (Vedoucí budovy, Pravá
ruka, Vedoucí místností, Technická podpora — see CLAUDE.md). A second sheet
lists the manual overlay roles (Registrace, Uvaděči / Předávání cen), since
those aren't tied to any one room.
"""
from __future__ import annotations

from pathlib import Path

import xlsxwriter

from rostering.domain import (
    Competition,
    ManualRoles,
    Role,
    SolveResult,
    StructuralRole,
)

_ROLE_COLORS: dict[Role, str] = {
    Role.Opravovatel: "#FFE599",
    Role.Menic: "#F5A555",
    Role.Skenovac: "#E06666",
    Role.Kreslic: "#64A2DA",
    Role.Fotograf: "#93C47D",
    Role.Zaloha: "#FFFFFF",
}

_ROLE_ORDER = [
    Role.Opravovatel,
    Role.Menic,
    Role.Skenovac,
    Role.Kreslic,
    Role.Fotograf,
    Role.Zaloha,
]

_STRUCTURAL_ORDER = [
    StructuralRole.VedouciBudovy,
    StructuralRole.PravaRuka,
    StructuralRole.VedouciMistnosti,
    StructuralRole.TechnickaPodpora,
]


def write_roster(
    comp: Competition,
    result: SolveResult,
    manual: ManualRoles,
    out_path: str | Path,
) -> None:
    helper_name_by_id = {h.id: h.name for h in comp.helpers}
    buildings = list(comp.buildings.values())

    room_col: dict[tuple[str, str], int] = {}
    col = 1
    for b in buildings:
        for room in b.rooms:
            room_col[(b.name, room.name)] = col
            col += 1
    num_cols = max(col - 1, 1)

    workbook = xlsxwriter.Workbook(str(out_path))
    ws = workbook.add_worksheet("Roster")

    building_fmt = workbook.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#AAAAAA"})
    role_label_fmt = workbook.add_format({"bold": True, "align": "left", "valign": "top", "bg_color": "#CCCCCC"})
    role_formats = {role: workbook.add_format({"bg_color": color}) for role, color in _ROLE_COLORS.items()}

    ws.set_column(0, 0, 22)
    ws.set_column(1, num_cols, 20)

    # Header rows: building name merged across its rooms, then room names.
    col = 1
    for b in buildings:
        if not b.rooms:
            continue
        start = col
        end = col + len(b.rooms) - 1
        if len(b.rooms) == 1:
            ws.write(0, start, b.name, building_fmt)
        else:
            ws.merge_range(0, start, 0, end, b.name, building_fmt)
        for i, room in enumerate(b.rooms):
            ws.write(1, start + i, room.name, building_fmt)
        col = end + 1

    # Row-blocks: one per solved role, sized to the largest minimum
    # headcount configured for that role across all rooms (at least 1).
    row = 2
    role_row_start: dict[Role, int] = {}
    for role in _ROLE_ORDER:
        max_min = 1
        for b in buildings:
            for r in b.rooms:
                cap = r.capacities.get(role)
                if cap:
                    max_min = max(max_min, cap.minimum)
        role_row_start[role] = row
        label = role.value
        if max_min > 1:
            ws.merge_range(row, 0, row + max_min - 1, 0, label, role_label_fmt)
        else:
            ws.write(row, 0, label, role_label_fmt)
        row += max_min

    placement_counters: dict[tuple[Role, str, str], int] = {}
    for a in result.assignments:
        col_idx = room_col.get((a.building, a.room))
        if col_idx is None:
            continue
        key = (a.role, a.building, a.room)
        placed = placement_counters.get(key, 0)
        target_row = role_row_start[a.role] + placed
        ws.write(target_row, col_idx, a.helper_name, role_formats[a.role])
        placement_counters[key] = placed + 1

    # Structural roles (manual): appended below the solved-role blocks.
    structural_row_start: dict[StructuralRole, int] = {}
    for structural_role in _STRUCTURAL_ORDER:
        structural_row_start[structural_role] = row
        ws.write(row, 0, structural_role.value, role_label_fmt)
        row += 1

    building_span: dict[str, tuple[int, int]] = {}
    col = 1
    for b in buildings:
        if not b.rooms:
            continue
        building_span[b.name] = (col, col + len(b.rooms) - 1)
        col += len(b.rooms)

    for entry in manual.structural:
        name = helper_name_by_id.get(entry.helper_id, f"#{entry.helper_id}")
        target_row = structural_row_start[entry.role]
        if entry.role is StructuralRole.VedouciMistnosti and entry.room:
            col_idx = room_col.get((entry.building, entry.room))
            if col_idx is not None:
                ws.write(target_row, col_idx, name)
            continue
        span = building_span.get(entry.building)
        if span:
            ws.write(target_row, span[0], name)

    _overlay_sheet(workbook, comp, manual)
    workbook.close()


def _overlay_sheet(workbook: xlsxwriter.Workbook, comp: Competition, manual: ManualRoles) -> None:
    helper_name_by_id = {h.id: h.name for h in comp.helpers}
    ws = workbook.add_worksheet("Registrace a predavani cen")
    ws.set_column(0, 1, 30)
    ws.write(0, 0, "Role")
    ws.write(0, 1, "Helper")
    row = 1
    for entry in manual.overlay:
        ws.write(row, 0, entry.role.value)
        ws.write(row, 1, helper_name_by_id.get(entry.helper_id, f"#{entry.helper_id}"))
        row += 1
