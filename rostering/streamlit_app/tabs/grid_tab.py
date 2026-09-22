"""Tab 3: the drag-and-drop assignment grid, including the manual
structural/overlay roles (see CLAUDE.md "Out-of-solver roles") rendered as
extra, non-droppable rows in the same grid rather than as a separate
section below it."""
from __future__ import annotations

import streamlit as st

from rostering.domain import OverlayRole, Preference, Role, StructuralRole, normalize_name
from rostering.streamlit_app import mutations, session
from rostering_assignment_grid import assignment_grid

_ROLE_ORDER = [r.name for r in Role]
_ROLE_LABELS = {r.name: r.value for r in Role}

# Manual rows before the solved roles (building leadership, then room leads)
# and after them (before/after-event overlay duties, then tech support) —
# ordering follows the season's historical hand-built roster layout.
_MANUAL_ROWS_BEFORE = [
    (StructuralRole.VedouciBudovy, "building"),
    (StructuralRole.PravaRuka, "building"),
    (StructuralRole.VedouciMistnosti, "room"),
]
_MANUAL_ROWS_AFTER = [
    (OverlayRole.UvadeciPredavaniCen, "global"),
    (OverlayRole.Registrace, "global"),
    (StructuralRole.TechnickaPodpora, "building"),
]
_STRUCTURAL_ROLE_NAMES = {r.name for r in StructuralRole}

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


def _grid_rows() -> list[dict]:
    rows = [
        {"kind": "manual", "key": role.name, "label": role.value, "scope": scope}
        for role, scope in _MANUAL_ROWS_BEFORE
    ]
    rows += [
        {
            "kind": "role",
            "key": name,
            "label": _ROLE_LABELS[name],
            # Záloha is a solver-only overflow role, never offered as a
            # choice on the form — excluded from the hover card's
            # role-preference list (see CLAUDE.md).
            "preferenceable": name != Role.Zaloha.name,
        }
        for name in _ROLE_ORDER
    ]
    rows += [
        {"kind": "manual", "key": role.name, "label": role.value, "scope": scope}
        for role, scope in _MANUAL_ROWS_AFTER
    ]
    return rows


def _manual_display_name(entry: dict, helper_names: dict[int, str]) -> str:
    helper_id = entry.get("helper_id")
    if helper_id is not None:
        return helper_names.get(helper_id, f"#{helper_id}")
    return entry.get("helper_name") or ""


def _manual_entries(state: dict) -> list[dict]:
    manual = state["manual_roles"]
    helper_names = _helper_options(state)
    entries = []
    for s in manual["structural"]:
        entries.append(
            {
                "key": s["role"],
                "building": s["building"],
                "room": s.get("room"),
                "helper_id": s.get("helper_id"),
                "name": _manual_display_name(s, helper_names),
            }
        )
    for o in manual["overlay"]:
        entries.append(
            {
                "key": o["role"],
                "building": None,
                "room": None,
                "helper_id": o.get("helper_id"),
                "name": _manual_display_name(o, helper_names),
            }
        )
    return [e for e in entries if e["name"]]


def _resolve_manual_name(state: dict, name: str) -> dict:
    """Resolve a hand-typed name to a registered helper (matched
    diacritics/whitespace-insensitively, like the rest of ingestion), or
    keep it as a free-text name for someone unregistered."""
    norm = normalize_name(name)
    for h in state["helpers"]:
        if normalize_name(h["name"]) == norm:
            return {"helper_id": h["id"], "helper_name": None}
    return {"helper_id": None, "helper_name": name}


def _apply_manual_set(state: dict, event: dict) -> dict:
    key = event["key"]
    building = event.get("building")
    room = event.get("room")
    names = [n.strip() for n in event.get("names", []) if n and n.strip()]
    manual = state["manual_roles"]
    resolved = [_resolve_manual_name(state, n) for n in names]

    if key in _STRUCTURAL_ROLE_NAMES:
        filtered = [
            s
            for s in manual["structural"]
            if not (s["role"] == key and s["building"] == building and s.get("room") == room)
        ]
        new_entries = [{"role": key, "building": building, "room": room, **r} for r in resolved]
        return {**manual, "structural": filtered + new_entries}

    other = [o for o in manual["overlay"] if o["role"] != key]
    new_entries = [{"role": key, **r} for r in resolved]
    return {**manual, "overlay": other + new_entries}


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
        rows=_grid_rows(),
        helpers=grid_helpers,
        assignments=state["assignments"],
        manual_entries=_manual_entries(state),
        helper_names=sorted({h["name"] for h in state["helpers"]}, key=str.lower),
        key="assignment_grid",
    )
    if event:
        # CCv2 triggers reset automatically after the rerun that reports
        # them, so no dedup bookkeeping is needed here.
        try:
            if event["type"] == "drop":
                session.set_state(
                    mutations.move_helper(
                        session.get_workspace(), event["helper_id"], event["building"], event["room"], event["role"]
                    )
                )
            else:
                next_manual = _apply_manual_set(state, event)
                session.set_state(mutations.put_manual_roles(session.get_workspace(), next_manual))
        except mutations.RosteringError as exc:
            st.error(str(exc))
        st.rerun()
