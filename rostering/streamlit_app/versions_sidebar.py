"""Sidebar panel for saving/restoring/deleting the open Season's named
Versions. Rendered on every tab from ``app.py``."""
from __future__ import annotations

import streamlit as st

from rostering.webapp import mutations
from rostering.streamlit_app import session


@st.dialog("Obnovit verzi")
def _confirm_restore(version: dict) -> None:
    st.warning(
        f"Obnovit **{version['name']}**? Vše, co ročník obsahuje, se vrátí do stavu té verze: "
        "propojení osob, odmítnutá spojení, štítky, vynucené skupinky kamarádů a přiřazení (spolu s "
        "pomocníky, budovami a všemi dalšími úpravami provedenými od té doby). "
        "Označení ročníku se nevrací."
    )
    restore_col, cancel_col = st.columns(2)
    if restore_col.button("Obnovit", type="primary", key="confirm_restore_version"):
        try:
            session.workspace_replaced(
                mutations.restore_version(session.get_workspace(), version["slug"]), keep_view=True
            )
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        st.rerun()
    if cancel_col.button("Zrušit", key="cancel_restore_version"):
        st.rerun()


def render() -> None:
    st.subheader("Verze")
    workspace = session.get_workspace()
    if mutations.get_open_season(workspace) is None:
        st.caption("Verze patří k ročníku — nejdřív nahrajte odpovědi, tím se ročník vytvoří.")
        return

    with st.form(key="save_version_form", clear_on_submit=True):
        name = st.text_input("Název verze…", label_visibility="collapsed", placeholder="Název verze…")
        if st.form_submit_button("Uložit aktuální stav jako verzi") and name.strip():
            try:
                mutations.save_version(workspace, name.strip())
            except mutations.RosteringError as exc:
                st.error(str(exc))
            else:
                st.rerun()

    versions = mutations.list_versions(workspace)
    if not versions:
        st.caption("Zatím žádné uložené verze.")
        return

    for v in versions:
        st.write(f"**{v['name']}**")
        st.caption(v["created_at"] or "")
        cols = st.columns(2)
        if cols[0].button("Obnovit", key=f"restore_{v['slug']}"):
            _confirm_restore(v)
        if cols[1].button("Smazat", key=f"delete_{v['slug']}"):
            try:
                mutations.delete_version(workspace, v["slug"])
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
