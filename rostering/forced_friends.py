"""Forced friends groups (see ``CONTEXT.md``: Forced friends group).

A group is a named hard constraint on a set of *Persons*: a list of rules that
must all hold at once. A rule is one of

- ``share``: the members must share a Building, a Room or a Role (never negated);
- ``be``: every member must (or must not) be in one of some Buildings or Rooms,
  or have one of some Roles (``values`` is the set, "any of").

Members are Persons (``person_id``), not per-Season records, so a group can
outlive a Season and resolves in the open Season to a Helper or to "not
registered". Overlapping groups are never merged.

This module holds the pure rule definition that the solver's relaxation, the
live Broken-rule checker and the mutation layer all consume, so they cannot
drift: which rules are enforced, who the *active* members are, the identity and
wording of a violation, and its size. It does no I/O and never imports the
solver.

Active member: a Helper of the Season who is not Can't attend, or an Organizer
who is placed and not Can't attend. A ``share`` rule binds from two active
members; a ``be`` rule from one. A group none of whose rules binds is dormant.

An Organizer is a member through their Person like anyone else, but only as an
*anchor*: they never move, and contribute their fixed placement to the Building
and Room rules (a Building-level Organizer holds no Room, so a room rule is
judged by their Building as far as that goes). They have no solved Role, so role
rules never apply to them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable, Iterable, Mapping, Optional, Sequence, Union

from rostering import tags as tags_module
from rostering.domain import Assignment, Helper, Organizer, Role, RuleInstance
from rostering.placement_rules import (  # noqa: F401  (the rule model is re-exported from here)
    AXES,
    AXIS_LABELS,
    BE,
    BUILDING,
    ROLE,
    ROOM,
    SHARE,
    Rule,
    RuleValue,
    _PLURALS,
    _SHARE_OBJECT,
    _canonical_values,
    _joined,
    effective_values,
    value_label,
    violates_be,
)

# The RuleInstance / BrokenRule family name of a group's rules.
KIND = "forced_friends"


def share_rules(*axes: str) -> tuple[Rule, ...]:
    """``share`` rules for ``axes`` (a convenience for tests and migration)."""
    return tuple(Rule.share(axis) for axis in axes)


def normalize_rules(items: Iterable[Union[Rule, Mapping[str, Any]]]) -> tuple[Rule, ...]:
    """The rules of a group from ``Rule``s or their saved dicts. ``ValueError``
    (Czech) for none, a malformed one, or a repeat."""
    rules = tuple(Rule.from_dict(item) for item in items or [])
    if not rules:
        raise ValueError("Přidejte skupince alespoň jedno pravidlo.")
    seen: set[str] = set()
    for rule in rules:
        if rule.key in seen:
            raise ValueError(f"Pravidlo se opakuje: {rule.text()}.")
        seen.add(rule.key)
    return rules


def legacy_rules(axes: Iterable[str]) -> list[dict[str, Any]]:
    """A group saved before rules existed carried the axes it shared (Room
    implying Building); each is a ``share`` rule, the implied Building left out."""
    ticked = [a for a in AXES if a in set(axes)]
    return [{"kind": SHARE, "axis": a} for a in ticked if not (a == BUILDING and ROOM in ticked)]


def record_rules(record: Mapping[str, Any]) -> list[Rule]:
    """The rules of a saved group record, whichever shape it was saved in."""
    if "rules" in record:
        return [Rule.from_dict(r) for r in record["rules"] or []]
    return [Rule.from_dict(r) for r in legacy_rules(record.get("axes") or [])]


def migrate_state(state: dict[str, Any]) -> bool:
    """Rewrite the groups of a saved ``state`` that predate rules (``axes``) into
    ``rules``, in place. Returns whether anything changed."""
    changed = False
    for record in state.get("forced_groups") or []:
        if "rules" not in record:
            record["rules"] = legacy_rules(record.pop("axes", None) or [])
            changed = True
    return changed


def effective_rules(rules: Iterable[Rule]) -> frozenset[str]:
    """What a set of rules demands, for telling two groups' rules apart: a shared
    Room is a shared Building, so ``share building`` next to ``share room`` adds
    nothing."""
    rules = list(rules)
    shares = {r.axis for r in rules if r.kind == SHARE}
    return frozenset(r.key for r in rules if not (r.kind == SHARE and r.axis == BUILDING and ROOM in shares))


@dataclass(frozen=True)
class ForcedGroup:
    """A Forced friends group: its ``rules`` (all must hold) and the
    ``person_ids`` of its members."""

    id: int
    name: str
    rules: tuple[Rule, ...]
    person_ids: tuple[str, ...]
    # Set on a group derived from a Tag's ``share`` rules (see :func:`tag_groups`):
    # the Tag it comes from. Such a group is never saved, and its ``id`` is the
    # negative of the Tag's, so it cannot meet a saved group's.
    tag_id: Optional[int] = None

    @property
    def share_axes(self) -> tuple[str, ...]:
        """The axes its ``share`` rules name, in the canonical order."""
        shared = {r.axis for r in self.rules if r.kind == SHARE}
        return tuple(a for a in AXES if a in shared)

    @property
    def be_rules(self) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.kind == BE)


def enforced_axes(axes: Sequence[str]) -> tuple[str, ...]:
    """The share axes that are checked and bent on their own: Room subsumes
    Building (a shared Room is a shared Building), so a Room group is judged on
    Room."""
    return tuple(axis for axis in axes if not (axis == BUILDING and ROOM in axes))


def group_to_dict(group: ForcedGroup, names: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """The saved form: ``members`` keep the last-known name of each Person, so a
    member who is not registered this Season can still be named."""
    names = names or {}
    return {
        "id": group.id,
        "name": group.name,
        "rules": [r.to_dict() for r in group.rules],
        "members": [{"person_id": p, "name": names.get(p, "")} for p in group.person_ids],
    }


def group_from_dict(data: dict[str, Any]) -> ForcedGroup:
    return ForcedGroup(
        id=int(data["id"]),
        name=data["name"],
        rules=tuple(record_rules(data)),
        person_ids=tuple(m["person_id"] for m in data.get("members") or []),
    )


def groups_from_state(state: dict[str, Any]) -> list[ForcedGroup]:
    """The groups saved in a Season's state (``state["forced_groups"]``; a state
    saved before groups existed has none)."""
    return [group_from_dict(g) for g in state.get("forced_groups") or []]


def tag_groups(
    tag_defs: Sequence[tags_module.Tag], helpers: Iterable[Helper], organizers: Iterable[Organizer] = ()
) -> list[ForcedGroup]:
    """The groups a Tag's ``share`` rules stand for: for each Tag with any, one
    group of every Person carrying it, directly or through a Tag that implies it,
    bound by that Tag's ``share`` rules. They run through the same
    :func:`group_rules` as saved groups, so the solver, the live check and the
    wording cannot drift. A Tag nobody carries makes none."""
    tag_defs = list(tag_defs)
    sharing = [t for t in tag_defs if any(r.kind == SHARE for r in t.rules)]
    if not sharing:
        return []
    carriers: dict[int, list[str]] = {t.id: [] for t in sharing}
    for person in (*helpers, *organizers):
        if not person.person_id:
            continue
        for tag_id in tags_module.effective_tag_ids(tag_defs, person.tags):
            if tag_id in carriers and person.person_id not in carriers[tag_id]:
                carriers[tag_id].append(person.person_id)
    return [
        ForcedGroup(
            id=-tag.id,
            name=tag.name,
            rules=tuple(r for r in tag.rules if r.kind == SHARE),
            person_ids=tuple(carriers[tag.id]),
            tag_id=tag.id,
        )
        for tag in sharing
        if carriers[tag.id]
    ]


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


def be_place_label(axis: str, a: Assignment) -> str:
    """Where an Assignment stands on a ``be`` rule's ``axis``, for a violation line."""
    if axis == BUILDING:
        return a.building
    if axis == ROOM:
        return f"{a.room} ({a.building})"
    return a.role.value


