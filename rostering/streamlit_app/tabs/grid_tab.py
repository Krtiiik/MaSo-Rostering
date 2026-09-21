"""Tab 3: the drag-and-drop assignment grid plus manual structural/overlay roles."""
from __future__ import annotations

import streamlit as st

from rostering.domain import OverlayRole, Preference, Role, StructuralRole
from rostering.streamlit_app import mutations, session
from rostering_assignment_grid import assignment_grid

_ROLE_ORDER = [r.name for r in Role]
_ROLE_LABELS = {r.name: r.value for r in Role}
_STRUCTURAL_BUILDING_ROLES = [StructuralRole.VedouciBudovy, StructuralRole.PravaRuka, StructuralRole.TechnickaPodpora]
_OVERLAY_ROLES = list(OverlayRole)

# Czech wording as shown on the registration form (see
# rostering.ingest.preferences), for display in the roster grid's helper
# hover card — not to be confused with Preference's member names, which are
# ASCII-normalized identifiers rather than display text.
_PREFERENCE_LABELS = {
    Preference.Ano.name: "Ano",
    Preference.Klidne.name: "Klidně",
    Preference.Nevadi.name: "Nevadí",
    Preference.Spise_ne.name: "Spíš ne",
    Preference.Ne.name: "Ne",
}


def _grid_role_preferences(role_preferences: dict[str, str]) -> dict[str, dict[str, object]]:
    return {
        role: {"level": Preference[pref].value, "label": _PREFERENCE_LABELS[pref]}
        for role, pref in role_preferences.items()
    }


def _flatten_rooms(config: list[dict]) -> list[dict]:
    return [{"building": b["name"], "room": r["name"]} for b in config for r in b["rooms"]]


def _helper_options(state: dict) -> dict[int, str]:
    return {h["id"]: h["name"] for h in state["helpers"]}


def _structural_helper_id(manual: dict, role: StructuralRole, building: str, room: str | None) -> int | None:
    for s in manual["structural"]:
        if s["role"] == role.name and s["building"] == building and s.get("room") == room:
            return s["helper_id"]
    return None


def _set_structural(manual: dict, role: StructuralRole, building: str, room: str | None, helper_id: int | None) -> dict:
    filtered = [
        s
        for s in manual["structural"]
        if not (s["role"] == role.name and s["building"] == building and s.get("room") == room)
    ]
    if helper_id is not None:
        filtered.append({"role": role.name, "building": building, "room": room, "helper_id": helper_id})
    return {**manual, "structural": filtered}


def _overlay_helper_ids(manual: dict, role: OverlayRole) -> list[int]:
    return [o["helper_id"] for o in manual["overlay"] if o["role"] == role.name]


