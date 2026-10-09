"""The roster grid's view model, as plain data: a pure function of the Season's
state plus the Overlays and Tag filter chosen on the Roster tab. No NiceGUI in
here, so it is tested directly; ``render`` turns it into the grid's HTML.

Layout: the columns are always one per physical Room, grouped under their
Building. Rows, top to bottom: the leadership slots (Organizer rows), the six
solver Roles, the Additional roles, then Technická podpora (see CONTEXT.md). Any
*one row* (a solver Role, or a Room-scoped manual role) can merge two or more of
its own adjacent cells into one wider cell, like merging cells within a single
spreadsheet row; every other row for the same Rooms is unaffected
(``state["cell_merges"]``, see ``rostering.domain.group_adjacent_rooms``). That
is purely presentational: Assignments always name exact Rooms.

Friend relations are derived from each Helper's own ``friends`` list (what they
wrote on the form, resolved to ids) and the current Assignments — deliberately
not from the solver's satisfied/unsatisfied pair diagnostics, which the
friend-scoring config can collapse or drop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from rostering.domain import OverlayRole, Preference, Role, StructuralRole, normalize_name
from rostering.ingest.mapping import building_keys
from rostering.webapp import labels, mutations

ROLE_ORDER = [r.name for r in Role]
ROLE_LABELS = {r.name: r.value for r in Role}
RESERVE_ROLE = Role.Zaloha.name
# Preference level of Nevadí: the lowest one Role satisfaction counts as
# satisfied (a blank answer counts as Nevadí; Záloha is left unjudged).
NEUTRAL_LEVEL = Preference.Nevadi.value

# Manual rows before the solved Roles (Building leadership, then Room leads) and
# after them (the Additional roles, then tech support), following the Season's
# historical hand-built roster layout. Each is (role, scope, duplicate drop):
# a duplicate-drop row also takes a Helper's chip dragged from their own
# Room (scope "room") or Building (scope "building"), which adds them to that
# role without moving their Assignment.
MANUAL_ROWS_BEFORE = [
    (StructuralRole.VedouciBudovy, "building", False),
    (StructuralRole.PravaRuka, "room", False),
    (StructuralRole.VedouciMistnosti, "room", False),
]
MANUAL_ROWS_AFTER = [
    (OverlayRole.UvadeciUcastniku, "room", True),
    (OverlayRole.FoceniPredavaniCen, "room", True),
    (OverlayRole.Registrace, "building", True),
    (StructuralRole.TechnickaPodpora, "building", False),
]
STRUCTURAL_ROLE_NAMES = {r.name for r in StructuralRole}

# The Czech wording of the form (see rostering.ingest.preferences), for the
# details card; Preference's member names are ASCII identifiers, not display text.
PREFERENCE_LABELS = {
    Preference.Ano.name: "Ano",
    Preference.Klidne.name: "Klidně",
    Preference.Nevadi.name: "Nevadí",
    Preference.Spise_ne.name: "Spíš ne",
    Preference.Ne.name: "Ne",
}

# The decorations the Overlays chips switch on, key -> label. Friends is on to
# begin with, as friend highlighting always was.
OVERLAYS = {
    "friends": "Kamarádi",
    "tags": "Štítky",
    "role_fit": "Spokojenost s rolí",
    "building_fit": "Spokojenost s budovou",
}
DEFAULT_OVERLAYS = ["friends"]
TAGS_OVERLAY = "tags"


# ---------------------------------------------------------------------- rows
@dataclass(frozen=True)
class GridRow:
    kind: str  # "role" or "manual"
    key: str
    label: str
    scope: str = "room"  # manual rows: "building" or "room"
    organizer: bool = False  # a leadership slot: takes Organizers only
    duplicate_drop: bool = False


def grid_rows() -> list[GridRow]:
    def manual(role, scope: str, duplicate_drop: bool) -> GridRow:
        return GridRow(
            kind="manual",
            key=role.name,
            label=role.value,
            scope=scope,
            organizer=role.name in STRUCTURAL_ROLE_NAMES,
            duplicate_drop=duplicate_drop,
        )

    rows = [manual(*spec) for spec in MANUAL_ROWS_BEFORE]
    rows += [GridRow(kind="role", key=name, label=ROLE_LABELS[name]) for name in ROLE_ORDER]
    rows += [manual(*spec) for spec in MANUAL_ROWS_AFTER]
    return rows


def flatten_rooms(config: list[dict]) -> list[dict]:
    return [{"building": b["name"], "room": r["name"]} for b in config for r in b["rooms"]]


def building_groups(rooms: list[dict]) -> list[tuple[str, list[str]]]:
    """Consecutive Rooms sharing a Building, in config order: (Building, Rooms)."""
    groups: list[tuple[str, list[str]]] = []
    for r in rooms:
        if groups and groups[-1][0] == r["building"]:
            groups[-1][1].append(r["room"])
        else:
            groups.append((r["building"], [r["room"]]))
    return groups


def group_adjacent(room_names: list[str], merged_pairs: Sequence[Sequence[str]]) -> list[list[str]]:
    merged = {(a, b) for a, b in merged_pairs}
    groups: list[list[str]] = []
    for name in room_names:
        if groups and (groups[-1][-1], name) in merged:
            groups[-1].append(name)
        else:
            groups.append([name])
    return groups


# ---------------------------------------------------------------------- people
def acceptable_buildings(building_preferences: list[str], config: list[dict]) -> list[str]:
    """The Season's Buildings a Helper's Building preference accepts (see
    CONTEXT.md "Building preference"): every one when the set is empty, else those
    matching an entry the way the solver matches them."""
    if not building_preferences:
        return [b["name"] for b in config]
    wanted = frozenset().union(*(building_keys(p) for p in building_preferences))
    return [b["name"] for b in config if not building_keys(b["name"]).isdisjoint(wanted)]


def role_preferences(prefs: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {role: {"level": Preference[p].value, "label": PREFERENCE_LABELS[p]} for role, p in prefs.items()}


def manual_display_name(entry: dict, helper_names: dict[int, str]) -> str:
    helper_id = entry.get("helper_id")
    if helper_id is not None:
        return helper_names.get(helper_id, f"#{helper_id}")
    return entry.get("helper_name") or ""


def manual_entries(
    state: dict,
    organizer_pills: Optional[dict[int, dict]] = None,
    dimmed_organizer_ids: Sequence[int] = (),
    organizer_broken: Optional[dict[int, list[str]]] = None,
) -> list[dict]:
    """The manual-role entries shown in the grid. An Organizer's entry also
    carries their Tag pills, whether the Tag filter dims them and the Broken-rule
    lines their placement is part of, like a Helper's chip does. An entry saved
    before Organizers existed (a Helper or typed text) in a leadership slot is
    ``legacy``: shown, marked, until it is replaced."""
    manual = state["manual_roles"]
    helper_names = {h["id"]: h["name"] for h in state["helpers"]}
    organizer_names = {o["id"]: o["name"] for o in state["organizers"]}
    entries = []
    for s in manual["structural"]:
        organizer_id = s.get("organizer_id")
        entry = {
            "key": s["role"],
            "building": s["building"],
            "room": s.get("room"),
            "helper_id": s.get("helper_id"),
            "organizer_id": organizer_id,
            "legacy": organizer_id is None,
            "name": organizer_names.get(organizer_id, f"#{organizer_id}")
            if organizer_id is not None
            else manual_display_name(s, helper_names),
        }
        if organizer_id is not None:
            entry.update(
                tags=(organizer_pills or {}).get(organizer_id),
                dimmed=organizer_id in dimmed_organizer_ids,
                broken=(organizer_broken or {}).get(organizer_id, []),
            )
        entries.append(entry)
    for o in manual["overlay"]:
        entries.append(
            {
                "key": o["role"],
                "building": o.get("building"),
                "room": o.get("room"),
                "helper_id": o.get("helper_id"),
                "organizer_id": None,
                "legacy": False,
                "name": manual_display_name(o, helper_names),
            }
        )
    return [e for e in entries if e["name"]]


def grid_organizers(
    state: dict,
    organizer_pills: dict[int, dict],
    dimmed_organizer_ids: Sequence[int],
    organizer_broken: dict[int, list[str]],
) -> list[dict]:
    """The Organizers who attend, for the grid's draggable chips: ``placed`` says
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


