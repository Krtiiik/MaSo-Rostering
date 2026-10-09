"""The roster grid as HTML, from a :class:`~rostering.webapp.ui.grid.data.GridView`.

Every piece of text is escaped here. The markup carries ``data-*`` attributes
that ``roster_grid.js`` reads to drive drag-and-drop, the friend hover, lock
toggles, the manual-role name fields and cell merging; it never decides anything
the view model has not already decided.

Chips: a Helper's chip (``data-kind="helper"``) is draggable onto a solver Role
cell (a move) or onto an Additional role cell of their own Room/Building (a
duplicate, drawn dotted); an Organizer's chip (``data-kind="organizer"``) only
onto a leadership slot. Cells say which kind they take in ``data-drop``.
"""
from __future__ import annotations

import json
import re
from html import escape
from typing import Iterable, Optional

from rostering.webapp.ui.grid.data import (
    PREFERENCE_LABELS,
    GridRow,
    GridView,
    building_groups,
    group_adjacent,
)
from rostering.domain import Preference

# Preference level (5 Ano .. 1 Ne) -> its Czech wording, for the role-fit tooltip.
ROLE_FIT_LABELS = {Preference[name].value: label for name, label in PREFERENCE_LABELS.items()}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# How much of a Tag's colour goes into its stripe; the rest is the chip's own
# background, so the chip's normal text colour stays readable.
_TINT_PERCENT = 55
_CHIP_BACKGROUND = "#eef1f5"

# Material Symbols "link_2" (Rounded), inlined.
LINK_ICON = (
    '<svg class="link-2-icon" viewBox="0 0 960 960" width="1em" height="1em" aria-hidden="true" '
    'fill="currentColor"><path transform="translate(0 960) scale(1 -1)" d="M318 120Q236 120 178 178Q120 236 120 '
    "318Q120 358 135 394Q150 430 178 458L283 563Q295 575 311.5 575Q328 575 340 563Q352 551 352 535Q352 519 340 "
    "507L234 401Q217 384 208.5 362.5Q200 341 200 318Q200 269 234.5 234.5Q269 200 318 200Q341 200 363 208.5Q385 217 "
    "402 234L507 340Q519 351 535 351Q551 351 563 339Q575 327 575 311Q575 295 563 283L458 178Q430 150 394 135Q358 "
    "120 318 120ZM368 368Q356 380 356 396.5Q356 413 368 425L535 592Q547 604 563.5 604Q580 604 592 592Q604 580 604 "
    "563.5Q604 547 592 535L425 368Q413 356 396.5 356Q380 356 368 368ZM620 397Q608 409 608 425Q608 441 620 453L726 "
    "558Q743 575 751 596Q759 617 759 640Q759 690 725 725Q691 760 641 760Q618 760 596.5 751.5Q575 743 558 726L453 "
    "620Q441 608 425 608Q409 608 397 620Q385 632 385 648.5Q385 665 397 677L502 782Q530 810 566 825Q602 840 642 "
    "840Q724 840 781.5 782Q839 724 839 641Q839 602 824.5 566Q810 530 782 502L677 397Q665 385 648.5 385Q632 385 620 "
    '397Z"/></svg>'
)


def _attr(value: object) -> str:
    return escape(str(value), quote=True)


def _attrs(**values: object) -> str:
    """``data_x=1`` -> ``data-x="1"``; ``None`` / ``False`` values are left out."""
    parts = []
    for name, value in values.items():
        if value is None or value is False:
            continue
        name = name.rstrip("_").replace("_", "-")
        parts.append(name if value is True else f'{name}="{_attr(value)}"')
    return " ".join(parts)


def _title(lines: Iterable[str]) -> Optional[str]:
    text = "\n".join(line for line in lines if line)
    return text or None


def tag_stripe_style(tags: Optional[dict]) -> Optional[str]:
    """The Tags overlay's colouring: as many equal vertical stripes as the person
    has direct Tags, one per Tag in its colour; one Tag is a flat tint; no style
    for a person without direct Tags."""
    direct = (tags or {}).get("direct") or []
    if not direct:
        return None
    tints = [
        f"color-mix(in srgb, {p['colour'] if _HEX.match(p['colour'] or '') else '#888888'} {_TINT_PERCENT}%, "
        f"{_CHIP_BACKGROUND})"
        for p in direct
    ]
    if len(tints) == 1:
        return f"background: {tints[0]}"
    step = 100 / len(tints)
    stops = ", ".join(f"{t} {i * step:.3f}% {(i + 1) * step:.3f}%" for i, t in enumerate(tints))
    return f"background: linear-gradient(to right, {stops})"


