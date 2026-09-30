"""``st.session_state`` glue around the on-disk :class:`Workspace`.

Single-workspace design: one ``Workspace`` per Streamlit session — whichever
Season is open — backed by the Season directories under ``data/seasons/`` (or
``ROSTERING_SEASONS_DIR``) that every session shares on disk.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from rostering.persistence.workspace import Workspace

_WORKSPACE_KEY = "_workspace"
_STATE_KEY = "workspace_state"


def get_workspace() -> Workspace:
    if _WORKSPACE_KEY not in st.session_state:
        st.session_state[_WORKSPACE_KEY] = Workspace()
    return st.session_state[_WORKSPACE_KEY]


def get_state() -> dict[str, Any]:
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = get_workspace().load()
    return st.session_state[_STATE_KEY]


def set_state(new_state: dict[str, Any]) -> None:
    st.session_state[_STATE_KEY] = new_state


def workspace_replaced(new_state: dict[str, Any], keep_view: bool = False) -> None:
    """Make ``new_state`` the session's state after the Workspace changed under
    the UI (opened another Season, New Season, Start over, restored a Version)
    and drop every piece of UI state derived from the old one. ``keep_view``
    leaves the current tab and upload state alone (a Version restore)."""
    # Imported here: config_tab imports this module.
    from rostering.streamlit_app.tabs import config_tab

    set_state(new_state)
    config_tab.clear_drafts()
    if keep_view:
        return
    # (The last three are the roster grid's Tag controls, see grid_tab.)
    for key in (
        "_confirm_reset",
        "_last_upload_hash",
        "_active_tab",
        "_pending_tab",
        "_fix_focus",
        "_grid_show_tags",
        "_grid_tag_filter",
        "_grid_tag_mode",
    ):
        st.session_state.pop(key, None)
    # A new key gives the upload tab a fresh, empty file picker, so a file
    # picked for the previous Season isn't silently loaded into this one.
    st.session_state["_uploader_nonce"] = st.session_state.get("_uploader_nonce", 0) + 1


def switch_tab(tab: str) -> None:
    """Queue a tab switch for the next rerun.

    Can't just assign ``st.session_state["_active_tab"] = tab`` here: that key
    also backs the ``st.segmented_control`` tab strip in ``app.py``, and
    Streamlit raises ``StreamlitWidgetAlreadyInstantiatedError`` if a widget's
    session-state key is written after the widget has already rendered in the
    same script run (which is exactly when callers reach this function — from
    a button handler inside a tab that rendered after the tab strip). Queuing
    it here and applying it in ``app.py`` *before* the widget is instantiated
    on the next run avoids that.
    """
    st.session_state["_pending_tab"] = tab