@dataclass(frozen=True)
class Anchor:
    """A placed Organizer member: never moved, they hold the group to their
    placement (``room`` is None for a Building-level Organizer)."""

    organizer_id: int
    name: str
    building: str
    room: Optional[str] = None

    def value(self, axis: str) -> Hashable:
        """Where they stand on ``axis``, comparable with :func:`place_value`."""
        return self.building if axis == BUILDING else (self.building, self.room)

    def label(self, axis: str) -> str:
        return self.building if axis == BUILDING else self.room or ""

    def violates(self, rule: Rule, values: Sequence[RuleValue]) -> bool:
        """Whether this Organizer breaks the ``be`` ``rule``. Role rules never
        apply to them. A Building-level Organizer holds no Room, so a room rule
        is judged by their Building: a "must" breaks only if the Building holds
        none of the rooms named, a "must not" never does."""
        if rule.axis == BUILDING:
            return (self.building in values) != rule.must
        if rule.axis == ROOM:
            if self.room:
                return ((self.building, self.room) in values) != rule.must
            return rule.must and self.building not in {b for b, _room in values}
        return False

    def place(self, axis: str) -> str:
        """Where they stand, for a violation line."""
        if axis == ROOM and self.room:
            return f"{self.room} ({self.building})"
        return self.building


