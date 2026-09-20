"""Tab 2: buildings/rooms/capacities editor and solver weight tuning."""
from __future__ import annotations

import copy

import pandas as pd
import streamlit as st

from rostering.domain import Role
from rostering.streamlit_app import mutations, session

_ROLE_LABELS = {r.name: r.value for r in Role}
_ROLE_ORDER = [r.name for r in Role]


def _capacity_rows(capacities: dict) -> pd.DataFrame:
    rows = []
    for role_name in _ROLE_ORDER:
        cap = capacities.get(role_name, {"minimum": 0, "maximum": None})
        rows.append({"Role": _ROLE_LABELS[role_name], "Min": cap.get("minimum", 0), "Max": cap.get("maximum")})
    return pd.DataFrame(rows)


def _capacities_from_rows(df: pd.DataFrame) -> dict:
    capacities = {}
    for role_name, (_, row) in zip(_ROLE_ORDER, df.iterrows()):
        maximum = row["Max"]
        capacities[role_name] = {
            "minimum": int(row["Min"]) if pd.notna(row["Min"]) else 0,
            "maximum": None if pd.isna(maximum) else int(maximum),
        }
    return capacities


def _capacity_editor(capacities: dict, key: str) -> dict:
    edited = st.data_editor(
        _capacity_rows(capacities),
        key=key,
        hide_index=True,
        width="stretch",
        disabled=["Role"],
        column_config={
            "Min": st.column_config.NumberColumn(min_value=0, step=1),
            "Max": st.column_config.NumberColumn(min_value=0, step=1, help="Blank = unbounded"),
        },
    )
    return _capacities_from_rows(edited)


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
            cols = st.columns([4, 1])
            building["name"] = cols[0].text_input("Building name", value=building["name"], key=f"bname_{bi}")
            if cols[1].button("Remove building", key=f"remove_building_{bi}"):
                buildings.pop(bi)
                st.rerun()

            st.caption("Building-wide requirements (not tied to one room)")
            building["capacities"] = _capacity_editor(building["capacities"], key=f"bcap_{bi}")

            st.caption("Rooms")
            for ri, room in enumerate(building["rooms"]):
                room_cols = st.columns([4, 1])
                room["name"] = room_cols[0].text_input("Room name", value=room["name"], key=f"rname_{bi}_{ri}")
                if room_cols[1].button("Remove room", key=f"remove_room_{bi}_{ri}"):
                    building["rooms"].pop(ri)
                    st.rerun()
                room["capacities"] = _capacity_editor(room["capacities"], key=f"rcap_{bi}_{ri}")

            with st.form(key=f"add_room_form_{bi}", clear_on_submit=True):
                new_room_name = st.text_input("New room name")
                if st.form_submit_button("+ Add room") and new_room_name:
                    building["rooms"].append({"name": new_room_name, "capacities": {}})
                    st.rerun()

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