# ---------------------------------------------------------------------- Additional roles
def resolve_manual_name(state: dict, name: str) -> dict:
    """A hand-typed name as a registered, attending Helper (matched diacritics-
    and whitespace-insensitively, like the rest of ingestion), or kept as free
    text for someone unregistered."""
    norm = normalize_name(name)
    for h in state["helpers"]:
        # A Helper who can't attend is not on the roster: their name stays text.
        if not h.get("cant_attend") and normalize_name(h["name"]) == norm:
            return {"helper_id": h["id"], "helper_name": None}
    return {"helper_id": None, "helper_name": name}


def apply_overlay_set(state: dict, key: str, building: Optional[str], room: Optional[str], names: list[str]) -> dict:
    """The Manual roles after an edit of an Additional role cell. The leadership
    slots take Organizers instead, see ``mutations.set_slot_holders``."""
    cleaned = [n.strip() for n in names if n and n.strip()]
    manual = state["manual_roles"]
    other = [
        o
        for o in manual["overlay"]
        if not (o["role"] == key and o.get("building") == building and o.get("room") == room)
    ]
    new_entries = [{"role": key, "building": building, "room": room, **resolve_manual_name(state, n)} for n in cleaned]
    return {**manual, "overlay": other + new_entries}


# ---------------------------------------------------------------------- the whole grid
@dataclass
class GridView:
    """Everything the grid draws, already judged (see the module docstring)."""

    rooms: list[dict]
    rows: list[GridRow]
    helpers: dict[int, dict]  # attending Helpers, with their chip data
    assignments: dict[int, dict]  # helper id -> Assignment
    entries: list[dict]
    organizers: list[dict]
    helper_names: list[str]
    organizer_names: list[str]
    overlays: list[str]
    broken_cells: dict[tuple, list[str]] = field(default_factory=dict)  # (building, room, role) -> lines
    broken_rooms: dict[tuple, list[str]] = field(default_factory=dict)  # (building, room) -> lines
    broken_helpers: dict[int, list[str]] = field(default_factory=dict)
    dimmed_helper_ids: set[int] = field(default_factory=set)
    friend_status: dict[int, dict[int, bool]] = field(default_factory=dict)  # who THEY named -> co-located?
    requesters: dict[int, list[int]] = field(default_factory=dict)  # who named THEM
    # The same for requests toward an Organizer: helper id -> {organizer id -> met?}
    # and organizer id -> the Helpers who named them. Organizer ids and Helper ids
    # are separate id spaces, hence the separate maps.
    organizer_status: dict[int, dict[int, bool]] = field(default_factory=dict)
    organizer_requesters: dict[int, list[int]] = field(default_factory=dict)

    @property
    def friends_on(self) -> bool:
        return "friends" in self.overlays

    @property
    def tags_on(self) -> bool:
        return TAGS_OVERLAY in self.overlays

    def unsatisfied(self, helper_id: int) -> bool:
        """A Helper with at least one friend (Helper or Organizer) they named not
        in their Room."""
        return any(
            not ok
            for status in (self.friend_status, self.organizer_status)
            for ok in status.get(helper_id, {}).values()
        )

    def role_fit(self, helper_id: int) -> Optional[bool]:
        placed = self.assignments.get(helper_id)
        if "role_fit" not in self.overlays or placed is None or placed["role"] == RESERVE_ROLE:
            return None
        pref = self.helpers[helper_id]["role_preferences"].get(placed["role"])
        return (pref["level"] if pref else NEUTRAL_LEVEL) >= NEUTRAL_LEVEL

    def building_fit(self, helper_id: int) -> Optional[bool]:
        placed = self.assignments.get(helper_id)
        if "building_fit" not in self.overlays or placed is None:
            return None
        return placed["building"] in self.helpers[helper_id]["acceptable_buildings"]


