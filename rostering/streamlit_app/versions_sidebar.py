"""Sidebar panel for saving/restoring/deleting the open Season's named
Versions. Rendered on every tab from ``app.py``."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session


@st.dialog("Restore version")
def _confirm_restore(version: dict) -> None:
    st.warning(
        f"Restore **{version['name']}**? Everything this Season holds is rolled back to that snapshot: "
        "Person links, rejected matches, Tags, Forced-friend groups and Assignments (along with the "
        "helpers, buildings and every other edit made since). The Season's label is not rolled back."
    )
    restore_col, cancel_col = st.columns(2)
    if restore_col.button("Restore", type="primary", key="confirm_restore_version"):
        try:
            session.workspace_replaced(
                mutations.restore_version(session.get_workspace(), version["slug"]), keep_view=True
            )
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        st.rerun()
    if cancel_col.button("Cancel", key="cancel_restore_version"):
        st.rerun()


def render() -> None:
    st.subheader("Versions")
    workspace = session.get_workspace()
    if mutations.get_open_season(workspace) is None:
        st.caption("Versions belong to a Season — upload responses to create one first.")
        return

    with st.form(key="save_version_form", clear_on_submit=True):
        name = st.text_input("Version name…", label_visibility="collapsed", placeholder="Version name…")
        if st.form_submit_button("Save current as version") and name.strip():
            try:
                mutations.save_version(workspace, name.strip())
            except mutations.RosteringError as exc:
                st.error(str(exc))
            else:
                st.rerun()

    versions = mutations.list_versions(workspace)
    if not versions:
        st.caption("No saved versions yet.")
        return

    for v in versions:
        st.write(f"**{v['name']}**")
        st.caption(v["created_at"] or "")
        cols = st.columns(2)
        if cols[0].button("Restore", key=f"restore_{v['slug']}"):
            _confirm_restore(v)
        if cols[1].button("Delete", key=f"delete_{v['slug']}"):
            try:
                mutations.delete_version(workspace, v["slug"])
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
