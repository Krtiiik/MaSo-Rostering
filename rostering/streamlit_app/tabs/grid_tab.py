"""Tab 3: the drag-and-drop assignment grid, including the manual
structural/overlay roles (see CLAUDE.md "Out-of-solver roles") rendered as
extra rows in the same grid rather than as a separate section below it. A
manual row's names are added by clicking its cell; the Organizer rows also take
a dragged Organizer chip (never a Helper's). The overlay roles
(UvadeciUcastniku, FoceniPredavaniCen: room-scoped; Registrace:
building-scoped) additionally
accept dropping a helper's existing chip onto the cell for their own
room/building, to duplicate them into that overlay slot without moving
their solved assignment.

The grid's columns are always one per physical room — adjacent rooms are
never merged at the column-layout level. Instead, any *one row* (a solved
role, or a room-scoped manual role) can merge two or more of its own
adjacent cells into one wider cell, like merging cells within a single
spreadsheet row/Excel row (see CLAUDE.md "Out-of-solver roles" and
rostering.domain.group_adjacent_rooms) — every other row for those same
rooms is unaffected. Purely a display/export grouping; the underlying
per-helper room assignment is untouched either way."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import streamlit as st

from rostering import tags as tag_tree
from rostering import organizers as organizer_slots
from rostering.domain import BrokenRule, OverlayRole, Preference, Role, StructuralRole, normalize_name
from rostering.czech import plural
from rostering.ingest.mapping import building_keys
from rostering.streamlit_app import fix_focus, labels, mutations, session, solve_prompt
from rostering.streamlit_app.reveal import reveal_in_file_manager
from rostering.streamlit_app.tabs import upload_summary_ui
from rostering_assignment_grid import assignment_grid

_ROLE_ORDER = [r.name for r in Role]
_ROLE_LABELS = {r.name: r.value for r in Role}

# Manual rows before the solved roles (building leadership, then room leads)
# and after them (before/after-event overlay duties, then tech support) —
# ordering follows the season's historical hand-built roster layout. Pravá
# ruka (the building lead's deputy) is scoped per room, not per building —
# each room can have its own deputy. Each entry is (role, scope,
# allow_duplicate_drop); allow_duplicate_drop marks overlay roles that
# accept dragging a helper's existing chip onto the cell for their own room
# (scope "room") or building (scope "building") to duplicate them into that
# overlay slot (without moving their solved assignment) in addition to
# typing a name.
_MANUAL_ROWS_BEFORE = [
    (StructuralRole.VedouciBudovy, "building", False),
    (StructuralRole.PravaRuka, "room", False),
    (StructuralRole.VedouciMistnosti, "room", False),
]
_MANUAL_ROWS_AFTER = [
    (OverlayRole.UvadeciUcastniku, "room", True),
    (OverlayRole.FoceniPredavaniCen, "room", True),
    (OverlayRole.Registrace, "building", True),
    (StructuralRole.TechnickaPodpora, "building", False),
]
_STRUCTURAL_ROLE_NAMES = {r.name for r in StructuralRole}

# The four leadership slots (structural roles) hold only a tracked Organizer,
# never a Helper: their cell input autocompletes against the Season's
# Organizers (`organizer_names`), and a name nobody tracks creates an Organizer
# on the spot (mutations.set_slot_holders). Three of them are single-holder
# roles (one building lead, one deputy, one lead per room), so their cells cap
# at one name rather than the multi-name lists Technická podpora and the
# overlay roles allow.
_SINGLE_HOLDER_ROLE_NAMES = {r.name for r in organizer_slots.SINGLE_HOLDER_ROLES}

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


def _acceptable_buildings(building_preferences: list[str], config: list[dict]) -> list[str]:
    """The Season's Buildings a Helper's Building preference accepts (see
    CONTEXT.md "Building preference"): every one when the set is empty, else those
    matching an entry the way the solver matches them."""
    if not building_preferences:
        return [b["name"] for b in config]
    wanted = frozenset().union(*(building_keys(p) for p in building_preferences))
    return [b["name"] for b in config if not building_keys(b["name"]).isdisjoint(wanted)]


def _flatten_rooms(config: list[dict]) -> list[dict]:
    return [{"building": b["name"], "room": r["name"]} for b in config for r in b["rooms"]]


def _helper_options(state: dict) -> dict[int, str]:
    return {h["id"]: h["name"] for h in state["helpers"]}


def _grid_rows() -> list[dict]:
    def manual_row(role, scope: str, allow_duplicate_drop: bool) -> dict:
        return {
            "kind": "manual",
            "key": role.name,
            "label": role.value,
            "scope": scope,
            "organizer": role.name in _STRUCTURAL_ROLE_NAMES,
            "single_entry": role.name in _SINGLE_HOLDER_ROLE_NAMES,
            "allowDuplicateDrop": allow_duplicate_drop,
        }

    rows = [manual_row(role, scope, allow_drop) for role, scope, allow_drop in _MANUAL_ROWS_BEFORE]
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
    rows += [manual_row(role, scope, allow_drop) for role, scope, allow_drop in _MANUAL_ROWS_AFTER]
    return rows


def _manual_display_name(entry: dict, helper_names: dict[int, str]) -> str:
    helper_id = entry.get("helper_id")
    if helper_id is not None:
        return helper_names.get(helper_id, f"#{helper_id}")
    return entry.get("helper_name") or ""


def _manual_entries(
    state: dict,
    organizer_pills: dict[int, dict] | None = None,
    dimmed_organizer_ids: Sequence[int] = (),
    organizer_broken: dict[int, list[str]] | None = None,
) -> list[dict]:
    """The grid's manual-role entries. An Organizer's entry also carries their Tag
    pills, whether the Tag filter dims them and the Broken-rule lines their
    placement is part of, like a Helper's chip does."""
    manual = state["manual_roles"]
    helper_names = _helper_options(state)
    organizer_names = {o["id"]: o["name"] for o in state["organizers"]}
    entries = []
    for s in manual["structural"]:
        organizer_id = s.get("organizer_id")
        entries.append(
            {
                "key": s["role"],
                "building": s["building"],
                "room": s.get("room"),
                "helper_id": s.get("helper_id"),
                "organizer_id": organizer_id,
                # An entry saved before Organizers existed (a Helper or typed
                # text) is shown, marked, until it is replaced.
                "legacy": organizer_id is None,
                "name": organizer_names.get(organizer_id, f"#{organizer_id}")
                if organizer_id is not None
                else _manual_display_name(s, helper_names),
                **(
                    {
                        "tags": (organizer_pills or {}).get(organizer_id),
                        "dimmed": organizer_id in dimmed_organizer_ids,
                        "broken": (organizer_broken or {}).get(organizer_id, []),
                    }
                    if organizer_id is not None
                    else {}
                ),
            }
        )
    for o in manual["overlay"]:
        entries.append(
            {
                "key": o["role"],
                "building": o.get("building"),
                "room": o.get("room"),
                "helper_id": o.get("helper_id"),
                "name": _manual_display_name(o, helper_names),
            }
        )
    return [e for e in entries if e["name"]]


