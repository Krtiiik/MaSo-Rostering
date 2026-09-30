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

from rostering import tags as tags_module
from rostering.domain import Assignment, Helper, Role, RuleInstance

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


def place_label(axis: str, a: Assignment) -> str:
    """How a violation line names where an Assignment sits on ``axis``."""
    if axis == BUILDING:
        return a.building
    if axis == ROOM:
        return a.room
    return a.role.value


def _joined(labels: Sequence[str]) -> str:
    """``A``, ``A and B``, ``A, B and C``."""
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


@dataclass(frozen=True)
class GroupRule:
    """One enforced axis of one active group: ``helper_ids`` are the active
    members (``helper_names`` their names, in the same order), who must all have
    the same value on ``axis``."""

    group: ForcedGroup
    axis: str
    helper_ids: tuple[int, ...]
    helper_names: tuple[str, ...] = ()

    @property
    def instance(self) -> RuleInstance:
        return RuleInstance(KIND, (self.group.id, self.axis))

    @property
    def max_units(self) -> int:
        return len(self.helper_ids) - 1

    def _subject(self) -> str:
        return f"Group {self.group.name} [{', '.join(self.helper_names)}]"

    def line(self, assignments: Sequence[Assignment] = ()) -> str:
        """``Group Rodina [Anna, Petr, Jana] is split across rooms N4 and N6``:
        the members' names and the distinct places the ``assignments`` of those
        members occupy on the axis (first seen first). The solver and the live
        checker word every violation through this one function."""
        by_id = {a.helper_id: a for a in assignments}
        members = [by_id[h] for h in self.helper_ids if h in by_id]
        places: dict[Hashable, Assignment] = {}
        for a in members:
            places.setdefault(place_value(self.axis, a.building, a.room, a.role.name), a)
        labels = [place_label(self.axis, a) for a in places.values()]
        if self.axis == ROOM and len(set(labels)) < len(labels):
            # The same Room name in two Buildings: say which is which.
            labels = [f"{place_label(ROOM, a)} ({a.building})" for a in places.values()]
        return f"{self._subject()} is split across {_PLURALS[self.axis].lower()}" + (
            f" {_joined(labels)}" if labels else ""
        )


def active_helpers(group: ForcedGroup, helpers: Iterable[Helper]) -> list[Helper]:
    """The group's active members among ``helpers`` (the Season's attending
    Helpers): those carrying a member Person."""
    members = set(group.person_ids)
    return [h for h in helpers if h.person_id in members]


def active_helper_ids(group: ForcedGroup, helpers: Iterable[Helper]) -> list[int]:
    return [h.id for h in active_helpers(group, helpers)]


def group_rules(helpers: Sequence[Helper], groups: Iterable[ForcedGroup]) -> list[GroupRule]:
    """Every rule instance the ``groups`` state over the attending ``helpers``:
    for each group with at least two active members, one per enforced axis."""
    rules: list[GroupRule] = []
    for group in groups:
        active = active_helpers(group, helpers)
        if len(active) < 2:
            continue
        ids, names = tuple(h.id for h in active), tuple(h.name for h in active)
        rules.extend(GroupRule(group, axis, ids, names) for axis in enforced_axes(group.axes))
    return rules


@dataclass(frozen=True)
class TagClash:
    """A group whose active members' effective allowed sets (see
    ``rostering.tags.allowed_values``) have nothing in common on a shared axis
    (``tags.BUILDING`` or ``tags.ROLE``): it could never hold. ``limits`` are the
    members Tags narrow, as ``(name, allowed values)``."""

    group: ForcedGroup
    axis: str
    limits: tuple[tuple[str, tuple[str, ...]], ...]

    def message(self) -> str:
        role = self.axis == tags_module.ROLE
        shown = [
            f"{name}: only {', '.join(Role[v].value if role else v for v in values)}"
            for name, values in self.limits[:3]
        ]
        more = len(self.limits) - len(shown)
        noun = "Role" if role else "Building"
        return f"Group {self.group.name} can't share a {noun} ({'; '.join(shown)}" + (
            f"; and {more} more)" if more > 0 else ")"
        )


def tag_clashes(
    groups: Iterable[ForcedGroup],
    helpers: Sequence[Helper],
    tags: Sequence[tags_module.Tag],
    universes: dict[str, Sequence[str]],
) -> list[TagClash]:
    """The groups (among those with two or more active members in ``helpers``,
    the attending Helpers) whose members' allowed sets have an empty
    intersection on a Building or Role axis the group shares. This is the one
    check that blocks creating or editing a group (Room implies Building, so a
    Room group is judged on Building); size, capacity and fixed Assignments never
    do. A member who has nowhere to go on the axis at all is that Helper's own
    dead end (refused by the Tag edit) and does not also count against the group.
    """
    clashes: list[TagClash] = []
    for group in groups:
        active = active_helpers(group, helpers)
        if len(active) < 2:
            continue
        for axis in (tags_module.BUILDING, tags_module.ROLE):
            universe = list(universes.get(axis) or [])
            if axis not in group.axes or not universe:
                continue
            allowed = {h.id: tags_module.allowed_values(tags, h.tags, axis, universe) for h in active}
            if any(not values for values in allowed.values()):
                continue
            common = set(universe)
            for values in allowed.values():
                common &= set(values)
            if common:
                continue
            limits = tuple((h.name, tuple(allowed[h.id])) for h in active if len(allowed[h.id]) < len(universe))
            clashes.append(TagClash(group, axis, limits))
    return clashes
