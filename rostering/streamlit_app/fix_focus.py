"""The "Go fix" hand-off from a Broken rule to the tab where it is fixed.

A Broken-rule banner line's "Go fix" button switches tab and *preselects the
entity*: the target tab shows what to fix (a callout naming the rule, and a
marker on the building / helper row), for as long as that rule instance is
still broken — once the rule holds again the focus disappears by itself.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from rostering.domain import BrokenRule, FixTarget
from rostering.streamlit_app import mutations, session

_KEY = "_fix_focus"

# Logical FixTarget.tab -> the tab strip's label (app.py's _TABS). A rule
# family whose tab does not exist yet has no entry, hence no "Go fix" button.
TAB_LABELS = {
    "buildings": "4. Buildings",
    "helpers": "1. People",
    "tags": "2. Tags",
    "forced_friends": "3. Forced friends",
}


def can_go_fix(broken: BrokenRule) -> bool:
    return broken.fix is not None and broken.fix.tab in TAB_LABELS


def go_fix(broken: BrokenRule) -> None:
    """Queue the switch to the rule's fix tab and remember what to preselect
    there. Call it from a button handler, then ``st.rerun()``."""
    assert broken.fix is not None
    st.session_state[_KEY] = {
        "kind": broken.instance.kind,
        "entity": list(broken.instance.entity),
        "line": broken.line,
        "fix": broken.fix,
    }
    if broken.fix.tab == "tags" and broken.fix.tag_id is not None:
        # Imported here: the Tags tab itself imports this module.
        from rostering.streamlit_app.tabs import tags_tab

        tags_tab.focus_tag(broken.fix.tag_id)
    if broken.fix.tab == "forced_friends" and broken.fix.group_id is not None:
        from rostering.streamlit_app.tabs import forced_friends_tab

        forced_friends_tab.focus_group(broken.fix.group_id)
    session.switch_tab(TAB_LABELS[broken.fix.tab])


def current(state: dict, tab: str) -> Optional[FixTarget]:
    """The FixTarget to preselect on ``tab`` (a ``FixTarget.tab`` name), or
    ``None`` — also when the focused rule instance no longer breaks."""
    focus = st.session_state.get(_KEY)
    if not focus or focus["fix"].tab != tab:
        return None
    instance = (focus["kind"], tuple(focus["entity"]))
    if not any((b.instance.kind, b.instance.entity) == instance for b in mutations.broken_rules(state)):
        st.session_state.pop(_KEY, None)
        return None
    return focus["fix"]


def render_callout(state: dict, tab: str) -> Optional[FixTarget]:
    """Show the focused rule on its tab, with a way to dismiss it. Returns the
    target so the tab can also mark the row it names."""
    fix = current(state, tab)
    if fix is None:
        return None
    line = st.session_state[_KEY]["line"]
    cols = st.columns([6, 1], vertical_alignment="center")
    cols[0].info(f"**Fixing:** {line}", icon="🔧")
    if cols[1].button("Dismiss", key="fix_focus_dismiss"):
        st.session_state.pop(_KEY, None)
        st.rerun()
    return fix
