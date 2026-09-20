"""``st.session_state`` glue around the on-disk :class:`Workspace`.

Single-workspace design, same as the old web app: one ``Workspace`` per
Streamlit session, backed by the same ``data/workspace/state.json`` (or
``ROSTERING_WORKSPACE_DIR``) file every session shares on disk.
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
