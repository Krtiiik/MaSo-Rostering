"""Forced friends groups in the Season's saved state (see
``rostering.forced_friends`` for the rule and ``CONTEXT.md`` for the concept).

Kept apart from ``mutations`` (which it builds on) so the group lifecycle lives
in one place; Streamlit-free like it, so tests and the panel share it.

A group is a dict in ``state["forced_groups"]``: ``id`` (from the high-water
mark ``state["next_forced_group_id"]``, never reused), ``name``, ``axes``
(canonical, Room implies Building) and ``members``, one ``{person_id, name}``
per Person, ``name`` being the last name seen so a member who is not registered
this Season can still be named. Members are Persons, so who they are this
Season is derived on every read, never stored: a Helper who is attending
(active), a Helper who can't attend, an Organizer (active when placed, else
``unplaced``; ``cant_attend`` when flagged) or nobody (not registered). A Person
who is promoted to Organizer keeps their membership this way, since promotion
keeps their ``person_id``.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from rostering import forced_friends
from rostering.domain import OrganizerRef
from rostering.persistence.serialize import assignment_from_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.rules import FORCED_FRIENDS_FAMILY
from rostering.streamlit_app import mutations
from rostering.streamlit_app.mutations import RosteringError

ACTIVE = "active"
CANT_ATTEND = "cant_attend"
NOT_REGISTERED = "not_registered"
# An Organizer member who holds no slot yet: dormant until placed.
UNPLACED = "unplaced"
# A group's status badge besides ACTIVE (which a member's state shares).
DORMANT = "dormant"
VIOLATED = "violated"


def _records(state: dict[str, Any]) -> list[dict]:
    return state.setdefault("forced_groups", [])


def _helpers_of(state: dict[str, Any], person_id: str) -> list[dict]:
    return [h for h in state["helpers"] if h.get("person_id") == person_id]


def _organizers_of(state: dict[str, Any], person_id: str) -> list[dict]:
    return [o for o in state.get("organizers", []) if o.get("person_id") == person_id]


def _member_state(state: dict[str, Any], member: dict) -> dict[str, Any]:
    helpers = _helpers_of(state, member["person_id"])
    if helpers:
        live = next((h for h in helpers if not h.get("cant_attend")), None)
        shown = live or helpers[0]
        return {
            "person_id": member["person_id"],
            "name": shown["name"],
            "state": ACTIVE if live else CANT_ATTEND,
            "kind": "helper",
            "helper_id": shown["id"],
        }
    organizers = _organizers_of(state, member["person_id"])
    if organizers:
        organizer = next((o for o in organizers if not o.get("cant_attend")), organizers[0])
        if organizer.get("cant_attend"):
            member_state = CANT_ATTEND
        else:
            member_state = ACTIVE if organizer.get("building") else UNPLACED
        return {
            "person_id": member["person_id"],
            "name": organizer["name"],
            "state": member_state,
            "kind": "organizer",
            "organizer_id": organizer["id"],
            "helper_id": None,
        }
    return {
        "person_id": member["person_id"],
        "name": member.get("name", ""),
        "state": NOT_REGISTERED,
        "kind": None,
        "helper_id": None,
    }


def _describe(group: dict, violations: Sequence[str]) -> dict[str, Any]:
    members = group["members"]
    active = sum(1 for m in members if m["state"] == ACTIVE)
    reason = None
    if active < 2:
        notes = [f"{m['name']} can't attend" for m in members if m["state"] == CANT_ATTEND]
        notes += [f"{m['name']} is an unplaced Organizer" for m in members if m["state"] == UNPLACED]
        notes += [f"{m['name']} is not registered this Season" for m in members if m["state"] == NOT_REGISTERED]
        reason = f"Fewer than two active members ({active} of {len(members)})" + (
            f": {'; '.join(notes)}" if notes else ""
        )
    # A dormant group constrains nothing, so the roster cannot violate it.
    violations = list(violations) if active >= 2 else []
    status = DORMANT if active < 2 else VIOLATED if violations else ACTIVE
    # An Organizer has no solved Role, so a group sharing Role never applies it to them.
    badges = (
        [f"Role not applied to {m['name']}" for m in members if m["kind"] == "organizer"]
        if forced_friends.ROLE in group["axes"]
        else []
    )
    return {
        **group,
        "active": active >= 2,
        "reason": reason,
        "status": status,
        "violations": violations,
        "badges": badges,
    }


def _violation_lines(state: dict[str, Any]) -> dict[int, list[str]]:
    """The live checker's lines for each group the current roster violates."""
    lines: dict[int, list[str]] = {}
    for broken in mutations.broken_rules(state):
        if broken.family == forced_friends.KIND:
            lines.setdefault(broken.instance.entity[0], []).append(broken.line)
    return lines


