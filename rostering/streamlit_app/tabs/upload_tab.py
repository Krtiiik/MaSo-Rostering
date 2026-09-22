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


def _decision_ids(value: object) -> list[int] | None:
    """Normalize a friend_name_decisions value to a list of ids (or None for
    dismissed). Older persisted state stored a single int per name instead
    of a list."""
    if value is None:
        return None
    if isinstance(value, int):
        return [value]
    return list(value)


def _render_friend_resolution(state: dict) -> None:
    rows = []
    for h in state["helpers"]:
        decisions = h.get("friend_name_decisions", {})
        all_names = list(dict.fromkeys(list(h["unresolved_friend_names"]) + list(decisions)))
        # friend_name_order is fixed at upload time so names keep their
        # original position even after being resolved and dropping out of
        # unresolved_friend_names; fall back to encounter order for state
        # persisted before that field existed.
        order_index = {n: i for i, n in enumerate(h.get("friend_name_order") or [])}
        names = sorted(all_names, key=lambda n: order_index.get(n, len(order_index)))
        if names:
            rows.append((h, names))
    if not rows:
        return

    st.subheader("Resolve friend names")
    st.caption("A name can match more than one helper if it refers to a group of people.")
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
            decided_ids = _decision_ids(decisions.get(name))
            if was_decided and decided_ids is None:
                default = [_DISMISS_LABEL]
            elif was_decided:
                default = [other_helpers[hid] for hid in decided_ids if hid in other_helpers]
            else:
                default = []
            choice = select_col.multiselect(
                name,
                options=options,
                default=default,
                placeholder=_UNRESOLVED_PLACEHOLDER,
                accept_new_options=True,
                key=f"match_{helper['id']}_{name}",
                label_visibility="collapsed",
            )
            if not choice:
                continue

            if _DISMISS_LABEL in choice:
                if len(choice) > 1:
                    select_col.warning(f"“{_DISMISS_LABEL}” can't be combined with other matches.")
                    continue
                if was_decided and decided_ids is None:
                    continue
                try:
                    session.set_state(
                        mutations.resolve_friend(session.get_workspace(), helper["id"], name, "dismiss")
                    )
                except mutations.RosteringError as exc:
                    st.error(str(exc))
                    continue
                st.rerun()
                continue

            resolved_ids = []
            unknown = []
            for picked in choice:
                hid = helper_id_by_name.get(picked)
                (resolved_ids if hid is not None else unknown).append(hid if hid is not None else picked)
            if unknown:
                names_str = ", ".join(f"“{u}”" for u in unknown)
                select_col.warning(f"{names_str} doesn't match any known helper.")
                continue
            if was_decided and decided_ids == resolved_ids:
                continue
            try:
                session.set_state(
                    mutations.resolve_friend(
                        session.get_workspace(), helper["id"], name, "resolve", resolved_ids
                    )
                )
            except mutations.RosteringError as exc:
                st.error(str(exc))
                continue
            st.rerun()