def tag_title(tags: Optional[dict]) -> Optional[str]:
    """The person's Tag names for a tooltip: direct ones, then inherited ones."""
    if not tags:
        return None
    names = [p["name"] for p in tags.get("direct", [])] + [f"{p['name']} (zděděný)" for p in tags.get("implied", [])]
    return f"Štítky: {', '.join(names)}" if names else None


# ---------------------------------------------------------------------- chips
def helper_chip(view: GridView, helper_id: int) -> str:
    h = view.helpers[helper_id]
    placed = view.assignments.get(helper_id)
    locked = bool(placed and placed.get("locked"))
    unsatisfied = view.friends_on and view.unsatisfied(helper_id)
    broken = view.broken_helpers.get(helper_id, [])
    role_fit = view.role_fit(helper_id)
    building_fit = view.building_fit(helper_id)
    stripes = tag_stripe_style(h["tags"]) if view.tags_on else None
    classes = ["helper-chip"]
    classes += ["unsatisfied"] if unsatisfied else []
    classes += ["broken"] if broken else []
    classes += ["locked"] if locked else []
    classes += ["chip-dimmed"] if helper_id in view.dimmed_helper_ids else []
    classes += ["tag-striped"] if stripes else []
    if role_fit is not None:
        classes.append(f"role-fit-{role_fit}")
    if building_fit is not None:
        classes.append("building-fit-ok" if building_fit else "building-fit-bad")
    title = _title(
        [
            *broken,
            "Má nesplněné přání být s kamarádem" if unsatisfied else "",
            "" if role_fit is None else f"Přání pro tuto roli: {ROLE_FIT_LABELS[role_fit]}",
            "" if building_fit is None else ("Spokojen/a s budovou" if building_fit else "Nespokojen/a s budovou"),
            (tag_title(h["tags"]) or "") if view.tags_on else "",
        ]
    )
    friends = ",".join(f"{f}:{int(ok)}" for f, ok in view.friend_status.get(helper_id, {}).items())
    organizer_friends = ",".join(f"{o}:{int(ok)}" for o, ok in view.organizer_status.get(helper_id, {}).items())
    attrs = _attrs(
        class_=" ".join(classes),
        draggable="true",
        data_kind="helper",
        data_hid=helper_id,
        data_name=h["name"],
        data_building=placed["building"] if placed else None,
        data_room=placed["room"] if placed else None,
        data_locked="1" if locked else None,
        data_friends=friends or None,
        data_organizer_friends=organizer_friends or None,
        data_requesters=",".join(map(str, view.requesters.get(helper_id, []))) or None,
        style=stripes,
        title=title,
    )
    inner = []
    if locked:
        inner.append('<span class="helper-chip-lock" title="Uzamčeno: celé sestavení rozdělení toto přiřazení zachová">🔒 </span>')
    if h["answers_changed"]:
        inner.append(
            f'<span class="helper-chip-answers-changed" title="'
            f'{_attr("Odpovědi se změnily od zařazení: " + ", ".join(h["answers_changed"]))}">✎ </span>'
        )
    if h["forced_groups"]:
        inner.append(
            f'<span class="helper-chip-forced" title="'
            f'{_attr("Vynucené skupinky kamarádů: " + "; ".join(h["forced_groups"]))}">🔗 </span>'
        )
    inner.append(escape(h["name"]))
    if h["can_bring_notebook"]:
        inner.append('<span title="Může přinést notebook"> 💻</span>')
    if h["can_bring_camera"]:
        inner.append('<span title="Může přinést fotoaparát"> 📷</span>')
    return f"<div {attrs}>{''.join(inner)}</div>"


