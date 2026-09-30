"""Tagging Helpers inline, in the Upload tab's Helper list: a multiselect of each
Helper's direct Tags next to their implied Tags (direct pills solid, implied
dashed), and a bulk "apply a tag to all shown" over the filtered list. Runs as a
fragment, so a tagging edit reruns only this section."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session, tag_pills

# A refused pick's reason, shown once after the rerun, and a counter that gives
# the pickers fresh widgets so they show what is saved again.
_ERROR = "_helper_tags_error"
_NONCE = "_helper_tags_nonce"


def _matches(state: dict, helper: dict, needle: str, filter_tags: list[int]) -> bool:
    if needle and needle not in helper["name"].casefold():
        return False
    if not filter_tags:
        return True
    effective = mutations.helper_tags(state, helper["id"])["effective"]
    return any(t in effective for t in filter_tags)


@st.fragment
def render() -> None:
    state = session.get_state()
    if not state["helpers"]:
        return
    with st.expander("Tag helpers", expanded=bool(state["tags"])):
        nonce = st.session_state.get(_NONCE, 0)
        refused = st.session_state.pop(_ERROR, None)
        if refused:
            st.error(refused)
        if not state["tags"]:
            st.caption("No Tags in this Season yet. Create some in the Tags tab, then tag Helpers here or there.")
            return
        tags = {t["id"]: t for t in state["tags"]}
        find_col, filter_col = st.columns(2)
        needle = find_col.text_input("Find a helper", key="helper_tags_find", placeholder="Type part of a name")
        filter_tags = filter_col.multiselect(
            "Only helpers with (directly or implied)",
            options=list(tags),
            format_func=lambda tid: tags[tid]["name"],
            key="helper_tags_filter",
        )
        shown = sorted(
            (h for h in state["helpers"] if _matches(state, h, needle.strip().casefold(), filter_tags)),
            key=lambda h: h["name"].lower(),
        )

        bulk_col, bulk_button_col = st.columns([3, 2], vertical_alignment="bottom")
        bulk_tag = bulk_col.selectbox(
            "Apply a tag to all shown",
            options=list(tags),
            index=None,
            format_func=lambda tid: tags[tid]["name"],
            placeholder="Pick a tag",
            key="helper_tags_bulk",
        )
        if bulk_button_col.button(
            f"Apply to {len(shown)} shown" if bulk_tag is None else f"Apply {tags[bulk_tag]['name']} to {len(shown)} shown",
            disabled=bulk_tag is None or not shown,
            key="helper_tags_bulk_apply",
        ):
            try:
                session.set_state(
                    mutations.add_tag_to_helpers(session.get_workspace(), bulk_tag, [h["id"] for h in shown])
                )
            except mutations.RosteringError as exc:
                st.error(str(exc))
            else:
                st.rerun()

        if not shown:
            st.caption("No helper matches.")
            return
        with st.container(height=420, border=True):
            for helper in shown:
                name_col, pick_col, pills_col = st.columns([3, 5, 5], vertical_alignment="center")
                name_col.write(helper["name"])
                direct = mutations.helper_tags(state, helper["id"])["direct"]
                picked = pick_col.multiselect(
                    f"Tags of {helper['name']}",
                    options=list(tags),
                    default=direct,
                    format_func=lambda tid: tags[tid]["name"],
                    # The saved Tags are part of the key, so the picker starts
                    # afresh from them after any other edit (bulk apply, a
                    # deleted Tag) instead of keeping a stale selection; the
                    # nonce does the same after a refused pick.
                    key=f"helper_tags_{helper['id']}_{'-'.join(map(str, direct))}_{nonce}",
                    label_visibility="collapsed",
                    placeholder="No tags",
                )
                current = state
                if set(picked) != set(direct):
                    try:
                        current = mutations.set_helper_tags(session.get_workspace(), helper["id"], picked)
                    except mutations.RosteringError as exc:
                        # Refused (say, it would leave them no allowed Building):
                        # show why and put the picker back to what is saved.
                        st.session_state[_ERROR] = str(exc)
                        st.session_state[_NONCE] = nonce + 1
                        st.rerun(scope="fragment")
                    else:
                        session.set_state(current)
                        state = current
                own = mutations.helper_tags(current, helper["id"])
                pills_col.html(
                    tag_pills.pills_html(
                        (tags[t] for t in own["direct"] if t in tags), (tags[t] for t in own["implied"] if t in tags)
                    )
                    or '<span style="opacity:.5">—</span>'
                )
