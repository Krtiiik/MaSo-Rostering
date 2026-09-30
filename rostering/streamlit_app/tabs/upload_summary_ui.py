"""The persistent summary of a re-upload, shown at the top of the Upload and
Roster tabs until the user dismisses it (see mutations.upload_summary)."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import labels, mutations, session


def render(where: str) -> None:
    """Draw the summary, if there is one. ``where`` keeps the widget keys of
    the two tabs that show it apart."""
    workspace = session.get_workspace()
    summary = mutations.upload_summary(workspace)
    if summary is None:
        return
    with st.container(border=True):
        title_col, dismiss_col = st.columns([6, 1], vertical_alignment="center")
        title_col.markdown("**Co změnilo poslední nahrání**")
        if dismiss_col.button("Skrýt", key=f"dismiss_upload_summary_{where}"):
            session.set_state(mutations.dismiss_upload_summary(workspace))
            st.rerun()

        if summary["new"]:
            st.markdown(
                f"**Noví zájemci ({len(summary['new'])})**, zatím nezařazení (export je zablokovaný, dokud nebudou): "
                + ", ".join(entry["name"] for entry in summary["new"])
            )
        if summary["changed"]:
            st.markdown(
                f"**Zařazení pomocníci, kteří změnili odpovědi ({len(summary['changed'])})** (jejich přiřazení zůstalo "
                "beze změny; v mřížce jsou označeni ✎, dokud je nepřesunete nebo neuzamknete):"
            )
            for entry in summary["changed"]:
                st.markdown(f"- {entry['name']}: {', '.join(labels.answer_label(f) for f in entry['fields'])}")
        if summary["missing"]:
            st.markdown(
                f"**Pomocníci chybějící v exportu ({len(summary['missing'])})** (zůstávají, jak jsou): "
                + ", ".join(entry["name"] for entry in summary["missing"])
            )
        if summary["uncertain"]:
            st.markdown(
                f"**Nejisté shody čekající na posouzení ({len(summary['uncertain'])})** (na záložce Lidé): "
                + ", ".join(entry["helper_name"] for entry in summary["uncertain"])
            )