def organizer_chip(view: GridView, organizer: dict, source: Optional[dict], removable: bool) -> str:
    """A tracked Organizer's chip, draggable onto the leadership slots only.
    ``source`` is the slot cell it sits in (None in the Nezařazení list)."""
    stripes = tag_stripe_style(organizer.get("tags")) if view.tags_on else None
    broken = organizer.get("broken") or []
    classes = ["manual-chip", "organizer-chip"]
    classes += ["tag-striped"] if stripes else []
    classes += ["chip-dimmed"] if organizer.get("dimmed") else []
    classes += ["broken"] if broken else []
    attrs = _attrs(
        class_=" ".join(classes),
        draggable="true",
        data_kind="organizer",
        data_oid=organizer["id"],
        data_source=json.dumps(source) if source else None,
        data_requesters=",".join(map(str, view.organizer_requesters.get(organizer["id"], []))) or None,
        style=stripes,
        title=_title([*broken, (tag_title(organizer.get("tags")) or "") if view.tags_on else ""]),
    )
    remove = (
        f'<button type="button" class="manual-chip-remove" {_attrs(data_remove=organizer["name"])} '
        f'aria-label="{_attr("Odebrat " + organizer["name"])}">×</button>'
        if removable
        else ""
    )
    return f"<span {attrs}>{escape(organizer['name'])}{remove}</span>"


def manual_chip(view: GridView, entry: dict, duplicate_cell: bool) -> str:
    """A name in a manual-role cell that is not a tracked Organizer: a registered
    Helper (dotted where it duplicates their placement) or typed text (dashed),
    or a legacy leadership-slot entry with its "not tracked" badge."""
    classes = ["manual-chip"]
    if entry.get("legacy") or entry.get("helper_id") is None:
        classes.append("manual-chip-new")
    elif duplicate_cell:
        classes.append("manual-chip-duplicate")
    badge = (
        '<span class="manual-chip-badge" title="Zatím to není evidovaný organizátor — odeberte ho a vyberte nebo '
        'přidejte organizátora, který ho nahradí">neevidován</span>'
        if entry.get("legacy")
        else ""
    )
    return (
        f'<span class="{" ".join(classes)}">{escape(entry["name"])}{badge}'
        f'<button type="button" class="manual-chip-remove" {_attrs(data_remove=entry["name"])} '
        f'aria-label="{_attr("Odebrat " + entry["name"])}">×</button></span>'
    )


# ---------------------------------------------------------------------- cells
def _merge_controls(row_key: str, building: str, rooms: list[str], next_group: Optional[tuple[str, list[str]]]) -> str:
    parts = []
    if next_group is not None and next_group[0] == building:
        pairs = json.dumps([[rooms[-1], next_group[1][0]]])
        parts.append(
            f'<div class="cell-merge-handle" title="Kliknutím sloučíte s další buňkou" '
            f"{_attrs(data_merge=pairs, data_key=row_key, data_building=building, data_merged='1')}></div>"
        )
    if len(rooms) > 1:
        pairs = json.dumps([[a, b] for a, b in zip(rooms, rooms[1:])])
        parts.append(
            f'<button type="button" class="cell-unmerge-handle" title="Kliknutím sloučenou buňku opět rozdělíte" '
            f"{_attrs(data_merge=pairs, data_key=row_key, data_building=building, data_merged='0')}>⊟</button>"
        )
    return "".join(parts)


def _cell(classes: list[str], colspan: int, attrs: str, title: Optional[str], content: str, controls: str) -> str:
    title_attr = f' title="{_attr(title)}"' if title else ""
    span = f' colspan="{colspan}"' if colspan > 1 else ""
    return (
        f'<td class="{" ".join(classes)}"{span} {attrs}{title_attr}>'
        f'<div class="grid-cell-inner">{content}</div>{controls}</td>'
    )


def _role_row(view: GridView, row: GridRow, groups: list[tuple[str, list[str]]]) -> str:
    cells = []
    by_cell: dict[tuple, list[int]] = {}
    for helper_id, a in view.assignments.items():
        by_cell.setdefault((a["building"], a["room"], a["role"]), []).append(helper_id)
    for i, (building, rooms) in enumerate(groups):
        lines: list[str] = []
        ids: list[int] = []
        for room in rooms:
            for line in view.broken_cells.get((building, room, row.key), []):
                if line not in lines:
                    lines.append(line)
            ids += by_cell.get((building, room, row.key), [])
        ids.sort(key=lambda hid: view.helpers[hid]["name"].lower())
        cells.append(
            _cell(
                ["grid-cell"] + (["broken"] if lines else []),
                len(rooms),
                _attrs(data_drop="role", data_building=building, data_room=rooms[0], data_role=row.key),
                _title(lines),
                "".join(helper_chip(view, hid) for hid in ids),
                _merge_controls(row.key, building, rooms, groups[i + 1] if i + 1 < len(groups) else None),
            )
        )
    return "".join(cells)


