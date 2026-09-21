"""Tab 2: buildings/rooms/capacities editor and solver weight tuning."""
from __future__ import annotations

import copy

import streamlit as st

from rostering.domain import Role
from rostering.streamlit_app import mutations, session

_ROLE_LABELS = {r.name: r.value for r in Role}
_ROLE_ORDER = [r.name for r in Role]

_ADD_ROOM_COL_CSS = """
<style>
div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-add_room_col_"]) {
    align-items: stretch !important;
}
/* Filling the button down to 100% height via plain nested percentage
   heights makes Chromium's flex layout runaway (each reflow re-measures a
   stale, ever-growing ancestor height), ballooning the column to roughly
   the full page height. Anchoring the column with absolute positioning
   against its (now stretched-to-the-table) stColumn parent sidesteps that
   feedback loop entirely, since an absolutely positioned box can't feed
   back into its ancestors' auto-height calculation. !important is needed
   throughout because Streamlit's own emotion-cache rules for these same
   elements are injected into <head> after this markdown's <style> tag and
   would otherwise win the cascade on tied specificity. */
div[data-testid="stColumn"]:has(div[class*="st-key-add_room_col_"]) {
    position: relative !important;
}
div[class*="st-key-add_room_col_"] {
    position: absolute !important;
    inset: 0 !important;
    display: flex !important;
    flex-direction: column !important;
}
div[class*="st-key-add_room_col_"] > div[data-testid="stElementContainer"] {
    height: 100% !important;
    flex: 1 1 auto !important;
}
div[class*="st-key-add_room_col_"] div[data-testid="stButton"] {
    height: 100% !important;
    display: flex !important;
}
div[class*="st-key-add_room_col_"] button {
    height: 100% !important;
    width: 100% !important;
    writing-mode: vertical-rl;
    text-orientation: mixed;
}
</style>
"""


def _capacity_cell(min_col, max_col, capacities: dict, role_name: str, key: str) -> None:
    cap = capacities.get(role_name, {"minimum": 0, "maximum": None})
    minimum = min_col.number_input(
        "Min",
        value=int(cap.get("minimum") or 0),
        min_value=0,
        step=1,
        key=f"{key}_min",
        label_visibility="collapsed",
    )
    existing_max = cap.get("maximum")
    maximum = max_col.number_input(
        "Max",
        value=int(existing_max) if existing_max is not None else None,
        min_value=0,
        step=1,
        key=f"{key}_max",
        label_visibility="collapsed",
        placeholder="∞",
    )
    capacities[role_name] = {"minimum": int(minimum), "maximum": None if maximum is None else int(maximum)}


def _render_building_table(building: dict, bi: int) -> None:
    rooms: list[dict] = building["rooms"]
    n_units = 1 + len(rooms)  # building-wide unit + one per room

    outer = st.columns([1 + 2 * n_units, 1])
    with outer[0]:
        header_cols = st.columns([1] + [2] * n_units)
        header_cols[0].write("")
        header_cols[1].markdown(f"**{building['name'] or 'Building'} (overall)**")
        for ri, room in enumerate(rooms):
            with header_cols[2 + ri]:
                room["name"] = st.text_input(
                    "Room name", value=room["name"], key=f"rname_{bi}_{ri}", label_visibility="collapsed"
                )

        subheader_cols = st.columns([1] + [1, 1] * n_units)
        subheader_cols[0].write("")
        for i in range(n_units):
            subheader_cols[1 + 2 * i].caption("Min")
            subheader_cols[2 + 2 * i].caption("Max")

        for role_name in _ROLE_ORDER:
            row_cols = st.columns([1] + [1, 1] * n_units)
            row_cols[0].write(_ROLE_LABELS[role_name])
            _capacity_cell(row_cols[1], row_cols[2], building["capacities"], role_name, key=f"bcap_{bi}_{role_name}")
            for ri, room in enumerate(rooms):
                _capacity_cell(
                    row_cols[3 + 2 * ri],
                    row_cols[4 + 2 * ri],
                    room["capacities"],
                    role_name,
                    key=f"rcap_{bi}_{ri}_{role_name}",
                )

        remove_cols = st.columns([1] + [2] * n_units)
        remove_cols[0].write("")
        remove_cols[1].write("")
        for ri, room in enumerate(rooms):
            if remove_cols[2 + ri].button("Remove room", key=f"remove_room_{bi}_{ri}", width="stretch"):
                rooms.pop(ri)
                st.rerun()

    with outer[1]:
        st.markdown(_ADD_ROOM_COL_CSS, unsafe_allow_html=True)
        with st.container(key=f"add_room_col_{bi}"):
            if st.button("+ Add room", key=f"add_room_{bi}", width="stretch"):
                rooms.append({"name": f"Room {len(rooms) + 1}", "capacities": {}})
                st.rerun()