def _grid_organizers(
    state: dict,
    organizer_pills: dict[int, dict],
    dimmed_organizer_ids: Sequence[int],
    organizer_broken: dict[int, list[str]],
) -> list[dict]:
    """The Organizers who attend, for the grid's draggable chips: `placed` says
    whether they hold a slot (an unplaced one waits in the Nezařazení area)."""
    return [
        {
            "id": o["id"],
            "name": o["name"],
            "placed": o.get("building") is not None,
            "tags": organizer_pills.get(o["id"]),
            "dimmed": o["id"] in dimmed_organizer_ids,
            "broken": organizer_broken.get(o["id"], []),
        }
        for o in state["organizers"]
        if not o.get("cant_attend")
    ]


def _resolve_manual_name(state: dict, name: str) -> dict:
    """Resolve a hand-typed name to a registered helper (matched
    diacritics/whitespace-insensitively, like the rest of ingestion), or
    keep it as a free-text name for someone unregistered."""
    norm = normalize_name(name)
    for h in state["helpers"]:
        # A Helper who can't attend is not on the roster, so their name is not
        # matched: it stays free text rather than pointing a role at them.
        if not h.get("cant_attend") and normalize_name(h["name"]) == norm:
            return {"helper_id": h["id"], "helper_name": None}
    return {"helper_id": None, "helper_name": name}


