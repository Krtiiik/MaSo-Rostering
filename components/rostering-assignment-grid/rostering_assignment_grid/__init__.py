"""Custom Streamlit component (CCv2): the drag-and-drop role assignment grid
used by the rostering app's Roster tab.

Streamlit has no native drag-and-drop, so this wraps a small packaged
React + dnd-kit frontend (``frontend/``) that renders the {building, room} x
role grid and reports drop events back to Python via the ``drop`` trigger.
Generated from Streamlit's official CCv2 `component-template`
(https://github.com/streamlit/component-template, cookiecutter/v2, React +
TypeScript) and then customized: see ``frontend/src/AssignmentGrid.tsx``
(ported from the rostering app's old React frontend's ``GridPage.tsx``) and
``frontend/src/Cell.tsx``/``HelperChip.tsx`` (copied close to verbatim, since
they were already presentation-only with no API calls).

Packaged as its own distribution (not nested inside the ``rostering``
package) because Streamlit's CCv2 manifest scanner discovers packaged
components by scanning *installed distributions* for a
``[tool.streamlit.component]`` table in their own ``pyproject.toml`` — see
``rostering``'s README for the two-package editable-install setup this
requires. The import package name matches the distribution name
(hyphens -> underscores) deliberately: the scanner's editable-install
fallback path resolves a component's manifest via ``importlib.util.find_spec``
on that normalized name, so a mismatched ``import_name`` (as an earlier,
reverted version of this component used) fails discovery silently.
"""
from __future__ import annotations

from typing import Any, Optional

import streamlit as st

_component = st.components.v2.component(
    "rostering-assignment-grid.rostering_assignment_grid",
    js="index-*.js",
    css="index-*.css",
    html='<div class="react-root"></div>',
)


def _noop() -> None:
    pass


def assignment_grid(
    *,
    rooms: list[dict[str, str]],
    rows: list[dict[str, Any]],
    helpers: list[dict[str, Any]],
    assignments: list[dict[str, Any]],  # a truthy ``locked`` marks a Locked Assignment
    manual_entries: list[dict[str, Any]],
    cell_merges: dict[str, dict[str, list[list[str]]]],
    helper_names: list[str],
    broken_marks: Optional[dict[str, list[dict[str, Any]]]] = None,
    show_tags: bool = False,
    dimmed_helper_ids: Optional[list[int]] = None,
    key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Render the grid, including any non-droppable manual-role rows.

    The column layout (``rooms``, header rows) is always one column per
    physical room — merging never changes it. Instead, any *one row*
    (``rows`` entry — a solved role or a room-scoped manual role) can merge
    two or more of its own adjacent cells into one wider cell, like merging
    cells within a single row in Excel: click the edge between two of that
    row's cells to merge them, click an already-merged cell to split it
    back apart. Every other row for the same rooms is unaffected.
    ``cell_merges`` is ``{row_key: {building: [[room_a, room_b], ...]}}``
    (see CLAUDE.md "Out-of-solver roles" and
    ``rostering.domain.group_adjacent_rooms``) — merging is purely
    presentational, every other argument here still refers to exact,
    unmerged room names.

    ``rows`` describes every row top to bottom: ``{"kind": "role", "key",
    "label"}`` for a solver-role row (drag-and-drop, matched against
    ``assignments``), or ``{"kind": "manual", "key", "label", "scope",
    "allowDuplicateDrop"}`` for a manual-role row (``scope`` one of
    ``"building"``/``"room"``/``"global"``, matched against
    ``manual_entries`` by ``key``/``building``/``room``). When
    ``allowDuplicateDrop`` is true (meaningful for ``scope: "room"`` or
    ``scope: "building"``), the cell also accepts dropping a helper's
    existing chip onto the cell for the room/building they're already
    solved into, which adds them to that manual row without removing
    their solved-role assignment (reported via the same ``manual_set``
    trigger as a typed/picked name would be).

    Each ``helpers`` entry's ``friends`` (raw, resolved-to-id friend
    requests straight from ingestion) is what drives the grid's own
    orange/green/red/purple friend-request highlighting client-side —
    deliberately *not* the solver's ``unsatisfied_friend_pairs``/
    ``satisfied_friend_pairs`` diagnostics, since those are collapsed by
    the friend-scoring config's ``mode``/``symmetric`` settings and can
    silently merge or drop a one-directional request. The grid always
    reflects what helpers actually wrote on the form.

    ``broken_marks`` (``{"cells": [{"building", "room", "role", "line"}],
    "helpers": [{"helper_id", "line"}]}``, see CONTEXT.md "Broken rule") lightly
    marks the Broken rules' affected role cells (a ``role`` of ``None`` marks
    only the Room's column header), Room headers and helper chips; ``line`` is
    the banner's wording, shown as a tooltip. Purely visual — it never blocks
    or reroutes a drop.

    Tags (see CONTEXT.md "Tag"): a ``helpers`` entry may carry ``tags``
    (``{"direct": [{"name", "colour"}], "implied": [...]}``), which
    ``show_tags`` renders as pills under the Helper's name (direct solid,
    implied dashed); off by default. ``dimmed_helper_ids`` are the Helpers the
    Tag filter fades: they are never hidden, stay where they are and remain
    draggable. The two are independent. Both are computed by the caller.

    Returns ``{"type": "drop", "helper_id", "building", "room", "role"}`` for
    a completed drag-and-drop, ``{"type": "manual_set", "key", "building",
    "room", "names"}`` for an edited manual-role cell (``names`` is the
    cell's full new list of names), ``{"type": "cell_merge", "key",
    "building", "pairs", "merged"}`` for a merge/unmerge click within row
    ``key`` (``pairs`` is one or more ``[room_a, room_b]`` adjacent-name
    pairs to set to ``merged``), ``{"type": "lock", "helper_id", "locked"}``
    for a lock toggle (ctrl/cmd-click on a placed chip or the hover card's
    Lock/Unlock button; ``locked`` is the new value), or ``None`` otherwise — CCv2 triggers
    reset automatically after the rerun that reports them, so callers
    don't need to dedupe.
    """
    result = _component(
        key=key,
        data={
            "rooms": rooms,
            "rows": rows,
            "helpers": helpers,
            "assignments": assignments,
            "manual_entries": manual_entries,
            "cell_merges": cell_merges,
            "helper_names": helper_names,
            "broken_marks": broken_marks or {"cells": [], "helpers": []},
            "show_tags": show_tags,
            "dimmed_helper_ids": dimmed_helper_ids or [],
        },
        on_drop_change=_noop,
        on_manual_set_change=_noop,
        on_cell_merge_change=_noop,
        on_lock_change=_noop,
    )
    if result.drop:
        return {"type": "drop", **result.drop}
    if result.manual_set:
        return {"type": "manual_set", **result.manual_set}
    if result.cell_merge:
        return {"type": "cell_merge", **result.cell_merge}
    if result.lock:
        return {"type": "lock", **result.lock}
    return None
