"""Header shown above every tab: the open Season's label (renamed from the sidebar's
Seasons panel). Rendered from ``app.py`` so it appears on every tab."""
from __future__ import annotations

import streamlit as st

from rostering.webapp import mutations
from rostering.streamlit_app import session


def render() -> None:
    workspace = session.get_workspace()
    season = mutations.get_open_season(workspace)
    if season is None:
        st.subheader("Nový ročník")
        st.caption("Zatím neuloženo — ročník se vytvoří nahráním souboru s odpověďmi na záložce Lidé.")
        return

    st.subheader(f"Ročník {season['label']}")
