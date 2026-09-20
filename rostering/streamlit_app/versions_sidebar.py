"""Sidebar panel for saving/restoring/deleting named workspace versions.
Rendered on every tab from ``app.py``."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session
from rostering.streamlit_app.tabs import config_tab


def render() -> None:
    st.subheader("Versions")
    workspace = session.get_workspace()

    with st.form(key="save_version_form", clear_on_submit=True):
        name = st.text_input("Version name…", label_visibility="collapsed", placeholder="Version name…")
        if st.form_submit_button("Save current as version") and name.strip():
            mutations.save_version(workspace, name.strip())
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
            try:
                session.set_state(mutations.restore_version(workspace, v["slug"]))
                config_tab.clear_drafts()
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
        if cols[1].button("Delete", key=f"delete_{v['slug']}"):
            try:
                mutations.delete_version(workspace, v["slug"])
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
