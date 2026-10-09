"""Sidebar panel listing every stored Season with Open, Rename and Delete, plus
"New Season". Rendered from ``app.py`` next to the Versions panel."""
from __future__ import annotations

import streamlit as st

from rostering.czech import count_helpers
from rostering.webapp import labels, mutations
from rostering.streamlit_app import session


@st.dialog("Smazat ročník")
def _confirm_delete(season: dict) -> None:
    workspace = session.get_workspace()
    st.warning(
        f"Smazat **{season['label']}** ({count_helpers(season['helper_count'])})? Nelze vrátit zpět. "
        "Ztratíte tento ročník jako zdroj pro import štítků a každou osobu, kterou znáte jen z něj; "
        "smažou se s ním i všechny jeho uložené verze."
    )
    delete_col, cancel_col = st.columns(2)
    if delete_col.button("Smazat ročník", type="primary", key="confirm_delete_season"):
        try:
            mutations.delete_season(workspace, season["id"])
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        st.rerun()
    if cancel_col.button("Zrušit", key="cancel_delete_season"):
        st.rerun()


def render() -> None:
    workspace = session.get_workspace()
    st.subheader("Ročníky")
    if st.button("Nový ročník", icon=":material/add:", key="new_season"):
        session.workspace_replaced(mutations.new_season(workspace))
        st.rerun()

    seasons = mutations.list_seasons(workspace)
    if not seasons:
        st.caption("Zatím žádné uložené ročníky.")
        return

    for season in seasons:
        with st.container(border=True):
            state_label = "otevřený" if season["open"] else "uložený"
            st.markdown(f"**{season['label']}**")
            st.caption(f"{count_helpers(season['helper_count'])} · {state_label}")
            open_col, rename_col, delete_col = st.columns(3)
            if not season["open"] and open_col.button("Otevřít", key=f"open_season_{season['id']}"):
                try:
                    session.workspace_replaced(mutations.open_season(workspace, season["id"]))
                except mutations.RosteringError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            with rename_col.popover("Přejmenovat", key=f"rename_pop_{season['id']}"):
                with st.form(key=f"rename_form_{season['id']}"):
                    label = st.text_input(
                        labels.SEASON_LABEL_FIELD, value=season["label"], help=labels.SEASON_LABEL_HELP
                    )
                    if st.form_submit_button("Uložit označení"):
                        try:
                            mutations.rename_season(workspace, season["id"], label)
                        except mutations.RosteringError as exc:
                            st.error(str(exc))
                        else:
                            session.set_state(mutations.get_state(workspace))
                            st.rerun()
            # Delete is never offered on the open Season.
            if not season["open"] and delete_col.button("Smazat", key=f"delete_season_{season['id']}"):
                _confirm_delete(season)