@dataclass(frozen=True)
class GroupRule:
    """One enforced rule of one group, over the active Helper members
    (``helper_ids``, ``helper_names`` their names in the same order) and the
    placed Organizers who count on it (``anchors``).

    A ``share`` rule (``rule`` None) is one enforced axis: all of them must have
    the same value on ``axis``. A ``be`` rule is judged per member against
    ``values``, its values that this Season's layout still has."""

    group: ForcedGroup
    axis: str
    helper_ids: tuple[int, ...]
    helper_names: tuple[str, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    rule: Optional[Rule] = None
    values: tuple[RuleValue, ...] = ()

    @property
    def key(self) -> str:
        return self.rule.key if self.rule is not None else f"share:{self.axis}"

    @property
    def instance(self) -> RuleInstance:
        return RuleInstance(KIND, (self.group.id, self.key))

    @property
    def size(self) -> int:
        return len(self.helper_ids) + len(self.anchors)

    @property
    def max_units(self) -> int:
        return self.size - 1 if self.rule is None else self.size

    def violating_anchors(self) -> tuple[Anchor, ...]:
        """The Organizers who break a ``be`` rule whatever the roster does."""
        if self.rule is None:
            return ()
        return tuple(a for a in self.anchors if a.violates(self.rule, self.values))

    def _subject(self) -> str:
        names = [*self.helper_names, *(a.name for a in self.anchors)]
        noun = "Štítek" if self.group.tag_id is not None else "Skupinka"
        return f"{noun} {self.group.name} [{', '.join(names)}]"

    def line(self, assignments: Sequence[Assignment] = ()) -> str:
        """The violation in words, from the members' ``assignments`` (and the
        anchors' fixed placement). The solver and the live checker word every
        violation through this one function."""
        if self.rule is not None:
            return self._be_line(assignments)
        by_id = {a.helper_id: a for a in assignments}
        # (value, label, building) of every member whose place is known.
        spots: list[tuple[Hashable, str, str]] = [
            (place_value(self.axis, a.building, a.room, a.role.name), place_label(self.axis, a), a.building)
            for a in (by_id[h] for h in self.helper_ids if h in by_id)
        ]
        spots += [(anchor.value(self.axis), anchor.label(self.axis), anchor.building) for anchor in self.anchors]
        places: dict[Hashable, tuple[str, str]] = {}
        for value, label, building in spots:
            places.setdefault(value, (label, building))
        labels = [label for label, _building in places.values()]
        if self.axis == ROOM and len(set(labels)) < len(labels):
            # The same Room name in two Buildings: say which is which.
            labels = [f"{label} ({building})" for label, building in places.values()]
        split = "rozdělen" if self.group.tag_id is not None else "rozdělena"
        return f"{self._subject()} je {split} mezi {_PLURALS[self.axis]}" + (
            f" {_joined(labels)}" if labels else ""
        )

    def offenders(self, assignments: Sequence[Assignment]) -> list[tuple[str, str]]:
        """``(name, where)`` of each member breaking this ``be`` rule in the
        given ``assignments``: Helpers by their Assignment, Organizers by their
        placement."""
        assert self.rule is not None
        by_id = {a.helper_id: a for a in assignments}
        found = []
        for helper_id, name in zip(self.helper_ids, self.helper_names):
            a = by_id.get(helper_id)
            if a is not None and violates_be(self.rule, self.values, a.building, a.room, a.role.name):
                found.append((name, be_place_label(self.axis, a)))
        found += [(f"{a.name} (organizátor)", a.place(self.axis)) for a in self.violating_anchors()]
        return found

    def _be_line(self, assignments: Sequence[Assignment]) -> str:
        assert self.rule is not None
        text = f"Skupinka {self.group.name}: pravidlo „{self.rule.text()}“"
        offenders = self.offenders(assignments)
        if not offenders:
            return f"{text} neplatí"
        return f"{text} porušují {_joined([f'{name} ({where})' for name, where in offenders])}"


def active_helpers(group: ForcedGroup, helpers: Iterable[Helper]) -> list[Helper]:
    """The group's active members among ``helpers`` (the Season's attending
    Helpers): those carrying a member Person."""
    members = set(group.person_ids)
    return [h for h in helpers if h.person_id in members]


def active_helper_ids(group: ForcedGroup, helpers: Iterable[Helper]) -> list[int]:
    return [h.id for h in active_helpers(group, helpers)]


def active_organizers(group: ForcedGroup, organizers: Iterable[Organizer]) -> list[Organizer]:
    """The group's active Organizer members among ``organizers`` (the Season's
    attending Organizers): the placed ones. An unplaced Organizer is dormant."""
    members = set(group.person_ids)
    return [o for o in organizers if o.person_id in members and o.building]


def active_member_count(group: ForcedGroup, helpers: Iterable[Helper], organizers: Iterable[Organizer] = ()) -> int:
    """How many active members the group has."""
    return len(active_helpers(group, helpers)) + len(active_organizers(group, organizers))


def in_force(group: ForcedGroup, active_count: int) -> bool:
    """Whether any rule of the group binds with ``active_count`` active members:
    a ``share`` rule needs two, a ``be`` rule one."""
    if active_count >= 2:
        return bool(group.rules)
    return active_count >= 1 and bool(group.be_rules)


def group_rules(
    helpers: Sequence[Helper],
    groups: Iterable[ForcedGroup],
    organizers: Iterable[Organizer] = (),
    buildings: Optional[Mapping[str, Iterable[str]]] = None,
) -> list[GroupRule]:
    """Every rule instance the ``groups`` state over the attending ``helpers`` and
    ``organizers``.

    ``share`` rules: for each enforced axis of a group, one rule over the members
    that count on it (two or more of them). The Role axis takes Helpers only. On
    the Room axis a placed Organizer counts if they hold a Room; one who leads a
    whole Building counts on the Building, so a Room group with such an
    Organizer also gets a Building rule.

    ``be`` rules: one per rule, over every active member (one is enough). A rule
    whose values the layout no longer has at all is inert and left out.
    ``buildings`` (Building name -> its Room names), when given, drops an anchor
    whose placement the configuration no longer has."""
    known = {name: set(rooms) for name, rooms in buildings.items()} if buildings is not None else None
    rules: list[GroupRule] = []
    for group in groups:
        active = active_helpers(group, helpers)
        anchors = [
            Anchor(o.id, o.name, o.building, o.room or None)
            for o in active_organizers(group, organizers)
            if known is None or (o.building in known and (not o.room or o.room in known[o.building]))
        ]
        shared = group.share_axes
        axes = list(enforced_axes(shared))
        if ROOM in shared and any(a.room is None for a in anchors):
            axes.insert(0, BUILDING)
        ids, names = tuple(h.id for h in active), tuple(h.name for h in active)
        for axis in axes:
            if axis == ROLE:
                on_axis: tuple[Anchor, ...] = ()
            elif axis == ROOM:
                on_axis = tuple(a for a in anchors if a.room)
            else:
                on_axis = tuple(anchors)
            rule = GroupRule(group, axis, ids, names, on_axis)
            if rule.size >= 2:
                rules.append(rule)
        for be in group.be_rules:
            values = effective_values(be, buildings)
            if not values:
                continue
            on_axis = () if be.axis == ROLE else tuple(anchors)
            rule = GroupRule(group, be.axis, ids, names, on_axis, rule=be, values=values)
            if rule.size >= 1:
                rules.append(rule)
    return rules


# -- Provable contradictions between a group's rules -------------------------------


def contradictions(rules: Sequence[Rule], buildings: Mapping[str, Iterable[str]]) -> list[str]:
    """The ways a group's ``be`` rules cannot all hold for the same member
    whatever the roster is (every member must meet every rule), as Czech
    messages. Judged against the layout (Building name -> its Room names):
    values it does not have are inert, as everywhere. ``share`` rules never
    contradict anything provably (they depend on the roster)."""
    be = [r for r in rules if r.kind == BE]
    problems: list[str] = []

    roles = [r for r in be if r.axis == ROLE]
    allowed_roles = set(Role.__members__)
    for rule in roles:
        values = set(rule.values)
        allowed_roles = allowed_roles & values if rule.must else allowed_roles - values
    if roles and not allowed_roles:
        problems.append("žádná role nevyhovuje všem pravidlům o roli: " + "; ".join(r.text() for r in roles))

    layout = {name: list(rooms) for name, rooms in buildings.items()}
    places = [r for r in be if r.axis in (BUILDING, ROOM)]
    building_rules = [(r, set(effective_values(r, layout))) for r in places if r.axis == BUILDING]
    room_rules = [(r, set(effective_values(r, layout))) for r in places if r.axis == ROOM]
    # A "must" naming only places the layout lacks is inert (it narrows nothing).
    building_rules = [(r, v) for r, v in building_rules if v or not r.must]
    room_rules = [(r, v) for r, v in room_rules if v or not r.must]
    if building_rules or room_rules:
        texts = "; ".join(r.text() for r in places)

        def building_ok(name: str) -> bool:
            return all((name in v) == r.must for r, v in building_rules)

        open_buildings = [b for b in layout if building_ok(b)]
        if not open_buildings:
            problems.append("žádná budova nevyhovuje všem pravidlům o budově: " + texts)
        elif room_rules:
            rooms_ok = [
                (b, room)
                for b in open_buildings
                for room in layout[b]
                if all(((b, room) in v) == r.must for r, v in room_rules)
            ]
            if not rooms_ok:
                problems.append("žádná místnost nevyhovuje všem pravidlům o budově a místnosti: " + texts)
    return problems


# -- Tags against the rules --------------------------------------------------------


@dataclass(frozen=True)
class TagClash:
    """A group that could never hold because of its active members' Tags, on a
    Building or Role axis (``tags.BUILDING`` / ``tags.ROLE``): either their
    effective allowed sets (see ``rostering.tags.allowed_values``) have nothing in
    common on an axis the group shares, or they leave a member nothing the group's
    ``be`` rules (``rules``, their words) allow. ``limits`` are the members Tags
    narrow, as ``(name, allowed values)``."""

    group: ForcedGroup
    axis: str
    limits: tuple[tuple[str, tuple[str, ...]], ...]
    rules: tuple[str, ...] = ()

    def message(self) -> str:
        role = self.axis == tags_module.ROLE
        shown = [
            f"{name}: jen {', '.join(Role[v].value if role else v for v in values)}"
            for name, values in self.limits[:3]
        ]
        more = len(self.limits) - len(shown)
        detail = "; ".join(shown) + (f"; a dalších {more}" if more > 0 else "")
        if self.rules:
            return (
                f"Skupinka {self.group.name} nemůže splnit svá pravidla ({'; '.join(self.rules)}) "
                f"se štítky členů ({detail})"
            )
        noun = "roli" if role else "budovu"
        return f"Skupinka {self.group.name} nemůže sdílet {noun} ({detail})"


def _listed_values(group: ForcedGroup, axis: str, universe: Sequence[str]) -> Optional[tuple[set[str], tuple[str, ...]]]:
    """What the group's ``be`` rules allow every member on the Tag ``axis``:
    ``(allowed values, the rules' words)``, or None when no rule speaks to that
    axis. Room rules narrow the Buildings too (a "must be in room X" is a must be
    in X's Building); values the universe lacks are inert."""
    allowed = set(universe)
    texts: list[str] = []
    for rule in group.be_rules:
        if axis == tags_module.ROLE:
            if rule.axis != ROLE:
                continue
            values = {v for v in rule.values if v in universe}
        elif rule.axis == BUILDING:
            values = {v for v in rule.values if v in universe}
        elif rule.axis == ROOM and rule.must:
            values = {b for b, _room in rule.values if b in universe}
        else:
            continue
        if not values and rule.must:
            continue  # names nothing this Season has: inert
        allowed = allowed & values if rule.must else allowed - values
        texts.append(rule.text())
    return (allowed, tuple(texts)) if texts else None


def tag_clashes(
    groups: Iterable[ForcedGroup],
    helpers: Sequence[Helper],
    tags: Sequence[tags_module.Tag],
    universes: dict[str, Sequence[str]],
) -> list[TagClash]:
    """The groups (among those with an active member in ``helpers``, the
    attending Helpers) that their members' Tags make impossible on a Building or
    Role axis: with two or more active members and a rule sharing that axis, the
    members' allowed sets (intersected with what the ``be`` rules allow) have
    nothing in common; with a ``be`` rule on the axis, some member's allowed set
    has nothing the rules allow. At most one clash per group and axis. This is the
    one check that blocks creating or editing a group (Room implies Building, so a
    Room group is judged on Building); size, capacity and fixed Assignments never
    do. A member who has nowhere to go on the axis at all is that Helper's own
    dead end (refused by the Tag edit) and does not also count against the group.
    """
    clashes: list[TagClash] = []
    for group in groups:
        active = active_helpers(group, helpers)
        if not active:
            continue
        shared = set(group.share_axes)
        for axis in (tags_module.BUILDING, tags_module.ROLE):
            universe = list(universes.get(axis) or [])
            if not universe:
                continue
            shares = bool(shared & ({BUILDING, ROOM} if axis == tags_module.BUILDING else {ROLE})) and len(active) >= 2
            listed = _listed_values(group, axis, universe)
            if not shares and listed is None:
                continue
            allowed = {h.id: tags_module.allowed_values(tags, h.tags, axis, universe) for h in active}
            if any(not values for values in allowed.values()):
                continue
            rule_words = listed[1] if listed else ()
            permitted = listed[0] if listed else set(universe)
            if shares:
                common = set(universe)
                for values in allowed.values():
                    common &= set(values)
                if common & permitted:
                    continue
                limits = tuple((h.name, tuple(allowed[h.id])) for h in active if len(allowed[h.id]) < len(universe))
                if not limits:
                    # Every member is unrestricted: only the rules themselves leave nothing (a contradiction).
                    continue
                words = rule_words if common else ()
                clashes.append(TagClash(group, axis, limits, words))
                continue
            stuck = tuple(
                (h.name, tuple(allowed[h.id])) for h in active if not (set(allowed[h.id]) & permitted)
            )
            if stuck:
                clashes.append(TagClash(group, axis, stuck, rule_words))
    return clashes
