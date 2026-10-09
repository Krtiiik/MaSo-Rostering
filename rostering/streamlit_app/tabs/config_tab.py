"""Tab 2: buildings/rooms/capacities editor."""
from __future__ import annotations

import copy

import streamlit as st

from rostering.domain import Role
from rostering.persistence import config_store
from rostering.webapp import labels, mutations
from rostering.streamlit_app import fix_focus, session, solve_prompt

_ROLE_LABELS = {r.name: r.value for r in Role}
_ROLE_ORDER = [r.name for r in Role]

# Width of one grid column, in rem: room for a number input with its steppers.
_GRID_SHARE_REM = 8

_ADD_ROOM_COL_CSS = """
<style>
div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-add_room_col_"]) {
    align-items: stretch !important;
}
/* The "Remove building" button and the "+ Add room" button live in the
   same stColumn (so they share its exact width and stay aligned with each
   other), with "Remove building" in normal flow at the top and "+ Add
   room" absolutely positioned below it, filling down to the table's
   bottom. It must be absolutely (not flex-grow) positioned: giving it
   height via flex-grow instead resolves against an indefinite ancestor
   height and Chromium falls back to sizing it against the viewport
   instead of the column. Anchoring it with absolute positioning against
   its (now stretched-to-the-table) stColumn parent sidesteps that
   entirely, since an absolutely positioned box's height comes from its
   inset offsets, not from an ancestor's auto height. !important is needed
   throughout because Streamlit's own emotion-cache rules for these same
   elements are injected into <head> after this markdown's <style> tag and
   would otherwise win the cascade on tied specificity. */
div[data-testid="stColumn"]:has(div[class*="st-key-add_room_col_"]) {
    position: relative !important;
}
div[class*="st-key-add_room_col_"] {
    position: absolute !important;
    top: 5rem !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
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
/* This column is narrow (it's the "1" share of the outer ratio), so
   "Remove building" needs to wrap instead of overflowing on one line —
   Streamlit's own button label <p> is styled white-space: nowrap. The
   button has a fixed height (and tight side padding so the label wraps to
   at most two lines even in the narrowest column): "+ Add room" is
   positioned at a fixed offset below it, so a button that grew with its
   wrapped label would run into "+ Add room". */
div[class*="st-key-remove_building_"] button {
    height: 3.5rem !important;
    padding: 0.25rem !important;
}
div[class*="st-key-remove_building_"] button p {
    white-space: normal !important;
    line-height: 1.2 !important;
    font-size: 0.85rem !important;
}
</style>
"""


def _capacity_cell(min_col, capacities: dict, role_name: str, key: str) -> None:
    cap = capacities.get(role_name, {"minimum": 0})
    minimum = min_col.number_input(
        "Počet",
        value=int(cap.get("minimum") or 0),
        min_value=0,
        step=1,
        key=f"{key}_min",
        label_visibility="collapsed",
    )
    capacities[role_name] = {"minimum": int(minimum)}


def _render_building_table(buildings: list[dict], bi: int) -> None:
    building = buildings[bi]
    rooms: list[dict] = building["rooms"]
    n_units = 1 + len(rooms)  # building-wide unit + one per room

    outer = st.columns([1 + n_units, 1])
    with outer[0]:
        building["name"] = st.text_input("Název budovy", value=building["name"], key=f"bname_{bi}")

        counts_cols = st.columns([1, n_units])
        counts_cols[1].markdown("**Počty**", text_alignment="center")

        header_cols = st.columns([1] + [1] * n_units)
        header_cols[0].write("")
        header_cols[1].markdown(f"**{building['name'] or 'Budova'} (celkem)**")
        for ri, room in enumerate(rooms):
            with header_cols[2 + ri]:
                room["name"] = st.text_input(
                    "Název místnosti", value=room["name"], key=f"rname_{bi}_{id(room)}", label_visibility="collapsed"
                )

        for role_name in _ROLE_ORDER:
            row_cols = st.columns([1] + [1] * n_units)
            row_cols[0].write(_ROLE_LABELS[role_name])
            _capacity_cell(row_cols[1], building["capacities"], role_name, key=f"bcap_{bi}_{role_name}")
            for ri, room in enumerate(rooms):
                _capacity_cell(
                    row_cols[2 + ri],
                    room["capacities"],
                    role_name,
                    key=f"rcap_{bi}_{id(room)}_{role_name}",
                )

        remove_cols = st.columns([1] + [1] * n_units)
        remove_cols[0].write("")
        remove_cols[1].write("")
        for ri, room in enumerate(rooms):
            if remove_cols[2 + ri].button("Odebrat místnost", key=f"remove_room_{bi}_{id(room)}", width="stretch"):
                rooms.pop(ri)
                st.rerun()

    with outer[1]:
        st.markdown(_ADD_ROOM_COL_CSS, unsafe_allow_html=True)
        if st.button("Odebrat budovu", key=f"remove_building_{bi}", width="stretch"):
            buildings.pop(bi)
            st.rerun()
        with st.container(key=f"add_room_col_{bi}"):
            if st.button("+ Přidat místnost", key=f"add_room_{bi}", width="stretch"):
                rooms.append({"name": f"Místnost {len(rooms) + 1}", "capacities": {}})
                st.rerun()


