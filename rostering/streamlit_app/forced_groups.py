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
(active), a Helper who can't attend, or nobody (not registered).
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from rostering import forced_friends
from rostering.persistence.serialize import assignment_from_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.rules import FORCED_FRIENDS_FAMILY
from rostering.streamlit_app import mutations
from rostering.streamlit_app.mutations import RosteringError

ACTIVE = "active"
CANT_ATTEND = "cant_attend"
NOT_REGISTERED = "not_registered"


def _records(state: dict[str, Any]) -> list[dict]:
    return state.setdefault("forced_groups", [])


def _helpers_of(state: dict[str, Any], person_id: str) -> list[dict]:
    return [h for h in state["helpers"] if h.get("person_id") == person_id]


def _member_state(state: dict[str, Any], member: dict) -> dict[str, Any]:
    helpers = _helpers_of(state, member["person_id"])
    if not helpers:
        return {"person_id": member["person_id"], "name": member.get("name", ""), "state": NOT_REGISTERED, "helper_id": None}
    live = next((h for h in helpers if not h.get("cant_attend")), None)
    shown = live or helpers[0]
    return {
        "person_id": member["person_id"],
        "name": shown["name"],
        "state": ACTIVE if live else CANT_ATTEND,
        "helper_id": shown["id"],
    }


def _describe(group: dict) -> dict[str, Any]:
    members = group["members"]
    active = sum(1 for m in members if m["state"] == ACTIVE)
    reason = None
    if active < 2:
        notes = [f"{m['name']} can't attend" for m in members if m["state"] == CANT_ATTEND]
        notes += [f"{m['name']} is not registered this Season" for m in members if m["state"] == NOT_REGISTERED]
        reason = f"Fewer than two active members ({active} of {len(members)})" + (
            f": {'; '.join(notes)}" if notes else ""
        )
    return {**group, "active": active >= 2, "reason": reason}


def list_groups(state: dict[str, Any]) -> list[dict]:
    """The Season's groups as the panel shows them: ``id``, ``name``, ``axes``,
    ``members`` (``person_id``, ``name``, ``state`` one of ``"active"``,
    ``"cant_attend"``, ``"not_registered"``, and the ``helper_id`` when
    registered), ``active`` (two or more active members) and, when inactive,
    the ``reason``."""
    return [
        _describe({**g, "members": [_member_state(state, m) for m in g.get("members") or []]})
        for g in state.get("forced_groups") or []
    ]


def member_options(state: dict[str, Any]) -> list[dict]:
    """The people the multiselect offers: one entry per Person registered this
    Season (``person_id``, ``name``), by name."""
    seen: dict[str, str] = {}
    for helper in state["helpers"]:
        if helper.get("person_id"):
            seen.setdefault(helper["person_id"], helper["name"])
    return sorted(({"person_id": p, "name": n} for p, n in seen.items()), key=lambda o: o["name"].lower())


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


def _stale_if_rostered(state: dict[str, Any], reason: str) -> None:
    """Nothing to make stale before the first solve."""
    if state["assignments"]:
        mutations._add_stale_reason(state, reason)


def _record(state: dict[str, Any], group_id: int) -> dict:
    for record in _records(state):
        if record["id"] == group_id:
            return record
    raise RosteringError(f"No such Forced friends group: {group_id}")


def add_group(workspace: Workspace, name: str, person_ids: Sequence[str], axes: Sequence[str]) -> dict:
    """Create a group. Nobody is moved; if a roster exists it is marked stale
    (a full Solve applies the group)."""
    name = _validated_name(name)
    canonical = _validated_axes(axes)
    state = workspace.load()
    members = _validated_members(state, person_ids)
    _records(state).append({"id": _next_group_id(state), "name": name, "axes": canonical, "members": members})
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
    since the rules the roster was solved for are unchanged."""
    state = workspace.load()
    record = _record(state, group_id)
    changed = False
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
        _stale_if_rostered(state, f"Forced friends group {record['name']} was changed: solve again to apply it")
    workspace.save(state)
    return state


def _was_pulling(state: dict[str, Any], group_id: int) -> bool:
    """Whether the group was actively pulling a member's placement, approximated
    as: it is active, two of its active members are placed and the roster
    currently satisfies it."""
    competition = mutations._build_competition(state)
    group = next((g for g in competition.forced_groups if g.id == group_id), None)
    if group is None or not state["assignments"]:
        return False
    active = forced_friends.active_helper_ids(group, competition.attending().helpers)
    placed = {a["helper_id"] for a in state["assignments"]}
    if len(active) < 2 or sum(1 for h in active if h in placed) < 2:
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
