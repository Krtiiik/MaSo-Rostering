"""Entry point for the Streamlit rostering app. Run via ``rostering serve``
(or directly: ``streamlit run rostering/streamlit_app/app.py``)."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import (
    labels,
    mutations,
    season_header,
    seasons_panel,
    session,
    solve_prompt,
    versions_sidebar,
)
from rostering.streamlit_app.tabs import config_tab, forced_friends_tab, grid_tab, people_tab, solver_tab, tags_tab


def _migrate_saved_state() -> None:
    """First launch after Seasons were introduced: move the old single saved
    state (and its Versions) into a labelled Season. Silent when the label can
    be derived; otherwise asks once and stops the run until answered."""
    workspace = session.get_workspace()
    try:
        migrated = mutations.migrate_legacy_workspace(workspace)
    except mutations.SeasonLabelRequired as exc:
        st.title(labels.APP_TITLE)
        st.info(
            "Vaše dřívější uložená práce se má stát uloženým ročníkem i s uloženými verzemi. "
            + str(exc)
        )
        with st.form(key="migrate_legacy_form"):
            label = st.text_input(
                labels.SEASON_LABEL_FIELD, value=exc.suggested_label or "", help=labels.SEASON_LABEL_HELP
            )
            submitted = st.form_submit_button("Uložit jako tento ročník")
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
    st.set_page_config(page_title=labels.APP_TITLE, layout="wide")
    _migrate_saved_state()
    session.get_state()  # ensure the workspace is loaded before anything renders

    with st.sidebar:
        st.title(labels.APP_TITLE)
        seasons_panel.render()
        st.divider()
        versions_sidebar.render()
        st.divider()
        if st.button("Začít znovu"):
            if st.session_state.get("_confirm_reset"):
                session.workspace_replaced(mutations.reset_workspace(session.get_workspace()))
                st.rerun()
            else:
                st.session_state["_confirm_reset"] = True
                st.warning(
                    "Kliknutím znovu potvrdíte — otevřený ročník se vyprázdní. Jeho označení a uložené verze zůstanou."
                )

    season_header.render()

    st.session_state.setdefault("_active_tab", labels.TABS[0])
    if "_pending_tab" in st.session_state:
        # Must happen before the segmented_control below is instantiated —
        # see session.switch_tab's docstring.
        st.session_state["_active_tab"] = st.session_state.pop("_pending_tab")

    active_tab = st.segmented_control(
        "Sekce",
        labels.TABS,
        key="_active_tab",
        required=True,
        label_visibility="collapsed",
    )

    if active_tab == labels.TAB_PEOPLE:
        people_tab.render()
    elif active_tab == labels.TAB_TAGS:
        tags_tab.render()
    elif active_tab == labels.TAB_FORCED:
        forced_friends_tab.render()
    elif active_tab == labels.TAB_BUILDINGS:
        config_tab.render()
    elif active_tab == labels.TAB_SOLVER:
        solver_tab.render()
    elif active_tab == labels.TAB_ROSTER:
        grid_tab.render()

    # Last, so a queued Solve runs over the fully drawn page (see solve_prompt).
    solve_prompt.run_pending()


main()