def list_groups(state: dict[str, Any]) -> list[dict]:
    """The Season's groups as the panel shows them: ``id``, ``name``, ``axes``,
    ``members`` (``person_id``, ``name``, ``state`` one of ``"active"``,
    ``"cant_attend"``, ``"unplaced"`` (an Organizer holding no slot),
    ``"not_registered"``; ``kind`` ``"helper"``/``"organizer"``/None, and the
    ``helper_id`` or ``organizer_id`` when registered), ``active`` (two or more
    active members), the ``reason`` when it is not, and its ``status`` badge:
    ``"active"``, ``"dormant"`` (with the ``reason``) or ``"violated"`` by the
    roster as it stands, in which case ``violations`` holds the live checker's
    lines (empty otherwise). ``badges`` are notes such as ``Role not applied to
    Anna`` (an Organizer member of a group that shares Role)."""
    groups = state.get("forced_groups") or []
    violations = _violation_lines(state) if groups else {}
    return [
        _describe({**g, "members": [_member_state(state, m) for m in g.get("members") or []]}, violations.get(g["id"], ()))
        for g in groups
    ]


def member_options(state: dict[str, Any]) -> list[dict]:
    """The people the multiselect offers: one entry per Person registered this
    Season, a Helper or an Organizer (``person_id``, ``name``, ``kind``), by
    name."""
    seen: dict[str, dict] = {}
    for helper in state["helpers"]:
        if helper.get("person_id"):
            seen.setdefault(
                helper["person_id"], {"person_id": helper["person_id"], "name": helper["name"], "kind": "helper"}
            )
    for organizer in state.get("organizers", []):
        if organizer.get("person_id"):
            seen.setdefault(
                organizer["person_id"],
                {"person_id": organizer["person_id"], "name": organizer["name"], "kind": "organizer"},
            )
    return sorted(seen.values(), key=lambda o: o["name"].lower())


def _next_group_id(state: dict[str, Any]) -> int:
    new_id = max(int(state.get("next_forced_group_id") or 1), max((g["id"] for g in _records(state)), default=0) + 1)
    state["next_forced_group_id"] = new_id + 1
    return new_id


def _validated_name(name: Optional[str]) -> str:
    name = (name or "").strip()
    if not name:
        raise RosteringError("A Forced friends group needs a name.")
    return name


def _validated_axes(axes: Sequence[str]) -> list[str]:
    try:
        return list(forced_friends.normalize_axes(axes))
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc


def _validated_members(state: dict[str, Any], person_ids: Sequence[str], kept: Sequence[dict] = ()) -> list[dict]:
    """The member records for ``person_ids`` (each once, in order): a Person must
    be registered this Season, unless they are already a member (kept as they
    were, so editing a group never drops someone who is not registered)."""
    known = {m["person_id"]: m for m in kept}
    names = {o["person_id"]: o["name"] for o in member_options(state)}
    members: list[dict] = []
    for person_id in dict.fromkeys(person_ids):
        if person_id in names:
            members.append({"person_id": person_id, "name": names[person_id]})
        elif person_id in known:
            members.append(dict(known[person_id]))
        else:
            raise RosteringError("Pick only people who are registered this Season.")
    return members


def _organizer_names(state: dict[str, Any], person_ids: Sequence[str]) -> list[str]:
    """The names of those among ``person_ids`` who are Organizers this Season."""
    return [
        _member_state(state, {"person_id": p})["name"]
        for p in person_ids
        if not _helpers_of(state, p) and _organizers_of(state, p)
    ]