def _manual_cell(
    view: GridView,
    row: GridRow,
    building: str,
    rooms: Optional[list[str]],
    colspan: int,
    controls: str,
) -> str:
    """One manual-role cell: its names as chips (removable by their ×), filled
    only by the drops its row allows; nothing can be typed into it."""
    if rooms is None:
        entries = [e for e in view.entries if e["key"] == row.key and e["building"] == building and e["room"] is None]
    else:
        # Entries stay keyed to their exact Room even when shown merged.
        entries = [e for e in view.entries if e["key"] == row.key and e["building"] == building and e["room"] in rooms]
    organizers = {o["id"]: o for o in view.organizers}
    chips = []
    for e in entries:
        if e.get("organizer_id") is not None:
            organizer = organizers.get(e["organizer_id"]) or {
                "id": e["organizer_id"],
                "name": e["name"],
                "tags": e.get("tags"),
                "dimmed": e.get("dimmed"),
                "broken": e.get("broken"),
            }
            source = {"key": row.key, "building": e["building"] or building, "room": e["room"]}
            chips.append(organizer_chip(view, organizer, source, removable=True))
        else:
            chips.append(manual_chip(view, e, duplicate_cell=row.duplicate_drop))
    drop = "org" if row.organizer else ("dup" if row.duplicate_drop else None)
    attrs = _attrs(
        data_drop=drop,
        data_key=row.key,
        data_building=building,
        data_room=rooms[0] if rooms else None,
        data_rooms=json.dumps(rooms) if rooms is not None else None,
        data_names=json.dumps([e["name"] for e in entries]),
    )
    return _cell(["grid-cell", "manual-cell"], colspan, attrs, None, "".join(chips), controls)


def _manual_row(view: GridView, row: GridRow, groups: list[tuple[str, list[str]]]) -> str:
    if row.scope == "room":
        cells = []
        for i, (building, rooms) in enumerate(groups):
            controls = _merge_controls(row.key, building, rooms, groups[i + 1] if i + 1 < len(groups) else None)
            cells.append(_manual_cell(view, row, building, rooms, len(rooms), controls))
        return "".join(cells)
    return "".join(
        _manual_cell(view, row, building, None, len(rooms), "") for building, rooms in building_groups(view.rooms)
    )


# ---------------------------------------------------------------------- the grid
def render(view: GridView, merges: dict) -> str:
    """The whole grid: the Nezařazení pool, then the table."""
    parts = []
    unassigned = sorted((hid for hid in view.helpers if hid not in view.assignments), key=lambda i: view.helpers[i]["name"].lower())
    waiting = sorted((o for o in view.organizers if not o["placed"]), key=lambda o: o["name"].lower())
    if unassigned or waiting:
        parts.append('<div class="unassigned-pool" data-drop="pool"><strong>Nezařazení:</strong>')
        if unassigned:
            parts.append('<div class="unassigned-group"><span class="unassigned-group-label">Pomocníci</span>')
            parts += [helper_chip(view, hid) for hid in unassigned]
            parts.append("</div>")
        if waiting:
            parts.append('<div class="unassigned-group"><span class="unassigned-group-label">Organizátoři</span>')
            parts += [organizer_chip(view, o, None, removable=False) for o in waiting]
            parts.append("</div>")
        parts.append("</div>")

    # Only the table scrolls sideways; the Nezařazení pool above it stays put.
    parts.append('<div class="table-scroll"><table class="roster-grid"><thead><tr><th></th>')
    for building, rooms in building_groups(view.rooms):
        span = f' colspan="{len(rooms)}"' if len(rooms) > 1 else ""
        parts.append(f'<th class="building-header"{span}>{escape(building)}</th>')
    parts.append("</tr><tr><th></th>")
    for r in view.rooms:
        lines = view.broken_rooms.get((r["building"], r["room"]), [])
        title = f' title="{_attr(chr(10).join(lines))}"' if lines else ""
        parts.append(f'<th class="room-header{" broken" if lines else ""}"{title}>{escape(r["room"])}</th>')
    parts.append("</tr></thead><tbody>")
    previous: Optional[GridRow] = None
    for row in view.rows:
        # The Organizer rows and the Helper rows are set apart by a heavy line
        # wherever one kind follows the other.
        side = ' class="row-side-start"' if previous is not None and previous.organizer != row.organizer else ""
        note = ""
        if row.kind == "manual":
            note = f'<span class="row-label-note">{LINK_ICON} {"Organizátorská role" if row.organizer else "Manuální role"}</span>'
        parts.append(f'<tr{side}><th class="row-label">{escape(row.label)}{note}</th>')
        groups = row_groups_for(view, merges, row.key)
        parts.append(_role_row(view, row, groups) if row.kind == "role" else _manual_row(view, row, groups))
        parts.append("</tr>")
        previous = row
    parts.append("</tbody></table></div>")
    return "".join(parts)


