"""The persistent summary of a re-upload, shown at the top of the Upload and
Roster tabs until the user dismisses it (see mutations.upload_summary)."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session


def render(where: str) -> None:
    """Draw the summary, if there is one. ``where`` keeps the widget keys of
    the two tabs that show it apart."""
    workspace = session.get_workspace()
    summary = mutations.upload_summary(workspace)
    if summary is None:
        return
    with st.container(border=True):
        title_col, dismiss_col = st.columns([6, 1], vertical_alignment="center")
        title_col.markdown("**What the latest upload changed**")
        if dismiss_col.button("Dismiss", key=f"dismiss_upload_summary_{where}"):
            session.set_state(mutations.dismiss_upload_summary(workspace))
            st.rerun()

        if summary["new"]:
            st.markdown(
                f"**{len(summary['new'])} new registrant(s)**, not placed yet (Export is blocked until they are): "
                + ", ".join(entry["name"] for entry in summary["new"])
            )
        if summary["changed"]:
            st.markdown(
                f"**{len(summary['changed'])} placed helper(s) changed their answers** (their Assignment was left "
                "as it is; marked ✎ in the grid until you move or lock them):"
            )
            for entry in summary["changed"]:
                st.markdown(f"- {entry['name']}: {', '.join(entry['fields'])}")
        if summary["missing"]:
            st.markdown(
                f"**{len(summary['missing'])} helper(s) missing from the export** (kept as they are): "
                + ", ".join(entry["name"] for entry in summary["missing"])
            )
        if summary["uncertain"]:
            st.markdown(
                f"**{len(summary['uncertain'])} uncertain match(es) awaiting review** (in the Upload tab): "
                + ", ".join(entry["helper_name"] for entry in summary["uncertain"])
            )