def _apply_overlay_set(state: dict, event: dict) -> dict:
    """The Manual roles after an edit of an Additional role cell (Helper-only:
    a typed name is resolved to a registered Helper or kept as free text). The
    leadership slots take Organizers instead, see mutations.set_slot_holders."""
    key = event["key"]
    building = event.get("building")
    room = event.get("room")
    names = [n.strip() for n in event.get("names", []) if n and n.strip()]
    manual = state["manual_roles"]
    resolved = [_resolve_manual_name(state, n) for n in names]

    # Overlay roles are either building-scoped (room None, e.g. Registrace)
    # or room-scoped (UvadeciUcastniku/FoceniPredavaniCen) — filtered/replaced
    # by (role, building, room).
    other = [
        o
        for o in manual["overlay"]
        if not (o["role"] == key and o.get("building") == building and o.get("room") == room)
    ]
    new_entries = [{"role": key, "building": building, "room": room, **r} for r in resolved]
    return {**manual, "overlay": other + new_entries}


_TOAST_KEY = "_move_toast"
_PLACED_KEY = "_placed_new_note"
_EXPORT_PATH_KEY = "_exported_roster_path"
_EXPORT_ERROR_KEY = "_export_error"


def _save_export_to_season() -> None:
    """Export button callback: write the roster into the open Season's folder."""
    try:
        path = mutations.save_export_to_season(session.get_workspace())
    except mutations.RosteringError as exc:
        st.session_state[_EXPORT_ERROR_KEY] = str(exc)
    else:
        st.session_state[_EXPORT_PATH_KEY] = str(path)


def _render_export_note() -> None:
    """Where the last export went, with a button revealing it in the file
    manager; shown while that file is still the open Season's export."""
    error = st.session_state.pop(_EXPORT_ERROR_KEY, None)
    if error:
        st.error(error)
    saved = st.session_state.get(_EXPORT_PATH_KEY)
    if not saved:
        return
    path = Path(saved)
    if not path.is_file() or path.parent != session.get_workspace().open_season_dir():
        st.session_state.pop(_EXPORT_PATH_KEY, None)
        return
    note, reveal = st.columns([5, 1], vertical_alignment="center")
    note.success(f"Rozdělení uloženo do {path}", icon="✅")
    if reveal.button("Zobrazit ve složce", key="_reveal_export"):
        reveal_in_file_manager(path)


def _apply_drop(event: dict, confirmed: bool) -> None:
    """Place the dropped Helper. Never refused, whatever it breaks; the toast
    only names what this drop newly broke (minimums excepted). Raises
    ``ConfirmationRequired`` (nothing changed) while ``confirmed`` is off and
    the move would take the Helper out of an Additional role."""
    before = session.get_state()
    moved = mutations.move_helper(
        session.get_workspace(), event["helper_id"], event["building"], event["room"], event["role"], confirmed=confirmed
    )
    session.set_state(moved)
    toast_lines = mutations.move_toast_lines(before, moved)
    if toast_lines:
        st.session_state[_TOAST_KEY] = toast_lines