def organizer_request_met(organizer: dict, placed: Optional[dict]) -> bool:
    """Whether a Helper's request to be with ``organizer`` is met, judged like the
    solver does: by sharing the Organizer's Room when they hold one, by sharing
    their Building when they are placed at Building level only, never while the
    Organizer is unplaced (or the Helper is)."""
    if placed is None or not organizer.get("building"):
        return False
    if organizer.get("room"):
        return (placed["building"], placed["room"]) == (organizer["building"], organizer["room"])
    return placed["building"] == organizer["building"]


def build_view(state: dict, overlays: Sequence[str], filter_tags: Sequence[int], filter_mode: str) -> GridView:
    """The grid as it stands. Helpers flagged Can't attend are not on it at all
    (not in a cell, not in the Nezařazení pool, not in the name suggestions), and a
    friend request naming one is not shown. A request toward an attending
    Organizer is shown too (``organizer_status``); one toward an Organizer who
    can't attend is not, as the solver does not score it."""
    overlays = [key for key in OVERLAYS if key in overlays]
    if TAGS_OVERLAY not in overlays:
        filter_tags = []  # with Tags off the filter dims no one
    attending = [h for h in state["helpers"] if not h.get("cant_attend")]
    attending_ids = {h["id"] for h in attending}
    pills = mutations.grid_tag_pills(state)
    answers_changed = mutations.answers_changed_since_placed(state)
    forced = mutations.grid_forced_groups(state)
    broken_rules = mutations.broken_rules(state)
    marks = mutations.broken_rule_marks(broken_rules)
    organizer_broken: dict[int, list[str]] = {}
    for mark in marks["organizers"]:
        organizer_broken.setdefault(mark["organizer_id"], []).append(mark["line"])
    dimmed_organizers = mutations.dimmed_organizer_ids(state, list(filter_tags), filter_mode)
    organizer_pills = mutations.organizer_tag_pills(state)
    attending_organizers = {o["id"]: o for o in state["organizers"] if not o.get("cant_attend")}

    helpers = {
        h["id"]: {
            "id": h["id"],
            "name": h["name"],
            "tags": pills[h["id"]],
            "answers_changed": [labels.answer_label(a) for a in answers_changed.get(h["id"], [])],
            "forced_groups": forced.get(h["id"], []),
            "can_bring_notebook": h["can_bring_notebook"],
            "can_bring_camera": h["can_bring_camera"],
            "role_preferences": role_preferences(h["role_preferences"]),
            "building_preferences": h["building_preferences"],
            "acceptable_buildings": acceptable_buildings(h["building_preferences"], state["config"]),
            "friends": [
                f for f in h["friends"] if isinstance(f, int) and f in attending_ids and f != h["id"]
            ],
            "organizer_friends": list(
                dict.fromkeys(
                    f["organizer_id"]
                    for f in h["friends"]
                    if isinstance(f, dict) and f.get("organizer_id") in attending_organizers
                )
            ),
        }
        for h in attending
    }
    assignments = {a["helper_id"]: a for a in state["assignments"] if a["helper_id"] in helpers}

    def same_room(a: int, b: int) -> bool:
        pa, pb = assignments.get(a), assignments.get(b)
        return pa is not None and pb is not None and (pa["building"], pa["room"]) == (pb["building"], pb["room"])

    friend_status: dict[int, dict[int, bool]] = {}
    requesters: dict[int, list[int]] = {}
    for h in helpers.values():
        for friend_id in h["friends"]:
            friend_status.setdefault(h["id"], {})[friend_id] = same_room(h["id"], friend_id)
            requesters.setdefault(friend_id, []).append(h["id"])

    organizer_status: dict[int, dict[int, bool]] = {}
    organizer_requesters: dict[int, list[int]] = {}
    for h in helpers.values():
        for organizer_id in h["organizer_friends"]:
            organizer_status.setdefault(h["id"], {})[organizer_id] = organizer_request_met(
                attending_organizers[organizer_id], assignments.get(h["id"])
            )
            organizer_requesters.setdefault(organizer_id, []).append(h["id"])

    broken_cells: dict[tuple, list[str]] = {}
    broken_rooms: dict[tuple, list[str]] = {}
    for m in marks["cells"]:
        room_key = (m["building"], m["room"])
        if m["line"] not in broken_rooms.get(room_key, []):
            broken_rooms.setdefault(room_key, []).append(m["line"])
        if m["role"] is not None:
            broken_cells.setdefault((m["building"], m["room"], m["role"]), []).append(m["line"])
    broken_helpers: dict[int, list[str]] = {}
    for m in marks["helpers"]:
        broken_helpers.setdefault(m["helper_id"], []).append(m["line"])

    return GridView(
        rooms=flatten_rooms(state["config"]),
        rows=grid_rows(),
        helpers=helpers,
        assignments=assignments,
        entries=manual_entries(state, organizer_pills, dimmed_organizers, organizer_broken),
        organizers=grid_organizers(state, organizer_pills, dimmed_organizers, organizer_broken),
        helper_names=sorted({h["name"] for h in attending}, key=str.lower),
        # An Organizer who can't attend is not offered for a slot.
        organizer_names=sorted({o["name"] for o in state["organizers"] if not o.get("cant_attend")}, key=str.lower),
        overlays=overlays,
        broken_cells=broken_cells,
        broken_rooms=broken_rooms,
        broken_helpers=broken_helpers,
        dimmed_helper_ids=set(mutations.dimmed_helper_ids(state, list(filter_tags), filter_mode)) & set(helpers),
        friend_status=friend_status,
        requesters=requesters,
        organizer_status=organizer_status,
        organizer_requesters=organizer_requesters,
    )