def _refuse_organizer_on_role(
    state: dict[str, Any],
    axes: Sequence[str],
    person_ids: Sequence[str],
    old_axes: Sequence[str] = (),
    old_person_ids: Sequence[str] = (),
) -> None:
    """An Organizer has no solved Role, so one may not be added to a group that
    shares Role, nor may Role be ticked on a group with an Organizer in it. A
    member already there under Role (promoted after the group was made) stays,
    with the badge, and never blocks an edit that leaves them be."""
    if forced_friends.ROLE not in axes:
        return
    newly = [p for p in person_ids if forced_friends.ROLE not in old_axes or p not in old_person_ids]
    names = _organizer_names(state, newly)
    if names:
        raise RosteringError(
            f"An Organizer has no Role to share: {', '.join(names)} can't be in a group that shares Role."
        )


def _stale_if_rostered(state: dict[str, Any], reason: str) -> None:
    """Nothing to make stale before the first solve."""
    if state["assignments"]:
        mutations._add_stale_reason(state, reason)


def _record(state: dict[str, Any], group_id: int) -> dict:
    for record in _records(state):
        if record["id"] == group_id:
            return record
    raise RosteringError(f"No such Forced friends group: {group_id}")


def _refuse_tag_clash(state: dict[str, Any], group_id: int) -> None:
    """The one check that blocks creating or editing a group (the group is
    already in the in-memory ``state``, not yet saved): its active members'
    effective allowed sets, from their Tags, must have something in common on
    every Building/Role axis it shares. Size, capacity and fixed Assignments
    never block; they show up as a Broken rule."""
    clashes = [c for c in mutations._group_tag_clashes(state) if c.group.id == group_id]
    if clashes:
        raise RosteringError("Refused: " + "; ".join(c.message() for c in clashes) + ".")


def add_group(workspace: Workspace, name: str, person_ids: Sequence[str], axes: Sequence[str]) -> dict:
    """Create a group. Nobody is moved; if a roster exists it is marked stale
    (a full Solve applies the group). Refused when its members' Tags leave them
    no Building or Role in common on an axis it shares."""
    name = _validated_name(name)
    canonical = _validated_axes(axes)
    state = workspace.load()
    members = _validated_members(state, person_ids)
    _refuse_organizer_on_role(state, canonical, [m["person_id"] for m in members])
    group_id = _next_group_id(state)
    _records(state).append({"id": group_id, "name": name, "axes": canonical, "members": members})
    _refuse_tag_clash(state, group_id)
    _stale_if_rostered(state, f"Forced friends group {name} was created: solve again to apply it")
    workspace.save(state)
    return state


def update_group(
    workspace: Workspace,
    group_id: int,
    *,
    name: Optional[str] = None,
    person_ids: Optional[Sequence[str]] = None,
    axes: Optional[Sequence[str]] = None,
) -> dict:
    """Edit a group; what is left out stays. Nobody is moved. A change of
    members or axes marks an existing roster stale; a rename alone does not,
    since the rules the roster was solved for are unchanged. A change of members
    or axes is refused like a creation (see :func:`_refuse_tag_clash`), even for a
    group already at odds, so it can only be edited towards holding; a rename is
    never refused."""
    state = workspace.load()
    record = _record(state, group_id)
    old_axes = list(record["axes"])
    old_person_ids = [m["person_id"] for m in record["members"]]
    changed = False
    new_axes = _validated_axes(axes) if axes is not None else old_axes
    new_members = (
        _validated_members(state, person_ids, record["members"]) if person_ids is not None else record["members"]
    )
    _refuse_organizer_on_role(state, new_axes, [m["person_id"] for m in new_members], old_axes, old_person_ids)
    if name is not None:
        record["name"] = _validated_name(name)
    if axes is not None:
        canonical = _validated_axes(axes)
        changed |= canonical != record["axes"]
        record["axes"] = canonical
    if person_ids is not None:
        members = _validated_members(state, person_ids, record["members"])
        changed |= [m["person_id"] for m in members] != [m["person_id"] for m in record["members"]]
        record["members"] = members
    if changed:
        _refuse_tag_clash(state, group_id)
        _stale_if_rostered(state, f"Forced friends group {record['name']} was changed: solve again to apply it")
    workspace.save(state)
    return state