@st.dialog("Odebrat pomocníka z manuální role?")
def _confirm_drop(event: dict, state: dict, lines: list[str]) -> None:
    name = next((h["name"] for h in state["helpers"] if h["id"] == event["helper_id"]), "pomocník")
    st.write(f"Přesunutím pomocníka **{name}** do jiné místnosti se odebere z:")
    for line in lines:
        st.markdown(f"- {line}")
    st.caption("Nelze vrátit zpět; do role je třeba ho případně znovu zapsat.")
    cols = st.columns(2)
    if cols[0].button("Přesunout a odebrat", type="primary", key="drop_confirm_go"):
        try:
            _apply_drop(event, confirmed=True)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        st.rerun()
    if cols[1].button("Zrušit", key="drop_confirm_cancel"):
        st.rerun()

# How the Broken-rule banner names each rule family, in tier order. A family
# not listed (added later through rostering.solver.rules.register_rule_family)
# falls back to its own name.
_FAMILY_LABELS = {
    "minimums": "Počty v místnostech a budovách",
    "tag_restrictions": "Omezení štítků",
    "forced_friends": "Vynucené skupinky kamarádů",
    "equipment": "Vybavení",
}

# A family with more broken instances than this collapses into an expandable
# summary so the banner never becomes a wall of text.
_COLLAPSE_ABOVE = 10


def _render_broken_line(broken: BrokenRule) -> None:
    cols = st.columns([9, 1], vertical_alignment="center")
    cols[0].markdown(f"- {broken.line}")
    if fix_focus.can_go_fix(broken):
        key = f"go_fix_{broken.instance.kind}_{'_'.join(map(str, broken.instance.entity))}"
        if cols[1].button("Opravit", key=key):
            fix_focus.go_fix(broken)
            st.rerun()


def _render_broken_banner(broken_rules: list[BrokenRule], has_roster: bool) -> None:
    """The warning banner above the grid: one line per broken rule instance,
    grouped by family (in the order the rules bend), each with a "Go fix"
    button; a family above about ten instances collapses into an expander."""
    if not broken_rules:
        if has_roster:
            st.caption("✓ Žádná porušená pravidla")
        return
    by_family: dict[str, list[BrokenRule]] = {}
    for broken in broken_rules:
        by_family.setdefault(broken.family, []).append(broken)
    with st.container(border=True):
        st.markdown(
            f"**⚠ {len(broken_rules)} "
            + plural(len(broken_rules), "porušené pravidlo", "porušená pravidla", "porušených pravidel")
            + "**"
        )
        for family, instances in by_family.items():
            label = _FAMILY_LABELS.get(family, family)
            if len(instances) > _COLLAPSE_ABOVE:
                with st.expander(f"{label}: porušeno {len(instances)}"):
                    for broken in instances:
                        _render_broken_line(broken)
            else:
                st.caption(label)
                for broken in instances:
                    _render_broken_line(broken)


# Session-state keys of the grid's controls (dropped when another Season opens,
# see session.workspace_replaced): the Overlays pills, the Tag filter's Tag ids
# and its all-of / any-of mode. The filter only dims; it never hides.
OVERLAYS_KEY = "_grid_overlays"
TAG_FILTER_KEY = "_grid_tag_filter"
TAG_MODE_KEY = "_grid_tag_mode"
_MODE_LABELS = {tag_tree.ALL_OF: "Všechny", tag_tree.ANY_OF: "Kterýkoli"}

# The decorations the Overlays pills switch on, key -> label. The keys are what
# the grid component receives (``overlays``); a new overlay (Buildings, Roles)
# is an entry here plus its drawing in the component. Friends is on to begin
# with, as friend highlighting always was.
OVERLAYS = {
    "friends": "Kamarádi",
    "tags": "Štítky",
    "role_fit": "Spokojenost s rolí",
    "building_fit": "Spokojenost s budovou",
}
DEFAULT_OVERLAYS = ["friends"]
TAGS_OVERLAY = "tags"


