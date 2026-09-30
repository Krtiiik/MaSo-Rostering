"""Header shown above every tab: the open Season's label, editable in place.
Rendered from ``app.py`` so it appears on every tab."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import labels, mutations, session


def render() -> None:
    workspace = session.get_workspace()
    season = mutations.get_open_season(workspace)
    if season is None:
        st.subheader("Nový ročník")
        st.caption("Zatím neuloženo — ročník se vytvoří nahráním souboru s odpověďmi na záložce Lidé.")
        return

    title_col, edit_col = st.columns([0.8, 0.2], vertical_alignment="center")
    title_col.subheader(f"Ročník {season['label']}")
    with edit_col.popover("Přejmenovat", icon=":material/edit:"):
        with st.form(key="rename_open_season_form"):
            label = st.text_input(labels.SEASON_LABEL_FIELD, value=season["label"], help=labels.SEASON_LABEL_HELP)
            if st.form_submit_button("Uložit označení"):
                try:
                    mutations.rename_season(workspace, season["id"], label)
                except mutations.RosteringError as exc:
                    st.error(str(exc))
                else:
                    session.set_state(mutations.get_state(workspace))
                    st.rerun()