def _ensure_drafts(state: dict) -> None:
    st.session_state.setdefault("config_draft", copy.deepcopy(state["config"]))


def _layout_key(buildings: list[dict]) -> list:
    """A building layout reduced to what it means: names and every Role's
    count (an absent capacity counts as 0, as the draft's fields show it)."""

    def caps(capacities: dict) -> dict[str, int]:
        return {r: int((capacities.get(r) or {}).get("minimum") or 0) for r in _ROLE_ORDER}

    return [
        (
            b["name"],
            caps(b.get("capacities") or {}),
            [(r["name"], caps(r.get("capacities") or {})) for r in b.get("rooms") or []],
        )
        for b in buildings
    ]


def has_unsaved_changes(state: dict, buildings: list[dict]) -> bool:
    """Whether the layout drafted on this tab differs from what the open Season has saved."""
    return _layout_key(buildings) != _layout_key(state["config"])


def _save_draft(buildings: list[dict]) -> dict:
    """Save the layout draft to the open Season and make the result the
    session's state. The layout is copied so later edits to the draft never
    reach the saved state through a shared reference."""
    saved = mutations.put_config(session.get_workspace(), copy.deepcopy(buildings))
    session.set_state(saved)
    return saved


_WIDGET_KEY_PREFIXES = ("bname_", "rname_", "bcap_", "rcap_")


def reset_draft_to_bundled() -> None:
    """Replace the layout draft with the bundled default. Nothing is saved: the
    user still saves (or drops) the result like any other edit. The fields'
    widget state is cleared too, or they would keep showing the old values."""
    st.session_state["config_draft"] = config_store.load_bundled_config()
    for key in [k for k in st.session_state if str(k).startswith(_WIDGET_KEY_PREFIXES)]:
        del st.session_state[key]


def clear_drafts() -> None:
    st.session_state.pop("config_draft", None)


def render() -> None:
    st.header(labels.TAB_BUILDINGS)
    st.write("Určete budovy, jejich místnosti a kolik pomocníků v každé roli musí každá z nich v tomto ročníku mít.")

    state = session.get_state()
    _ensure_drafts(state)
    buildings: list[dict] = st.session_state["config_draft"]

    fix = fix_focus.render_callout(state, "buildings")

    for bi, building in enumerate(buildings):
        title = building["name"] or f"Budova {bi + 1}"
        if fix is not None and fix.building == building["name"]:
            title = f"▶ {title}"  # the "Go fix" target
        with st.expander(title, expanded=True):
            # Every column of the grid (the label column, the building-wide
            # unit, one per room, and the button column) is an equal share, so
            # the grid takes a fixed width per share instead of the whole page.
            shares = 1 + 1 + len(building["rooms"]) + 1
            st.markdown(
                f'<style>.st-key-building_grid_{bi} '
                f'{{ width: {shares * _GRID_SHARE_REM}rem; max-width: 100%; }}</style>',
                unsafe_allow_html=True,
            )
            with st.container(key=f"building_grid_{bi}"):
                _render_building_table(buildings, bi)

    if st.button("+ Přidat budovu", key="add_building", width="stretch"):
        # Named afterwards in the building's own "Název budovy" field.
        taken = {b["name"] for b in buildings}
        number = len(buildings) + 1
        while f"Budova {number}" in taken:
            number += 1
        buildings.append({"name": f"Budova {number}", "rooms": [], "capacities": {}})
        st.rerun()

    with st.bottom:
        # Filled in after the buttons ran, so it reflects a save just made.
        unsaved_note = st.empty()
        action_cols = st.columns(3)
        if action_cols[2].button(
            "Obnovit výchozí budovy",
            key="reset_config",
            help="Nahradí rozložení zde výchozím, které je součástí aplikace. Uloží se až kliknutím na Uložit konfiguraci.",
        ):
            reset_draft_to_bundled()
            st.rerun()
        if action_cols[0].button("Uložit konfiguraci", key="save_config"):
            try:
                _save_draft(buildings)
                st.success("Konfigurace uložena.")
            except mutations.RosteringError as exc:
                st.error(str(exc))

        disabled = not state["helpers"]
        if action_cols[1].button("Uložit a sestavit rozdělení", type="primary", disabled=disabled):
            try:
                # Saved first, so the confirmation counts against the new
                # layout (a removed Room drops its locks). Removing a Room that
                # holds a lock is never blocked or prompted here.
                saved = _save_draft(buildings)
            except mutations.RosteringError as exc:
                st.error(str(exc))
            else:
                solve_prompt.request_solve(saved, solve_prompt.solve_and_open_roster)
        if disabled:
            st.caption("Nejdřív nahrajte odpovědi pomocníků.")
        if has_unsaved_changes(session.get_state(), buildings):
            unsaved_note.caption(
                "⚠ Neuložené změny: rozložení zde se uloží, až kliknete na Uložit konfiguraci "
                "(nebo Uložit a sestavit rozdělení). Znovunačtení stránky je zahodí."
            )