def _render_overlay_controls(state: dict) -> tuple[list[str], list[int], str]:
    """The Overlays pills above the grid and, while the Tags overlay is on, the
    Tag filter; returns ``(overlays, filter_tag_ids, mode)``. With Tags off the
    filter is hidden and dims no one."""
    selected = st.pills(
        "Zobrazení",
        list(OVERLAYS),
        selection_mode="multi",
        default=DEFAULT_OVERLAYS,
        format_func=OVERLAYS.__getitem__,
        key=OVERLAYS_KEY,
        help=(
            "Kamarádi: zvýrazní přání být s kamarádem. Štítky: obarví blok každého člověka podle jeho štítků. "
            "Spokojenost s rolí: svislý okraj vlevo, zelený = role mu nevadí nebo ji chce, červený = spíš ne nebo ne. "
            "Spokojenost s budovou: vodorovný okraj nahoře, zelený = je v některé z přijatelných budov, červený = není."
        ),
    )
    overlays = [key for key in OVERLAYS if key in (selected or [])]
    if TAGS_OVERLAY not in overlays:
        return overlays, [], tag_tree.ALL_OF
    chosen, mode = _render_tag_filter(state)
    return overlays, chosen, mode


def _render_tag_filter(state: dict) -> tuple[list[int], str]:
    """The Tag filter (Tags overlay only); returns ``(filter_tag_ids, mode)``."""
    tags = state.get("tags") or []
    known = {t["id"] for t in tags}
    # A Tag deleted (or a Season swapped) since the filter was chosen.
    if TAG_FILTER_KEY in st.session_state:
        st.session_state[TAG_FILTER_KEY] = [t for t in st.session_state[TAG_FILTER_KEY] if t in known]
    names = {t["id"]: t["name"] for t in tags}
    ordered = [t.id for t, _ in tag_tree.tree_order([tag_tree.tag_from_dict(t) for t in tags])]
    filter_col, mode_col = st.columns([8, 3], vertical_alignment="bottom")
    chosen = filter_col.multiselect(
        "Filtrovat podle štítků",
        ordered,
        format_func=names.__getitem__,
        key=TAG_FILTER_KEY,
        placeholder="Ztlumit pomocníky bez těchto štítků" if tags else "Zatím žádné štítky",
        disabled=not tags,
        help="Pomocníci a organizátoři, kteří neodpovídají, se ztlumí, nikdy nezmizí. Odvozené štítky se počítají.",
    )
    mode = mode_col.radio(
        "Shoda",
        list(_MODE_LABELS),
        format_func=_MODE_LABELS.__getitem__,
        key=TAG_MODE_KEY,
        horizontal=True,
        disabled=not tags,
    )
    return chosen, mode


