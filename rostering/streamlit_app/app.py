"""Entry point for the Streamlit rostering app. Run via ``rostering serve``
(or directly: ``streamlit run rostering/streamlit_app/app.py``)."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session, versions_sidebar
from rostering.streamlit_app.tabs import config_tab, grid_tab, upload_tab

_TABS = ["1. Upload", "2. Buildings", "3. Roster"]


def main() -> None:
    st.set_page_config(page_title="Rostering", layout="wide")
    session.get_state()  # ensure the workspace is loaded before anything renders

    with st.sidebar:
        st.title("Rostering")
        versions_sidebar.render()
        st.divider()
        if st.button("Start over"):
            if st.session_state.get("_confirm_reset"):
                session.set_state(mutations.reset_workspace(session.get_workspace()))
                config_tab.clear_drafts()
                for key in ("_confirm_reset", "_last_upload_hash", "_active_tab", "_pending_tab"):
                    st.session_state.pop(key, None)
                st.rerun()
            else:
                st.session_state["_confirm_reset"] = True
                st.warning("Click again to confirm — clears the current workspace.")

    st.session_state.setdefault("_active_tab", _TABS[0])
    if "_pending_tab" in st.session_state:
        # Must happen before the segmented_control below is instantiated —
        # see session.switch_tab's docstring.
        st.session_state["_active_tab"] = st.session_state.pop("_pending_tab")

    active_tab = st.segmented_control(
        "Section",
        _TABS,
        key="_active_tab",
        required=True,
        label_visibility="collapsed",
    )

    if active_tab == "1. Upload":
        upload_tab.render()
    elif active_tab == "2. Buildings":
        config_tab.render()
    elif active_tab == "3. Roster":
        grid_tab.render()


main()
