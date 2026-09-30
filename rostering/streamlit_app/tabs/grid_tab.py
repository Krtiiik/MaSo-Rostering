"""Tab 3: the drag-and-drop assignment grid, including the manual
structural/overlay roles (see CLAUDE.md "Out-of-solver roles") rendered as
extra rows in the same grid rather than as a separate section below it. Most
manual rows are typed/picked-name only; the overlay roles (UvadeciUcastniku,
FoceniPredavaniCen: room-scoped; Registrace: building-scoped) additionally
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

import streamlit as st

from rostering import tags as tag_tree
from rostering.domain import BrokenRule, OverlayRole, Preference, Role, StructuralRole, normalize_name
from rostering.streamlit_app import fix_focus, mutations, session, solve_prompt
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

# These structural roles are typically filled by people who never registered
# as a helper (teachers, organizers), so their manual-role cells are plain
# free text rather than an autocomplete/pick against registered helpers —
# unlike overlay roles and Technická podpora, which layer onto an already
# registered, already-assigned helper. Each is also a single-holder role (one
# building lead, one deputy, one lead per room), so their cells cap at one
# name rather than the multi-name lists overlay/Technická podpora cells allow.
_PLAIN_TEXT_ROLE_NAMES = {
    StructuralRole.VedouciBudovy.name,
    StructuralRole.PravaRuka.name,
    StructuralRole.VedouciMistnosti.name,
}

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
    def manual_row(role, scope: str, allow_duplicate_drop: bool) -> dict:
        return {
            "kind": "manual",
            "key": role.name,
            "label": role.value,
            "scope": scope,
            "plain_text": role.name in _PLAIN_TEXT_ROLE_NAMES,
            "single_entry": role.name in _PLAIN_TEXT_ROLE_NAMES,
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
                "building": o.get("building"),
                "room": o.get("room"),
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
        # A Helper who can't attend is not on the roster, so their name is not
        # matched: it stays free text rather than pointing a role at them.
        if not h.get("cant_attend") and normalize_name(h["name"]) == norm:
            return {"helper_id": h["id"], "helper_name": None}
    return {"helper_id": None, "helper_name": name}


def _apply_manual_set(state: dict, event: dict) -> dict:
    key = event["key"]
    building = event.get("building")
    room = event.get("room")
    names = [n.strip() for n in event.get("names", []) if n and n.strip()]
    manual = state["manual_roles"]
    if key in _PLAIN_TEXT_ROLE_NAMES:
        names = names[-1:]  # single-holder role — keep only the latest name
        resolved = [{"helper_id": None, "helper_name": n} for n in names]
    else:
        resolved = [_resolve_manual_name(state, n) for n in names]

    if key in _STRUCTURAL_ROLE_NAMES:
        filtered = [
            s
            for s in manual["structural"]
            if not (s["role"] == key and s["building"] == building and s.get("room") == room)
        ]
        new_entries = [{"role": key, "building": building, "room": room, **r} for r in resolved]
        return {**manual, "structural": filtered + new_entries}

    # Overlay roles are either building-scoped (room None, e.g. Registrace)
    # or room-scoped (UvadeciUcastniku/FoceniPredavaniCen) — in both cases
    # filtered/replaced the same way as structural, by (role, building, room).
    other = [
        o
        for o in manual["overlay"]
        if not (o["role"] == key and o.get("building") == building and o.get("room") == room)
    ]
    new_entries = [{"role": key, "building": building, "room": room, **r} for r in resolved]
    return {**manual, "overlay": other + new_entries}


_TOAST_KEY = "_move_toast"

# How the Broken-rule banner names each rule family, in tier order. A family
# not listed (added later through rostering.solver.rules.register_rule_family)
# falls back to its own name.
_FAMILY_LABELS = {
    "minimums": "Room and Building minimums",
    "tag_restrictions": "Tag restrictions",
    "forced_friends": "Forced-friend groups",
    "equipment": "Equipment",
}

# A family with more broken instances than this collapses into an expandable
# summary so the banner never becomes a wall of text.
_COLLAPSE_ABOVE = 10


def _render_broken_line(broken: BrokenRule) -> None:
    cols = st.columns([9, 1], vertical_alignment="center")
    cols[0].markdown(f"- {broken.line}")
    if fix_focus.can_go_fix(broken):
        key = f"go_fix_{broken.instance.kind}_{'_'.join(map(str, broken.instance.entity))}"
        if cols[1].button("Go fix", key=key):
            fix_focus.go_fix(broken)
            st.rerun()


def _render_broken_banner(broken_rules: list[BrokenRule], has_roster: bool) -> None:
    """The warning banner above the grid: one line per broken rule instance,
    grouped by family (in the order the rules bend), each with a "Go fix"
    button; a family above about ten instances collapses into an expander."""
    if not broken_rules:
        if has_roster:
            st.caption("✓ No broken rules")
        return
    by_family: dict[str, list[BrokenRule]] = {}
    for broken in broken_rules:
        by_family.setdefault(broken.family, []).append(broken)
    with st.container(border=True):
        st.markdown(f"**⚠ {len(broken_rules)} broken rule{'s' if len(broken_rules) != 1 else ''}**")
        for family, instances in by_family.items():
            label = _FAMILY_LABELS.get(family, family)
            if len(instances) > _COLLAPSE_ABOVE:
                with st.expander(f"{label}: {len(instances)} broken"):
                    for broken in instances:
                        _render_broken_line(broken)
            else:
                st.caption(label)
                for broken in instances:
                    _render_broken_line(broken)


# Session-state keys of the grid's Tag controls (dropped when another Season
# opens, see session.workspace_replaced): the "Show tags" toggle, the Tag filter's
# Tag ids and its all-of / any-of mode. The filter only dims; it never hides.
SHOW_TAGS_KEY = "_grid_show_tags"
TAG_FILTER_KEY = "_grid_tag_filter"
TAG_MODE_KEY = "_grid_tag_mode"
_MODE_LABELS = {tag_tree.ALL_OF: "All of", tag_tree.ANY_OF: "Any of"}


def _render_tag_controls(state: dict) -> tuple[bool, list[int], str]:
    """The "Show tags" toggle and the Tag filter above the grid; returns
    ``(show_tags, filter_tag_ids, mode)``. The two are independent."""
    tags = state.get("tags") or []
    known = {t["id"] for t in tags}
    # A Tag deleted (or a Season swapped) since the filter was chosen.
    if TAG_FILTER_KEY in st.session_state:
        st.session_state[TAG_FILTER_KEY] = [t for t in st.session_state[TAG_FILTER_KEY] if t in known]
    names = {t["id"]: t["name"] for t in tags}
    ordered = [t.id for t, _ in tag_tree.tree_order([tag_tree.tag_from_dict(t) for t in tags])]
    toggle_col, filter_col, mode_col = st.columns([2, 6, 3], vertical_alignment="bottom")
    show_tags = toggle_col.toggle("Show tags", key=SHOW_TAGS_KEY)
    chosen = filter_col.multiselect(
        "Filter by tags",
        ordered,
        format_func=names.__getitem__,
        key=TAG_FILTER_KEY,
        placeholder="Dim helpers without these tags" if tags else "No tags yet",
        disabled=not tags,
        help="Helpers who do not match are dimmed, never hidden. Inherited tags count.",
    )
    mode = mode_col.radio(
        "Match",
        list(_MODE_LABELS),
        format_func=_MODE_LABELS.__getitem__,
        key=TAG_MODE_KEY,
        horizontal=True,
        disabled=not tags,
    )
    return show_tags, chosen, mode


def render() -> None:
    st.header("4. Roster")
    state = session.get_state()
    rooms = _flatten_rooms(state["config"])
    upload_summary_ui.render("roster")

    if not rooms:
        st.info("Configure at least one building with a room first.")
        return

    locked = mutations.locked_count(state)

    def run_solve() -> None:
        with st.spinner("Solving…"):
            try:
                solved = mutations.solve(session.get_workspace())
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            session.set_state(solved)
            solve_prompt.remember_dropped_locks(solved)
        st.rerun()

    stale = mutations.stale_reasons(state)
    unplaced = mutations.unplaced_reason(state)
    blockers = mutations.export_blockers(state)
    with st.bottom:
        if stale:
            # Right above the Solve button: what made the roster stale, and that
            # Solving is what clears it.
            st.warning(
                "**Roster is out of date:** " + "; ".join(stale) + ". Solve again; Export is blocked until then.",
                icon="⚠️",
            )
        if unplaced:
            # Registrants nobody has placed yet (e.g. new in a re-upload): drag
            # them into the grid from the Unassigned pool, or Solve.
            st.warning(
                f"**{unplaced}.** Drag them into the grid from the Unassigned pool, or Solve; Export is blocked "
                "until everyone is placed.",
                icon="⚠️",
            )
        cols = st.columns([2, 2, 2, 1, 2], vertical_alignment="center")
        solve_label = f"Solve (keeps {locked} locked)" if locked else ("Re-solve" if state["assignments"] else "Solve")
        if cols[0].button(solve_label, type="primary"):
            solve_prompt.request_solve(state, run_solve)

        # Bulk lock management; single locks are set on the chips themselves.
        if cols[1].button("Lock all placed", disabled=not state["assignments"] or locked == len(state["assignments"])):
            session.set_state(mutations.lock_all_placed(session.get_workspace()))
            st.rerun()
        if cols[2].button("Clear all locks", disabled=not locked):
            session.set_state(mutations.clear_all_locks(session.get_workspace()))
            st.rerun()
        cols[3].markdown(f"**{locked}** locked")

        if state["assignments"] and blockers:
            cols[4].button("Export to Excel", disabled=True, help="Export is blocked: " + "; ".join(blockers))
        elif state["assignments"]:
            try:
                export_bytes = mutations.export_xlsx_bytes(session.get_workspace())
                cols[4].download_button(
                    "Export to Excel",
                    data=export_bytes,
                    file_name="roster.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except mutations.RosteringError:
                pass

    solve_prompt.show_dropped_locks()

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
    show_tags, filter_tags, filter_mode = _render_tag_controls(state)
    helper_pills = mutations.grid_tag_pills(state)
    answers_changed = mutations.answers_changed_since_placed(state)
    grid_helpers = [
        {
            "id": h["id"],
            "name": h["name"],
            "tags": helper_pills[h["id"]],
            "answers_changed": answers_changed.get(h["id"], []),
            "can_bring_notebook": h["can_bring_notebook"],
            "can_bring_camera": h["can_bring_camera"],
            "role_preferences": _grid_role_preferences(h["role_preferences"]),
            "building_preferences": h["building_preferences"],
            "friends": [f for f in h["friends"] if f not in absent_ids],
        }
        for h in attending
    ]

    event = assignment_grid(
        rooms=rooms,
        rows=_grid_rows(),
        helpers=grid_helpers,
        assignments=state["assignments"],
        manual_entries=_manual_entries(state),
        cell_merges=state.get("cell_merges", {}),
        helper_names=sorted({h["name"] for h in attending}, key=str.lower),
        broken_marks=mutations.broken_rule_marks(broken_rules),
        show_tags=show_tags,
        dimmed_helper_ids=mutations.dimmed_helper_ids(state, filter_tags, filter_mode),
        key="assignment_grid",
    )
    if event:
        # CCv2 triggers reset automatically after the rerun that reports
        # them, so no dedup bookkeeping is needed here.
        try:
            if event["type"] == "drop":
                # Never refused, whatever it breaks; the toast only names what
                # this drop newly broke (minimums excepted).
                moved = mutations.move_helper(
                    session.get_workspace(), event["helper_id"], event["building"], event["room"], event["role"]
                )
                session.set_state(moved)
                toast_lines = mutations.move_toast_lines(state, moved)
                if toast_lines:
                    st.session_state[_TOAST_KEY] = toast_lines
            elif event["type"] == "lock":
                # Never blocks and never touches the Broken-rule check.
                session.set_state(
                    mutations.set_lock(session.get_workspace(), event["helper_id"], bool(event["locked"]))
                )
            elif event["type"] == "cell_merge":
                session.set_state(
                    mutations.set_cell_merges(
                        session.get_workspace(), event["key"], event["building"], event["pairs"], event["merged"]
                    )
                )
            else:
                next_manual = _apply_manual_set(state, event)
                session.set_state(mutations.put_manual_roles(session.get_workspace(), next_manual))
        except mutations.RosteringError as exc:
            st.error(str(exc))
        st.rerun()