def _was_pulling(state: dict[str, Any], group_id: int) -> bool:
    """Whether the group was actively pulling a member's placement, approximated
    as: it is active, two of its active members are placed (a placed Organizer
    always is) and the roster currently satisfies it."""
    competition = mutations._build_competition(state)
    group = next((g for g in competition.forced_groups if g.id == group_id), None)
    if group is None or not state["assignments"]:
        return False
    attending = competition.attending()
    active = forced_friends.active_helper_ids(group, attending.helpers)
    anchors = forced_friends.active_organizers(group, attending.organizers)
    placed = {a["helper_id"] for a in state["assignments"]}
    if sum(1 for h in active if h in placed) + len(anchors) < 2:
        return False
    assignments = [assignment_from_dict(a) for a in state["assignments"]]
    broken = check_roster(competition, assignments, families=[FORCED_FRIENDS_FAMILY])
    return not any(b.instance.entity[0] == group_id for b in broken)


def dissolve_group(workspace: Workspace, group_id: int) -> dict:
    """Delete a group. Nobody is moved. An existing roster is marked stale only
    if the group was actively pulling a member's placement (see
    :func:`_was_pulling`); removing a group that did nothing blocks nothing."""
    state = workspace.load()
    record = _record(state, group_id)
    pulling = _was_pulling(state, group_id)
    state["forced_groups"] = [g for g in _records(state) if g["id"] != group_id]
    if pulling:
        mutations._add_stale_reason(
            state, f"Forced friends group {record['name']} was dissolved: solve again to release its members"
        )
    workspace.save(state)
    return state


def _friend_person(state: dict[str, Any], friend: Any) -> Optional[tuple[str, str]]:
    """``(person_id, name)`` of the person a saved friend reference names (a
    Helper id, or ``{"organizer_id": n}``); None if they no longer exist."""
    if isinstance(friend, dict):
        organizer = next((o for o in state.get("organizers", []) if o["id"] == friend.get("organizer_id")), None)
        return (organizer["person_id"], organizer["name"]) if organizer and organizer.get("person_id") else None
    helper = next((h for h in state["helpers"] if h["id"] == friend), None)
    return (helper["person_id"], helper["name"]) if helper and helper.get("person_id") else None


def _same_group_exists(state: dict[str, Any], person_ids: Sequence[str], axes: Sequence[str]) -> bool:
    return any(
        g["axes"] == list(axes) and {m["person_id"] for m in g["members"]} == set(person_ids) for g in _records(state)
    )


def friend_requests(state: dict[str, Any]) -> list[dict]:
    """The resolved soft friend requests "make forced" can harden, one per
    ``helper_id`` and ``friend`` reference (a Helper id, or ``{"organizer_id":
    n}``), with both names (an Organizer marked ``(Organizer)``) and whether a
    Room group of those two people already exists (``forced``)."""
    room_axes = list(forced_friends.normalize_axes([forced_friends.ROOM]))
    requests: list[dict] = []
    for helper in state["helpers"]:
        if not helper.get("person_id"):
            continue
        for friend in helper.get("friends", []):
            person = _friend_person(state, friend)
            if person is None or person[0] == helper["person_id"]:
                continue
            requests.append(
                {
                    "helper_id": helper["id"],
                    "helper_name": helper["name"],
                    "friend": friend,
                    "friend_name": person[1] + (" (Organizer)" if isinstance(friend, dict) else ""),
                    "forced": _same_group_exists(state, [helper["person_id"], person[0]], room_axes),
                }
            )
    return requests


def make_forced(workspace: Workspace, helper_id: int, friend: Any) -> dict:
    """Harden a resolved soft friend request in one click: a new group ``Anna +
    Petr`` of the two people with the Room axis (which implies Building), made
    exactly like any group (Tag check, stale roster). The soft request itself is
    left untouched. Refused when ``helper_id`` has no such resolved friend
    request (``friend`` a Helper id or ``{"organizer_id": n}``) or when that
    group already exists."""
    state = workspace.load()
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    refs = [OrganizerRef(f["organizer_id"]) if isinstance(f, dict) else f for f in (helper or {}).get("friends", [])]
    wanted = OrganizerRef(friend["organizer_id"]) if isinstance(friend, dict) else friend
    person = _friend_person(state, friend) if helper is not None and wanted in refs else None
    if helper is None or person is None or not helper.get("person_id"):
        raise RosteringError("That is not a resolved friend request.")
    room_axes = list(forced_friends.normalize_axes([forced_friends.ROOM]))
    if _same_group_exists(state, [helper["person_id"], person[0]], room_axes):
        raise RosteringError(f"A Room group of {helper['name']} and {person[1]} already exists.")
    return add_group(workspace, f"{helper['name']} + {person[1]}", [helper["person_id"], person[0]], room_axes)
