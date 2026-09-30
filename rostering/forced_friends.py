"""Forced friends groups (see ``CONTEXT.md``: Forced friends group).

A group is a named hard constraint on a set of *Persons* who must share the
ticked axes: Building, Room and/or Role, where ticking Room implies Building.
Members are Persons (``person_id``), not per-Season records, so a group can
outlive a Season and resolves in the open Season to a Helper or to "not
registered". Overlapping groups are never merged.

This module holds the pure rule definition that the solver's relaxation, the
live Broken-rule checker and the mutation layer all consume, so they cannot
drift: which axes are enforced, who the *active* members are, the identity and
wording of a violation, and its size. It does no I/O and never imports the
solver.

Active member: a Helper of the Season who is not Can't attend. A group with
fewer than two active members is inactive and constrains nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable, Iterable, Optional, Sequence

from rostering.domain import Helper, RuleInstance

BUILDING = "building"
ROOM = "room"
ROLE = "role"
# In this canonical order; a group stores exactly the axes it selects, with
# Building added whenever Room is ticked.
AXES = (BUILDING, ROOM, ROLE)

AXIS_LABELS = {BUILDING: "Building", ROOM: "Room", ROLE: "Role"}
_PLURALS = {BUILDING: "Buildings", ROOM: "Rooms", ROLE: "Roles"}

# The RuleInstance / BrokenRule family name of this rule.
KIND = "forced_friends"


@dataclass(frozen=True)
class ForcedGroup:
    """A Forced friends group: ``axes`` (canonical, see :func:`normalize_axes`)
    and the ``person_ids`` of its members."""

    id: int
    name: str
    axes: tuple[str, ...]
    person_ids: tuple[str, ...]


def normalize_axes(axes: Iterable[str]) -> tuple[str, ...]:
    """The canonical axes for the ticked ``axes``: Room implies Building, in
    the order Building, Room, Role. ``ValueError`` for an unknown axis or when
    none is ticked."""
    ticked = set(axes)
    unknown = ticked - set(AXES)
    if unknown:
        raise ValueError(f"Unknown axis: {sorted(unknown)[0]!r}")
    if ROOM in ticked:
        ticked.add(BUILDING)
    if not ticked:
        raise ValueError("Tick at least one axis (Building, Room or Role) the group must share.")
    return tuple(axis for axis in AXES if axis in ticked)


def enforced_axes(axes: Sequence[str]) -> tuple[str, ...]:
    """The axes that are checked and bent on their own: Room subsumes Building
    (a shared Room is a shared Building), so a Room group is judged on Room."""
    return tuple(axis for axis in axes if not (axis == BUILDING and ROOM in axes))


def group_to_dict(group: ForcedGroup, names: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """The saved form: ``members`` keep the last-known name of each Person, so a
    member who is not registered this Season can still be named."""
    names = names or {}
    return {
        "id": group.id,
        "name": group.name,
        "axes": list(group.axes),
        "members": [{"person_id": p, "name": names.get(p, "")} for p in group.person_ids],
    }


def group_from_dict(data: dict[str, Any]) -> ForcedGroup:
    return ForcedGroup(
        id=int(data["id"]),
        name=data["name"],
        axes=normalize_axes(data.get("axes") or []),
        person_ids=tuple(m["person_id"] for m in data.get("members") or []),
    )


def groups_from_state(state: dict[str, Any]) -> list[ForcedGroup]:
    """The groups saved in a Season's state (``state["forced_groups"]``; a state
    saved before groups existed has none)."""
    return [group_from_dict(g) for g in state.get("forced_groups") or []]


def place_value(axis: str, building: str, room: str, role: str) -> Hashable:
    """What an Assignment says on ``axis``; equal values mean shared."""
    if axis == BUILDING:
        return building
    if axis == ROOM:
        return (building, room)  # a Room name alone is not unique across Buildings
    return role


def split_units(values: Sequence[Hashable]) -> int:
    """The size of a split: how many members are not with the largest party
    sharing a value (0 when all share one)."""
    if not values:
        return 0
    return len(values) - max(values.count(v) for v in set(values))


@dataclass(frozen=True)
class GroupRule:
    """One enforced axis of one active group: ``helper_ids`` are the active
    members, who must all have the same value on ``axis``."""

    group: ForcedGroup
    axis: str
    helper_ids: tuple[int, ...]

    @property
    def instance(self) -> RuleInstance:
        return RuleInstance(KIND, (self.group.id, self.axis))

    @property
    def max_units(self) -> int:
        return len(self.helper_ids) - 1

    def line(self, units: int, members: Optional[int] = None) -> str:
        total = len(self.helper_ids) if members is None else members
        return (
            f"Group {self.group.name} is split across {_PLURALS[self.axis]}: "
            f"{units} of {total} members placed apart from the rest"
        )


def active_helper_ids(group: ForcedGroup, helpers: Iterable[Helper]) -> list[int]:
    """The ids of the group's active members among ``helpers`` (the Season's
    attending Helpers): those carrying a member Person."""
    members = set(group.person_ids)
    return [h.id for h in helpers if h.person_id in members]


def group_rules(helpers: Sequence[Helper], groups: Iterable[ForcedGroup]) -> list[GroupRule]:
    """Every rule instance the ``groups`` state over the attending ``helpers``:
    for each group with at least two active members, one per enforced axis."""
    rules: list[GroupRule] = []
    for group in groups:
        active = tuple(active_helper_ids(group, helpers))
        if len(active) < 2:
            continue
        rules.extend(GroupRule(group, axis, active) for axis in enforced_axes(group.axes))
    return rules