def row_groups_for(view: GridView, merges: dict, row_key: str) -> list[tuple[str, list[str]]]:
    row_merges = merges.get(row_key, {})
    return [
        (building, group)
        for building, rooms in building_groups(view.rooms)
        for group in group_adjacent(rooms, row_merges.get(building, []))
    ]


CSS = """
.roster-grid-root { font-size: 13px; }
.roster-grid-root .table-scroll { overflow-x: auto; }
.roster-grid-root .unassigned-pool {
  margin-bottom: .75rem; padding: .5rem; border: 1px dashed #bbb; border-radius: 6px; background: #fff;
}
.roster-grid-root .unassigned-group { display: flex; flex-wrap: wrap; align-items: center; margin-top: 4px; }
.roster-grid-root .unassigned-group-label { margin-right: 6px; font-size: .85em; opacity: .7; }
.roster-grid-root .roster-grid { border-collapse: collapse; width: 100%; background: #fff; }
.roster-grid-root .roster-grid th, .roster-grid-root .roster-grid td {
  border: 1px solid #ddd; padding: 4px 6px; text-align: left; vertical-align: top; white-space: nowrap;
}
.roster-grid-root .building-header { text-align: center; background: #f3f3f3; }
.roster-grid-root .room-header { background: #f9f9f9; }
.roster-grid-root .row-label { background: #f9f9f9; white-space: nowrap; position: sticky; left: 0; z-index: 2; }
.roster-grid-root .grid-cell { position: relative; min-width: 110px; height: 30px; }
.roster-grid-root .grid-cell.drop-over { background: #e6f4ff !important; }
.roster-grid-root .grid-cell.drop-disabled { opacity: .45; }
.roster-grid-root .grid-cell-inner { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
.roster-grid-root .cell-merge-handle {
  position: absolute; top: 0; right: -4px; bottom: 0; width: 8px; cursor: pointer; z-index: 5;
  background: #d5dae1; opacity: .35;
}
.roster-grid-root .cell-merge-handle:hover { opacity: 1; background: #1c83e1; }
.roster-grid-root .cell-unmerge-handle {
  position: absolute; top: 2px; right: 2px; width: 16px; height: 16px; line-height: 14px; text-align: center;
  font-size: 11px; padding: 0; cursor: pointer; border-radius: 3px; background: #eef1f5; border: 1px solid #d5dae1;
  z-index: 5; opacity: .6;
}
.roster-grid-root .cell-unmerge-handle:hover { opacity: 1; background: #e6f4ff; }
.roster-grid-root .helper-chip {
  display: inline-block; margin: 1px; padding: 2px 6px; border-radius: 10px; background: #eef1f5;
  border: 1px solid #d5dae1; cursor: grab; user-select: none; white-space: nowrap;
}
.roster-grid-root .helper-chip.locked { border: 2px solid #262730; padding: 1px 5px; }
.roster-grid-root .helper-chip-answers-changed { color: #e0a800; font-weight: 700; }
.roster-grid-root .helper-chip-forced { cursor: help; }
.roster-grid-root .helper-chip.chip-dimmed, .roster-grid-root .manual-chip.chip-dimmed { opacity: .3; }
.roster-grid-root .helper-chip.chip-dimmed:hover, .roster-grid-root .manual-chip.chip-dimmed:hover { opacity: 1; }
.roster-grid-root .helper-chip.dragging, .roster-grid-root .organizer-chip.dragging { opacity: .5; }
.roster-grid-root .helper-chip.unsatisfied { border-color: #e0a800; background: #fff6e0; }
.roster-grid-root .helper-chip.friend-highlight-satisfied, .roster-grid-root .organizer-chip.friend-highlight-satisfied {
  outline: 2px solid #21c354; outline-offset: 1px;
}
.roster-grid-root .helper-chip.friend-highlight-unsatisfied, .roster-grid-root .organizer-chip.friend-highlight-unsatisfied {
  outline: 2px solid #dc3545; outline-offset: 1px;
}
.roster-grid-root .helper-chip.friend-highlight-requester, .roster-grid-root .organizer-chip.friend-highlight-requester {
  outline: 2px solid #9c27b0; outline-offset: 1px;
}
.roster-grid-root .helper-chip[class*="role-fit-"] {
  border-left-width: 4px; padding-left: 3px;
}
.roster-grid-root .helper-chip.building-fit-ok, .roster-grid-root .helper-chip.building-fit-bad {
  border-top-width: 3px; padding-top: 0;
}
.roster-grid-root .helper-chip.role-fit-5 { border-left-color: #21c354; }
.roster-grid-root .helper-chip.role-fit-4 { border-left-color: #9acd32; }
.roster-grid-root .helper-chip.role-fit-3 { border-left-color: #f5d800; }
.roster-grid-root .helper-chip.role-fit-2 { border-left-color: #fd7e14; }
.roster-grid-root .helper-chip.role-fit-1 { border-left-color: #dc3545; }
.roster-grid-root .helper-chip.building-fit-ok { border-top-color: #21c354; }
.roster-grid-root .helper-chip.building-fit-bad { border-top-color: #dc3545; }
.roster-grid-root .helper-chip.tag-striped, .roster-grid-root .manual-chip.tag-striped { background-clip: padding-box; }
.roster-grid-root .row-label-note {
  display: flex; align-items: center; gap: 3px; font-size: .8em; font-style: italic; font-weight: 400; opacity: .7;
}
.roster-grid-root .manual-chip {
  display: inline-flex; align-items: center; gap: 4px; margin: 1px; padding: 2px 6px; border-radius: 10px;
  background: #eef1f5; border: 1px solid #d5dae1; white-space: nowrap;
}
.roster-grid-root .organizer-chip { cursor: grab; user-select: none; }
.roster-grid-root .manual-chip-new { border-style: dashed; }
.roster-grid-root .manual-chip-duplicate { border-style: dotted; border-width: 2px; }
.roster-grid-root .manual-chip-badge {
  font-size: .7em; padding: 0 4px; border-radius: 6px; border: 1px solid #d5dae1; opacity: .75;
}
.roster-grid-root .manual-chip-remove {
  border: none; background: none; cursor: pointer; padding: 0; line-height: 1; color: inherit; opacity: .6;
}
.roster-grid-root .manual-chip-remove:hover { opacity: 1; }
.roster-grid-root .grid-cell.broken {
  background: color-mix(in srgb, #dc3545 9%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #dc3545 45%, transparent);
}
.roster-grid-root .roster-grid th.broken {
  background: color-mix(in srgb, #dc3545 14%, #f3f3f3);
  box-shadow: inset 0 -2px 0 color-mix(in srgb, #dc3545 55%, transparent);
}
.roster-grid-root .helper-chip.broken, .roster-grid-root .manual-chip.broken {
  box-shadow: 0 0 0 2px color-mix(in srgb, #dc3545 45%, transparent);
}
.roster-grid-root .roster-grid tr.row-side-start > th, .roster-grid-root .roster-grid tr.row-side-start > td {
  border-top: 3px solid rgba(38, 39, 48, .7);
}
.helper-card {
  position: fixed; z-index: 3000; width: 260px; padding: 8px 10px; border-radius: 6px; border: 1px solid #ddd;
  background: #fff; box-shadow: 0 4px 16px rgba(0, 0, 0, .18); font-size: 13px;
}
.helper-card .helper-card-label { font-size: .8em; font-weight: 600; opacity: .7; text-transform: uppercase; }
.helper-card .stars { color: #d9a400; letter-spacing: 1px; }
.helper-card .friend-shared { color: #21c354; }
.helper-card .friend-different { color: #dc3545; }
.helper-card .friend-requested-by { color: #8b5cf6; }
"""