def render() -> None:
    st.header("3. Roster")
    state = session.get_state()
    rooms = _flatten_rooms(state["config"])

    if not rooms:
        st.info("Configure at least one building with a room first.")
        return

    with st.bottom:
        cols = st.columns(2)
        if cols[0].button("Re-solve" if state["assignments"] else "Solve", type="primary"):
            with st.spinner("Solving…"):
                try:
                    session.set_state(mutations.solve(session.get_workspace()))
                    st.rerun()
                except mutations.RosteringError as exc:
                    st.error(str(exc))

        if state["assignments"]:
            try:
                export_bytes = mutations.export_xlsx_bytes(session.get_workspace())
                cols[1].download_button(
                    "Export to Excel",
                    data=export_bytes,
                    file_name="roster.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except mutations.RosteringError:
                pass

    diagnostics = state["diagnostics"]
    if diagnostics["status"]:
        unsatisfied = len(diagnostics["unsatisfied_friend_pairs"])
        parts = [f"Status: {diagnostics['status']}"]
        if diagnostics["objective_value"] is not None:
            parts.append(f"objective {diagnostics['objective_value']}")
        parts.append(f"{unsatisfied} unsatisfied friend request(s)")
        st.caption(" · ".join(parts))

    grid_helpers = [
        {
            "id": h["id"],
            "name": h["name"],
            "can_bring_notebook": h["can_bring_notebook"],
            "can_bring_camera": h["can_bring_camera"],
            "role_preferences": _grid_role_preferences(h["role_preferences"]),
            "building_preferences": h["building_preferences"],
            "friends": h["friends"],
        }
        for h in state["helpers"]
    ]

    event = assignment_grid(
        rooms=rooms,
        roles=_ROLE_ORDER,
        role_labels=_ROLE_LABELS,
        helpers=grid_helpers,
        assignments=state["assignments"],
        unsatisfied_friend_pairs=diagnostics["unsatisfied_friend_pairs"],
        satisfied_friend_pairs=diagnostics.get("satisfied_friend_pairs", []),
        key="assignment_grid",
    )
    if event:
        # CCv2 triggers reset automatically after the rerun that reports
        # them, so no dedup bookkeeping is needed here.
        try:
            session.set_state(
                mutations.move_helper(
                    session.get_workspace(), event["helper_id"], event["building"], event["room"], event["role"]
                )
            )
        except mutations.RosteringError as exc:
            st.error(str(exc))
        st.rerun()

    _render_manual_roles(state, rooms)


def _render_manual_roles(state: dict, rooms: list[dict]) -> None:
    st.subheader("Manual roles")
    manual = state["manual_roles"]
    helper_names = _helper_options(state)
    buildings = [b["name"] for b in state["config"] if b["rooms"]]

    for role in _STRUCTURAL_BUILDING_ROLES:
        st.caption(role.value)
        cols = st.columns(len(buildings)) if buildings else []
        for col, building in zip(cols, buildings):
            current = _structural_helper_id(manual, role, building, None)
            chosen = col.selectbox(
                building,
                options=[None] + list(helper_names),
                index=([None] + list(helper_names)).index(current) if current in helper_names else 0,
                format_func=lambda hid: "—" if hid is None else helper_names.get(hid, f"#{hid}"),
                key=f"struct_{role.name}_{building}",
            )
            if chosen != current:
                session.set_state(
                    mutations.put_manual_roles(
                        session.get_workspace(), _set_structural(manual, role, building, None, chosen)
                    )
                )
                st.rerun()

    st.caption(StructuralRole.VedouciMistnosti.value)
    room_cols = st.columns(len(rooms)) if rooms else []
    for col, r in zip(room_cols, rooms):
        current = _structural_helper_id(manual, StructuralRole.VedouciMistnosti, r["building"], r["room"])
        options = [None] + list(helper_names)
        chosen = col.selectbox(
            r["room"],
            options=options,
            index=options.index(current) if current in helper_names else 0,
            format_func=lambda hid: "—" if hid is None else helper_names.get(hid, f"#{hid}"),
            key=f"struct_leads_{r['building']}_{r['room']}",
        )
        if chosen != current:
            session.set_state(
                mutations.put_manual_roles(
                    session.get_workspace(),
                    _set_structural(manual, StructuralRole.VedouciMistnosti, r["building"], r["room"], chosen),
                )
            )
            st.rerun()

    for role in _OVERLAY_ROLES:
        current_ids = _overlay_helper_ids(manual, role)
        chosen_ids = st.multiselect(
            role.value,
            options=list(helper_names),
            default=current_ids,
            format_func=lambda hid: helper_names.get(hid, f"#{hid}"),
            key=f"overlay_{role.name}",
        )
        if set(chosen_ids) != set(current_ids):
            other_entries = [o for o in manual["overlay"] if o["role"] != role.name]
            next_manual = {
                **manual,
                "overlay": other_entries + [{"role": role.name, "helper_id": hid} for hid in chosen_ids],
            }
            session.set_state(mutations.put_manual_roles(session.get_workspace(), next_manual))
            st.rerun()