def card_data(view: GridView, helper_id: int) -> Optional[dict]:
    """The details card of one Helper: their Building preference, Role ratings
    (the solver Roles but Záloha, which nobody rates) and friend requests split
    into shared Room (green), elsewhere (red) and who asked for them (purple),
    plus their Tags (shown whatever the Overlays) and the Forced friends groups
    that bind them."""
    h = view.helpers.get(helper_id)
    if h is None:
        return None
    names = {i: x["name"] for i, x in view.helpers.items()}
    organizer_names = {o["id"]: f"{o['name']} (organizátor)" for o in view.organizers}
    status = view.friend_status.get(helper_id, {})
    organizer_status = view.organizer_status.get(helper_id, {})
    placed = view.assignments.get(helper_id)
    return {
        "name": h["name"],
        "placed": placed is not None,
        "locked": bool(placed and placed.get("locked")),
        "building_preferences": h["building_preferences"],
        "roles": [
            (ROLE_LABELS[role], h["role_preferences"].get(role)) for role in ROLE_ORDER if role != RESERVE_ROLE
        ],
        "shared": [names[f] for f, ok in status.items() if ok]
        + [organizer_names[o] for o, ok in organizer_status.items() if ok],
        "different": [names[f] for f, ok in status.items() if not ok]
        + [organizer_names[o] for o, ok in organizer_status.items() if not ok],
        "requested_by": [names[r] for r in view.requesters.get(helper_id, [])],
        "tags": h["tags"],
        "forced_groups": h["forced_groups"],
    }