def _ensure_drafts(state: dict) -> None:
    st.session_state.setdefault("config_draft", copy.deepcopy(state["config"]))
    st.session_state.setdefault("solver_config_draft", copy.deepcopy(state["solver_config"]))


def clear_drafts() -> None:
    st.session_state.pop("config_draft", None)
    st.session_state.pop("solver_config_draft", None)


def render() -> None:
    st.header("2. Buildings & rooms")
    st.write("Define the buildings, their rooms, and how many of each role each can hold this season.")

    state = session.get_state()
    _ensure_drafts(state)
    buildings: list[dict] = st.session_state["config_draft"]
    solver_config: dict = st.session_state["solver_config_draft"]

    for bi, building in enumerate(buildings):
        with st.expander(building["name"] or f"Building {bi + 1}", expanded=True):
            cols = st.columns([1, 4], vertical_alignment="bottom")
            if cols[0].button("Remove building", key=f"remove_building_{bi}"):
                buildings.pop(bi)
                st.rerun()
            building["name"] = cols[1].text_input("Building name", value=building["name"], key=f"bname_{bi}")

            _render_building_table(building, bi)

    with st.form(key="add_building_form", clear_on_submit=True):
        new_building_name = st.text_input("New building name")
        if st.form_submit_button("+ Add building") and new_building_name:
            buildings.append({"name": new_building_name, "rooms": [], "capacities": {}})
            st.rerun()

    st.subheader("Solver weights")
    weights = solver_config["weights"]
    weights["role_preference"] = st.number_input(
        "Role preference weight", value=int(weights["role_preference"]), key="w_role_pref"
    )
    weights["building_mismatch"] = st.number_input(
        "Building mismatch weight", value=int(weights["building_mismatch"]), key="w_building"
    )
    weights["friend_unsatisfied"] = st.number_input(
        "Friend-unsatisfied weight", value=int(weights["friend_unsatisfied"]), key="w_friend"
    )
    friend_scoring = solver_config["friend_scoring"]
    friend_scoring["mode"] = st.selectbox(
        "Friend scoring mode",
        options=["pairwise", "mutual"],
        index=["pairwise", "mutual"].index(friend_scoring["mode"]),
        format_func=lambda m: "Pairwise (partial credit per request)" if m == "pairwise" else "Mutual only (both must name each other)",
        key="w_mode",
    )
    friend_scoring["symmetric"] = st.checkbox(
        "Symmetric (merge a mutual pair into one scored request instead of two)",
        value=friend_scoring["symmetric"],
        key="w_symmetric",
    )

    with st.bottom:
        action_cols = st.columns(2)
        if action_cols[0].button("Save config"):
            try:
                session.set_state(mutations.put_config(session.get_workspace(), buildings))
                st.success("Config saved.")
            except mutations.RosteringError as exc:
                st.error(str(exc))

        disabled = not state["helpers"]
        if action_cols[1].button("Save & solve", type="primary", disabled=disabled):
            with st.spinner("Solving…"):
                try:
                    mutations.put_config(session.get_workspace(), buildings)
                    mutations.put_solver_config(session.get_workspace(), solver_config)
                    session.set_state(mutations.solve(session.get_workspace()))
                    session.switch_tab("3. Roster")
                    st.rerun()
                except mutations.RosteringError as exc:
                    st.error(str(exc))
        if disabled:
            st.caption("Upload helper responses first.")
