"""Header shown above every tab: the open Season's label, editable in place.
Rendered from ``app.py`` so it appears on every tab."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session


def render() -> None:
    workspace = session.get_workspace()
    season = mutations.get_open_season(workspace)
    if season is None:
        st.subheader("New Season")
        st.caption("Not saved yet — upload a responses file on the People tab to create the Season.")
        return

    title_col, edit_col = st.columns([0.8, 0.2], vertical_alignment="center")
    title_col.subheader(f"Season {season['label']}")
    with edit_col.popover("Rename", icon=":material/edit:"):
        with st.form(key="rename_open_season_form"):
            label = st.text_input("Season label", value=season["label"], help="A year plus jaro or podzim.")
            if st.form_submit_button("Save label"):
                try:
                    mutations.rename_season(workspace, season["id"], label)
                except mutations.RosteringError as exc:
                    st.error(str(exc))
                else:
                    session.set_state(mutations.get_state(workspace))
                    st.rerun()
