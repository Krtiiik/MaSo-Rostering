"""Entry point for the Streamlit rostering app. Run via ``rostering serve``
(or directly: ``streamlit run rostering/streamlit_app/app.py``)."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, season_header, seasons_panel, session, versions_sidebar
from rostering.streamlit_app.tabs import config_tab, forced_friends_tab, grid_tab, tags_tab, upload_tab

_TABS = ["1. Upload", "2. Buildings", "3. Tags", "4. Forced friends", "5. Roster"]


def _migrate_saved_state() -> None:
    """First launch after Seasons were introduced: move the old single saved
    state (and its Versions) into a labelled Season. Silent when the label can
    be derived; otherwise asks once and stops the run until answered."""
    workspace = session.get_workspace()
    try:
        migrated = mutations.migrate_legacy_workspace(workspace)
    except mutations.SeasonLabelRequired as exc:
        st.title("Rostering")
        st.info(
            "Your earlier saved work is about to become a stored Season, along with its saved versions. "
            + str(exc)
        )
        with st.form(key="migrate_legacy_form"):
            label = st.text_input("Season label", value=exc.suggested_label or "", help="A year plus jaro or podzim.")
            submitted = st.form_submit_button("Save as this Season")
        if submitted:
            try:
                mutations.migrate_legacy_workspace(workspace, label=label)
            except mutations.SeasonLabelRequired as again:
                st.error(str(again))
            else:
                session.workspace_replaced(mutations.get_state(workspace))
                st.rerun()
        st.stop()
    if migrated is not None:
        session.workspace_replaced(mutations.get_state(workspace))


def main() -> None:
    st.set_page_config(page_title="Rostering", layout="wide")
    _migrate_saved_state()
    session.get_state()  # ensure the workspace is loaded before anything renders

    with st.sidebar:
        st.title("Rostering")
        seasons_panel.render()
        st.divider()
        versions_sidebar.render()
        st.divider()
        if st.button("Start over"):
            if st.session_state.get("_confirm_reset"):
                session.workspace_replaced(mutations.reset_workspace(session.get_workspace()))
                st.rerun()
            else:
                st.session_state["_confirm_reset"] = True
                st.warning(
                    "Click again to confirm — empties the open Season. Its label and saved versions are kept."
                )

    season_header.render()

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
    elif active_tab == "3. Tags":
        tags_tab.render()
    elif active_tab == "4. Forced friends":
        forced_friends_tab.render()
    elif active_tab == "5. Roster":
        grid_tab.render()


main()
