"""Tab 1: upload the raw survey export and resolve friend names."""
from __future__ import annotations

import hashlib

import streamlit as st

from rostering.domain import Role
from rostering.streamlit_app import mutations, session

_PREF_ROLES = [r for r in Role if r != Role.Zaloha]


def render() -> None:
    st.header("1. Upload responses")
    st.write(
        "Upload the raw Google Forms export (.xlsx) for the current helper "
        "responses. This replaces any previously uploaded helpers."
    )

    state = session.get_state()
    uploaded = st.file_uploader("Responses file", type=["xlsx"])
    if uploaded is not None:
        content = uploaded.getvalue()
        content_hash = hashlib.md5(content).hexdigest()
        if st.session_state.get("_last_upload_hash") != content_hash:
            with st.spinner("Uploading and parsing…"):
                try:
                    state = mutations.upload_responses(session.get_workspace(), content, uploaded.name)
                    session.set_state(state)
                    st.session_state["_last_upload_hash"] = content_hash
                except mutations.RosteringError as exc:
                    st.error(str(exc))
            st.rerun()

    if state["helpers"]:
        unresolved_count = sum(len(h["unresolved_friend_names"]) for h in state["helpers"])
        msg = f"**{len(state['helpers'])}** helpers loaded."
        if unresolved_count:
            msg += f" **{unresolved_count}** friend name(s) still need matching below."
        st.success(msg)

        if state["ingestion_warnings"]:
            with st.expander(f"{len(state['ingestion_warnings'])} ingestion warning(s)"):
                for warning in state["ingestion_warnings"]:
                    st.write(f"- {warning}")

        if st.button("Continue to buildings & rooms →", type="primary"):
            session.switch_tab("2. Buildings")
            st.rerun()

        _render_helpers_overview(state)
        _render_friend_resolution(state)


def _render_helpers_overview(state: dict) -> None:
    rows = []
    for h in state["helpers"]:
        buildings = ", ".join(h["building_preferences"]) or "any"
        equipment = " ".join(
            filter(None, ["💻" if h["can_bring_notebook"] else "", "📷" if h["can_bring_camera"] else ""])
        ) or "—"
        prefs = ", ".join(
            f"{role.value}: {h['role_preferences'][role.name]}"
            for role in _PREF_ROLES
            if role.name in h["role_preferences"]
        )
        friends = ", ".join(
            next((f["name"] for f in state["helpers"] if f["id"] == fid), f"#{fid}") for fid in h["friends"]
        )
        rows.append(
            {
                "Name": h["name"],
                "Buildings": buildings,
                "Equipment": equipment,
                "Role preferences": prefs,
                "Resolved friends": friends,
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_friend_resolution(state: dict) -> None:
    pairs = [(h, name) for h in state["helpers"] for name in h["unresolved_friend_names"]]
    if not pairs:
        return

    st.subheader("Resolve friend names")
    other_helpers = {h["id"]: h["name"] for h in state["helpers"]}
    for helper, name in pairs:
        candidates = [hid for hid in other_helpers if hid != helper["id"]]
        cols = st.columns([3, 3, 2, 2])
        cols[0].write(f"**{helper['name']}** named:")
        cols[1].write(f"“{name}”")
        chosen = cols[2].selectbox(
            "Match to…",
            options=candidates,
            format_func=lambda hid: other_helpers[hid],
            key=f"match_{helper['id']}_{name}",
            label_visibility="collapsed",
        )
        if cols[3].button("Match", key=f"match_btn_{helper['id']}_{name}"):
            try:
                session.set_state(
                    mutations.resolve_friend(session.get_workspace(), helper["id"], name, "resolve", chosen)
                )
            except mutations.RosteringError as exc:
                st.error(str(exc))
            st.rerun()
        if st.button("Not attending", key=f"dismiss_{helper['id']}_{name}"):
            try:
                session.set_state(mutations.resolve_friend(session.get_workspace(), helper["id"], name, "dismiss"))
            except mutations.RosteringError as exc:
                st.error(str(exc))
            st.rerun()
