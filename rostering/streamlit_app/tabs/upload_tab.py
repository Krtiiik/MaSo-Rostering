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

        with st.bottom:
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


_DISMISS_LABEL = "✕ Not attending"
_UNRESOLVED_PLACEHOLDER = "Unresolved / Unmatched / Unknown"


def _render_friend_resolution(state: dict) -> None:
    rows = []
    for h in state["helpers"]:
        decisions = h.get("friend_name_decisions", {})
        names = list(h["unresolved_friend_names"]) + [n for n in decisions if n not in h["unresolved_friend_names"]]
        if names:
            rows.append((h, names))
    if not rows:
        return

    st.subheader("Resolve friend names")
    other_helpers = {h["id"]: h["name"] for h in state["helpers"]}
    for helper, names in rows:
        decisions = helper.get("friend_name_decisions", {})
        candidates = sorted(
            (hid for hid in other_helpers if hid != helper["id"]),
            key=lambda hid: other_helpers[hid].lower(),
        )
        helper_id_by_name = {other_helpers[hid]: hid for hid in candidates}
        options = [_DISMISS_LABEL, *(other_helpers[hid] for hid in candidates)]

        st.markdown(f"**{helper['name']}** named:")
        for name in names:
            _, label_col, select_col = st.columns([0.3, 2, 3])
            label_col.write(f"“{name}”")
            was_decided = name in decisions
            default_index = None
            if was_decided:
                decided_id = decisions[name]
                if decided_id is None:
                    default_index = options.index(_DISMISS_LABEL)
                else:
                    decided_name = other_helpers.get(decided_id)
                    if decided_name in options:
                        default_index = options.index(decided_name)
            choice = select_col.selectbox(
                name,
                options=options,
                index=default_index,
                placeholder=_UNRESOLVED_PLACEHOLDER,
                accept_new_options=True,
                key=f"match_{helper['id']}_{name}",
                label_visibility="collapsed",
            )
            if choice is None or (was_decided and choice == _dismiss_or_name(decisions[name], other_helpers)):
                continue
            resolved_id = helper_id_by_name.get(choice)
            if choice != _DISMISS_LABEL and resolved_id is None:
                select_col.warning(f"“{choice}” doesn't match any known helper.")
                continue
            try:
                if choice == _DISMISS_LABEL:
                    session.set_state(
                        mutations.resolve_friend(session.get_workspace(), helper["id"], name, "dismiss")
                    )
                else:
                    session.set_state(
                        mutations.resolve_friend(session.get_workspace(), helper["id"], name, "resolve", resolved_id)
                    )
            except mutations.RosteringError as exc:
                st.error(str(exc))
                continue
            st.rerun()


def _dismiss_or_name(decided_id: int | None, other_helpers: dict[int, str]) -> str:
    return _DISMISS_LABEL if decided_id is None else other_helpers.get(decided_id, _DISMISS_LABEL)