def render() -> None:
    st.header(labels.TAB_ROSTER)
    state = session.get_state()
    rooms = _flatten_rooms(state["config"])
    upload_summary_ui.render("roster")

    if not rooms:
        st.info("Nejdřív nastavte alespoň jednu budovu s místností.")
        return

    locked = mutations.locked_count(state)

    def run_place_new() -> None:
        newcomers = len(mutations.unplaced_helpers(state))
        placed = mutations.place_new_registrants(session.get_workspace())
        session.set_state(placed)
        solve_prompt.remember_dropped_locks(placed)
        noun = plural(newcomers, "nového zájemce", "nové zájemce", "nových zájemců")
        st.session_state[_PLACED_KEY] = f"Zařazeno: {newcomers} {noun}; všichni ostatní zůstali, kde byli."

    def run_clear() -> None:
        session.set_state(mutations.clear_roster(session.get_workspace()))
        st.rerun()

    stale = mutations.stale_reasons(state)
    unplaced = mutations.unplaced_reason(state)
    blockers = mutations.export_blockers(state)
    with st.bottom:
        if stale:
            # Right above the Solve button: what made the roster stale, and that
            # Solving is what clears it.
            st.warning(
                "**Rozdělení pomocníků je neaktuální:** " + "; ".join(stale) + ". Sestavte rozdělení znovu; do té doby je export zablokovaný.",
                icon="⚠️",
            )
        if unplaced:
            # Registrants nobody has placed yet (e.g. new in a re-upload): drag
            # them into the grid from the Unassigned pool, place only them, or Solve.
            st.warning(
                f"**{unplaced}.** Přetáhněte je do mřížky z oblasti Nezařazení, použijte Zařadit nové registrované "
                "(všichni zařazení zůstanou na místě), nebo sestavte rozdělení; export je zablokovaný, dokud nejsou všichni zařazeni.",
                icon="⚠️",
            )
        cols = st.columns([2, 2, 2, 2, 2, 1, 2], vertical_alignment="center")
        solve_label = (
            f"Sestavit rozdělení (zachová uzamčených: {locked})"
            if locked
            else ("Sestavit znovu" if state["assignments"] else "Sestavit rozdělení")
        )
        if cols[0].button(solve_label, type="primary"):
            solve_prompt.request_solve(state, solve_prompt.run_solve)

        # Solves only the unassigned with every placed Assignment held fixed, so
        # no confirmation is needed: nothing placed can be lost. Touches no lock.
        if cols[1].button(
            "Zařadit nové registrované",
            disabled=not unplaced,
            help="Zařadí jen nezařazené pomocníky; všichni už zařazení zůstanou přesně tam, kde jsou.",
        ):
            solve_prompt.request_place(run_place_new)

        # Bulk lock management; single locks are set on the chips themselves.
        if cols[2].button("Uzamknout všechny zařazené", disabled=not state["assignments"] or locked == len(state["assignments"])):
            session.set_state(mutations.lock_all_placed(session.get_workspace()))
            st.rerun()
        if cols[3].button("Zrušit všechny zámky", disabled=not locked):
            session.set_state(mutations.clear_all_locks(session.get_workspace()))
            st.rerun()
        if cols[4].button(
            "Vymazat rozdělení",
            disabled=not state["assignments"],
            help="Odstraní všechna přiřazení (i uzamčená) a vynuluje výsledek řešení.",
        ):
            solve_prompt.request_clear(state, run_clear)
        cols[5].markdown(f"**{locked}** uzamčeno")

        if state["assignments"] and blockers:
            cols[6].button("Export do Excelu", disabled=True, help="Export je zablokovaný: " + "; ".join(blockers))
        elif state["assignments"]:
            cols[6].button(
                "Export do Excelu",
                on_click=_save_export_to_season,
                help="Uloží rozdělení do složky sezóny (přepíše předchozí export).",
            )
    _render_export_note()

    solve_prompt.show_dropped_locks()
    placed_note = st.session_state.pop(_PLACED_KEY, None)
    if placed_note:
        st.success(placed_note, icon="✅")

    # The toast for the previous run's drop (emitted after the rerun that
    # follows it, since a toast issued right before st.rerun() can be lost).
    for line in st.session_state.pop(_TOAST_KEY, []):
        st.toast(line, icon="⚠️")

    # Judged live against the roster as it stands, on every render; never
    # stored.
    broken_rules = mutations.broken_rules(state)
    _render_broken_banner(broken_rules, has_roster=bool(state["assignments"]))

    # Helpers flagged Can't attend are not on the roster at all: not in the
    # grid, not in the Unassigned pool, not in the name suggestions, and a
    # friend request naming one is simply not shown.
    attending = [h for h in state["helpers"] if not h.get("cant_attend")]
    absent_ids = {h["id"] for h in state["helpers"] if h.get("cant_attend")}
    overlays, filter_tags, filter_mode = _render_overlay_controls(state)
    helper_pills = mutations.grid_tag_pills(state)
    answers_changed = mutations.answers_changed_since_placed(state)
    forced_marks = mutations.grid_forced_groups(state)
    broken_marks = mutations.broken_rule_marks(broken_rules)
    organizer_broken: dict[int, list[str]] = {}
    for mark in broken_marks["organizers"]:
        organizer_broken.setdefault(mark["organizer_id"], []).append(mark["line"])
    dimmed_organizers = mutations.dimmed_organizer_ids(state, filter_tags, filter_mode)
    grid_helpers = [
        {
            "id": h["id"],
            "name": h["name"],
            "tags": helper_pills[h["id"]],
            "answers_changed": [labels.answer_label(a) for a in answers_changed.get(h["id"], [])],
            "forced_groups": forced_marks.get(h["id"], []),
            "can_bring_notebook": h["can_bring_notebook"],
            "can_bring_camera": h["can_bring_camera"],
            "role_preferences": _grid_role_preferences(h["role_preferences"]),
            "building_preferences": h["building_preferences"],
            "acceptable_buildings": _acceptable_buildings(h["building_preferences"], state["config"]),
            # The grid draws Helper-to-Helper requests only; a request toward an
            # Organizer (a {"organizer_id": n} reference) is not shown.
            "friends": [f for f in h["friends"] if isinstance(f, int) and f not in absent_ids],
        }
        for h in attending
    ]

    event = assignment_grid(
        rooms=rooms,
        rows=_grid_rows(),
        helpers=grid_helpers,
        assignments=state["assignments"],
        manual_entries=_manual_entries(
            state,
            mutations.organizer_tag_pills(state),
            dimmed_organizers,
            organizer_broken,
        ),
        cell_merges=state.get("cell_merges", {}),
        helper_names=sorted({h["name"] for h in attending}, key=str.lower),
        # An Organizer who can't attend is not offered for a slot.
        organizer_names=sorted({o["name"] for o in state["organizers"] if not o.get("cant_attend")}, key=str.lower),
        organizers=_grid_organizers(state, mutations.organizer_tag_pills(state), dimmed_organizers, organizer_broken),
        broken_marks=broken_marks,
        overlays=overlays,
        dimmed_helper_ids=mutations.dimmed_helper_ids(state, filter_tags, filter_mode),
        key="assignment_grid",
    )
    if event:
        # CCv2 triggers reset automatically after the rerun that reports
        # them, so no dedup bookkeeping is needed here.
        try:
            if event["type"] == "drop":
                try:
                    _apply_drop(event, confirmed=False)
                except mutations.ConfirmationRequired as exc:
                    # Leaving a Room takes the Helper out of the Additional roles
                    # held there: ask first. The dialog does the move on
                    # confirming; dismissing it leaves everything as it was, and
                    # the page must not rerun, which would close it.
                    _confirm_drop(event, state, exc.lines)
                    return
            elif event["type"] == "lock":
                # Never blocks and never touches the Broken-rule check.
                session.set_state(
                    mutations.set_lock(session.get_workspace(), event["helper_id"], bool(event["locked"]))
                )
            elif event["type"] == "organizer_drop":
                source = event.get("source")
                session.set_state(
                    mutations.move_organizer(
                        session.get_workspace(),
                        event["organizer_id"],
                        event["key"],
                        event["building"],
                        event.get("room"),
                        {"role": source["key"], "building": source["building"], "room": source.get("room")}
                        if source
                        else None,
                    )
                )
            elif event["type"] == "cell_merge":
                session.set_state(
                    mutations.set_cell_merges(
                        session.get_workspace(), event["key"], event["building"], event["pairs"], event["merged"]
                    )
                )
            else:
                if event["key"] in _STRUCTURAL_ROLE_NAMES:
                    # A leadership slot takes a tracked Organizer: pick one by
                    # name or create one on the spot; the placement follows.
                    session.set_state(
                        mutations.set_slot_holders(
                            session.get_workspace(), event["key"], event["building"], event.get("room"), event["names"]
                        )
                    )
                else:
                    next_manual = _apply_overlay_set(state, event)
                    session.set_state(mutations.put_manual_roles(session.get_workspace(), next_manual))
        except mutations.RosteringError as exc:
            st.error(str(exc))
        st.rerun()
