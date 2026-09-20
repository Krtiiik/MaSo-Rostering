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
    roles: list[str],
    role_labels: dict[str, str],
    helpers: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    unsatisfied_helper_ids: list[int],
    key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Render the grid. Returns ``{"helper_id", "building", "room", "role"}``
    for a drop that just happened this rerun, or ``None`` otherwise — CCv2
    triggers reset automatically after the rerun that reports them, so
    callers don't need to dedupe.
    """
    result = _component(
        key=key,
        data={
            "rooms": rooms,
            "roles": roles,
            "role_labels": role_labels,
            "helpers": helpers,
            "assignments": assignments,
            "unsatisfied_helper_ids": unsatisfied_helper_ids,
        },
        on_drop_change=_noop,
    )
    return result.drop
