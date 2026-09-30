"""Hard rules of the solve, relaxed into strict priority tiers.

A solve never fails because the hard rules clash (see CONTEXT.md "Broken
rule"): every hard rule is given a *slack* — the size of its violation — that
the solver pays a penalty for, so it always returns a full roster and reports
the rules it had to bend. The tiers bend in a fixed order, first to last:

1. ``MINIMUMS`` — Room and Building role minimums;
2. ``TAG_RESTRICTIONS`` — Tag constraints on Building/Role;
3. ``FORCED_FRIENDS`` — Forced-friend groups;
4. ``EQUIPMENT`` — Equipment eligibility (Fotograf needs a camera).

The order is fixed in code, not configurable. Tier weights are
*dominance-ordered*: one unit of violation in a stricter tier costs more than
every cheaper tier could ever add together, and any rule penalty costs more
than the ordinary preference/friend objective can ever add. So a stricter
rule is never bent to save a cheaper one, and among rosters that break the
same rules the ordinary objective still decides (see ``tier_weights``).

Never relaxed, because they are structural rather than rules: one Room and
one Role per Helper, and fixed Assignments (see ``solve_competition``'s
``fixed_assignments``).

Extension point
---------------
A later rule family (as Tag constraints and Forced-friend groups already do) plugs in by
building a ``RuleFamily`` and passing it through ``register_rule_family``
(or to ``solve_competition(families=...)``), with no change to the model:

- ``RuleFamily.relax(ctx)`` adds the family's constraints to ``ctx.model``,
  each guarded by a slack, and returns one ``Relaxation`` per rule instance;
- each ``Relaxation`` carries the ``RuleInstance`` identity (rule kind plus
  entity) that the family's live checker must emit for the same violation;
- ``RuleFamily.check(ctx)`` is the family's live checker: given the current
  Assignments (``CheckContext``) it returns one ``BrokenRule`` per violated
  instance — with the same identity, family, amount and line the relaxation
  reports, plus the grid cells/chips it affects and its "Go fix" target
  (``rostering.solver.checker`` runs every registered family's check). A
  family without a ``check`` cannot be registered, so a rule cannot be added
  to only one of the two; the agreement tests keep the copies from drifting;
- ``RuleFamily.tier`` picks the priority among the four tiers above; every
  tier except ``MINIMUMS`` is also announced by the transient toast after a
  hand move (minimums routinely dip mid-edit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional, Sequence

from ortools.sat.python import cp_model

from rostering import forced_friends, tags as tags_module
from rostering.domain import (
    Assignment,
    Building,
    BrokenRule,
    Competition,
    FixTarget,
    Helper,
    Role,
    Room,
    RuleInstance,
)


class Tier(IntEnum):
    """Bending order, first to last: a higher tier is stricter, so it is
    bent only when no lower tier's bending can avoid it."""

    MINIMUMS = 0
    TAG_RESTRICTIONS = 1
    FORCED_FRIENDS = 2
    EQUIPMENT = 3


@dataclass
class ModelContext:
    """What a rule family needs to state its rules over the solver model."""

    model: cp_model.CpModel
    helpers: list[Helper]
    buildings: list[Building]
    # Flattened (building name, Room), indexed by room id.
    rooms: list[tuple[str, Room]]
    building_rooms: dict[str, list[int]]
    roles: list[Role]
    assign_room: dict[tuple[int, int], cp_model.IntVar]
    assign_role: dict[tuple[int, Role], cp_model.IntVar]
    # role_room_var[helper_id, role, room_id]: helper has that role in that room.
    role_room_var: dict[tuple[int, Role, int], cp_model.IntVar]
    # The Season's Tag definitions; each Helper carries its direct Tag ids.
    tags: list[tags_module.Tag] = field(default_factory=list)
    # The Season's Forced friends groups (members resolved against ``helpers``).
    forced_groups: list[forced_friends.ForcedGroup] = field(default_factory=list)


@dataclass
class Relaxation:
    """One relaxed rule instance: ``slack`` is a non-negative expression that
    is exactly the size of the violation (0 when the rule holds), at most
    ``max_units``; ``describe`` words a violation of a given size."""

    instance: RuleInstance
    slack: cp_model.LinearExprT
    max_units: int
    describe: Callable[[int], str]
    # Optionally words the violation from the finished roster (it needs to say
    # where people ended up, which no slack knows); ``describe`` is the fallback.
    describe_placed: Optional[Callable[[int, Sequence[Assignment]], str]] = None


@dataclass
class CheckContext:
    """What a rule family's live check judges: the Season's configuration and
    Helpers plus the roster as it currently stands."""

    competition: Competition
    assignments: list[Assignment]


@dataclass(frozen=True)
class RuleFamily:
    name: str
    tier: Tier
    relax: Callable[[ModelContext], list[Relaxation]]
    # The live checker; required to register the family (see
    # ``register_rule_family``), optional here so a family can still be handed
    # to the solver alone.
    check: Optional[Callable[[CheckContext], list[BrokenRule]]] = None


def _minimums(ctx: ModelContext) -> list[Relaxation]:
    relaxations: list[Relaxation] = []

    def shortfall(name: str, minimum: int, terms: list) -> cp_model.IntVar:
        # Exactly max(0, minimum - count), so the reported violation is
        # right even when the search stops short of optimal.
        slack = ctx.model.NewIntVar(0, minimum, name)
        ctx.model.AddMaxEquality(slack, [0, minimum - sum(terms)])
        return slack

    for room_id, (bname, room) in enumerate(ctx.rooms):
        for role, cap in room.capacities.items():
            if not cap.minimum:
                continue
            terms = [ctx.role_room_var[h.id, role, room_id] for h in ctx.helpers]
            relaxations.append(
                Relaxation(
                    instance=RuleInstance("room_minimum", (bname, room.name, role.name)),
                    slack=shortfall(f"short_room{room_id}_{role.name}", cap.minimum, terms),
                    max_units=cap.minimum,
                    describe=_minimum_line(f"Room {room.name}", role, cap.minimum),
                )
            )

    for building in ctx.buildings:
        room_ids = ctx.building_rooms.get(building.name, [])
        for role, cap in building.capacities.items():
            if not cap.minimum:
                continue
            terms = [ctx.role_room_var[h.id, role, rid] for rid in room_ids for h in ctx.helpers]
            relaxations.append(
                Relaxation(
                    instance=RuleInstance("building_minimum", (building.name, role.name)),
                    slack=shortfall(f"short_building_{building.name}_{role.name}", cap.minimum, terms),
                    max_units=cap.minimum,
                    describe=_minimum_line(f"Building {building.name}", role, cap.minimum),
                )
            )
    return relaxations


def _minimum_line(where: str, role: Role, minimum: int) -> Callable[[int], str]:
    return lambda short: f"{where} · {role.value}: {minimum - short} of {minimum} required (needs {short} more)"


def _equipment_line(helper_name: str) -> str:
    return f"Helper {helper_name} has no camera but is Fotograf"


def _equipment(ctx: ModelContext) -> list[Relaxation]:
    # Camera/Fotograf only — the notebook/Kreslič rule was removed;
    # can_bring_notebook is display-only now.
    return [
        Relaxation(
            instance=RuleInstance("equipment", (h.id,)),
            slack=ctx.assign_role[h.id, Role.Fotograf],
            max_units=1,
            describe=lambda _short, name=h.name: _equipment_line(name),
        )
        for h in ctx.helpers
        if not h.can_bring_camera
    ]


def _check_minimums(ctx: CheckContext) -> list[BrokenRule]:
    # Counted over the Rooms the configuration still has, like the solver's
    # own counts: an Assignment to a removed Room contributes to nothing.
    counts: dict[tuple[str, str, Role], int] = {}
    known_rooms = {(b.name, r.name) for b in ctx.competition.buildings.values() for r in b.rooms}
    for a in ctx.assignments:
        if (a.building, a.room) in known_rooms:
            counts[a.building, a.room, a.role] = counts.get((a.building, a.room, a.role), 0) + 1

    broken: list[BrokenRule] = []
    for building in ctx.competition.buildings.values():
        for room in building.rooms:
            for role, cap in room.capacities.items():
                short = cap.minimum - counts.get((building.name, room.name, role), 0)
                if cap.minimum and short > 0:
                    broken.append(
                        BrokenRule(
                            instance=RuleInstance("room_minimum", (building.name, room.name, role.name)),
                            family="minimums",
                            amount=short,
                            line=_minimum_line(f"Room {room.name}", role, cap.minimum)(short),
                            cells=((building.name, room.name, role.name),),
                            fix=FixTarget("buildings", building=building.name, room=room.name, role=role.name),
                        )
                    )
    for building in ctx.competition.buildings.values():
        for role, cap in building.capacities.items():
            have = sum(counts.get((building.name, room.name, role), 0) for room in building.rooms)
            short = cap.minimum - have
            if cap.minimum and short > 0:
                broken.append(
                    BrokenRule(
                        instance=RuleInstance("building_minimum", (building.name, role.name)),
                        family="minimums",
                        amount=short,
                        line=_minimum_line(f"Building {building.name}", role, cap.minimum)(short),
                        cells=tuple((building.name, room.name, role.name) for room in building.rooms),
                        fix=FixTarget("buildings", building=building.name, role=role.name),
                    )
                )
    return broken


def _check_equipment(ctx: CheckContext) -> list[BrokenRule]:
    helpers = {h.id: h for h in ctx.competition.helpers}
    broken: list[BrokenRule] = []
    for a in ctx.assignments:
        helper = helpers.get(a.helper_id)
        if helper is None or helper.can_bring_camera or a.role != Role.Fotograf:
            continue
        broken.append(
            BrokenRule(
                instance=RuleInstance("equipment", (helper.id,)),
                family="equipment",
                amount=1,
                line=_equipment_line(helper.name),
                cells=((a.building, a.room, None),),
                helper_ids=(helper.id,),
                fix=FixTarget("helpers", helper_id=helper.id),
            )
        )
    return broken


def _role_display(name: str) -> str:
    return Role[name].value


def _tag_line(helper_name: str, blockers: list[tags_module.Restriction], axis: str, value: str) -> str:
    """``Helper Anna (Tag 8.M, allows only Building Karlín) is placed in
    Impakt`` -- the restrictions that keep the value out, the value itself."""
    display = _role_display if axis == tags_module.ROLE else str
    why = "; ".join(tags_module.describe_restriction(r, axis, display) for r in blockers)
    placed = f"as {display(value)}" if axis == tags_module.ROLE else f"in {value}"
    return f"Helper {helper_name} ({why}) is placed {placed}"


def _tag_universes(buildings: list[str], roles: list[Role]) -> dict[str, list[str]]:
    return {tags_module.BUILDING: list(buildings), tags_module.ROLE: [r.name for r in roles]}


_TAG_KINDS = {tags_module.BUILDING: "tag_building", tags_module.ROLE: "tag_role"}


def _tag_restrictions(ctx: ModelContext) -> list[Relaxation]:
    """Each Helper's allowed Buildings and Roles from their effective Tag
    constraints (see ``rostering.tags``): one relaxation per Building/Role the
    Helper may not be in, whose slack is 1 exactly when they are placed there."""
    relaxations: list[Relaxation] = []
    universes = _tag_universes([b.name for b in ctx.buildings], ctx.roles)
    for helper in ctx.helpers:
        if not helper.tags:
            continue
        for axis, universe in universes.items():
            found = tags_module.restrictions(ctx.tags, helper.tags, axis, universe)
            for value in universe:
                blockers = tags_module.blocking(found, value)
                if not blockers:
                    continue
                if axis == tags_module.BUILDING:
                    room_ids = ctx.building_rooms.get(value, [])
                    if not room_ids:
                        continue
                    slack = sum(ctx.assign_room[helper.id, room_id] for room_id in room_ids)
                else:
                    slack = ctx.assign_role[helper.id, Role[value]]
                relaxations.append(
                    Relaxation(
                        instance=RuleInstance(_TAG_KINDS[axis], (helper.id, value)),
                        slack=slack,
                        max_units=1,
                        describe=lambda _short, line=_tag_line(helper.name, blockers, axis, value): line,
                    )
                )
    return relaxations


def _check_tag_restrictions(ctx: CheckContext) -> list[BrokenRule]:
    comp = ctx.competition
    if not comp.tags:
        return []
    helpers = {h.id: h for h in comp.helpers}
    universes = _tag_universes([b.name for b in comp.buildings.values()], list(Role))
    broken: list[BrokenRule] = []
    for a in ctx.assignments:
        helper = helpers.get(a.helper_id)
        if helper is None or not helper.tags:
            continue
        for axis, value in ((tags_module.BUILDING, a.building), (tags_module.ROLE, a.role.name)):
            # A Building the configuration no longer has is judged by nothing.
            if value not in universes[axis]:
                continue
            blockers = tags_module.blocking(tags_module.restrictions(comp.tags, helper.tags, axis, universes[axis]), value)
            if not blockers:
                continue
            broken.append(
                BrokenRule(
                    instance=RuleInstance(_TAG_KINDS[axis], (helper.id, value)),
                    family="tag_restrictions",
                    amount=1,
                    line=_tag_line(helper.name, blockers, axis, value),
                    cells=((a.building, a.room, None),),
                    helper_ids=(helper.id,),
                    fix=FixTarget("tags", helper_id=helper.id, tag_id=blockers[0].tag.id),
                )
            )
    return broken


def _forced_friends(ctx: ModelContext) -> list[Relaxation]:
    """Each active Forced friends group's enforced axes (see
    ``rostering.forced_friends.group_rules``): the slack is the number of
    members placed apart from the largest party sharing a value on the axis,
    exactly 0 when they all share it. Groups are independent, so overlapping
    ones are never merged."""
    relaxations: list[Relaxation] = []
    for rule in forced_friends.group_rules(ctx.helpers, ctx.forced_groups):
        counts = []
        if rule.axis == forced_friends.BUILDING:
            for room_ids in ctx.building_rooms.values():
                counts.append(sum(ctx.assign_room[h, rid] for h in rule.helper_ids for rid in room_ids))
        elif rule.axis == forced_friends.ROOM:
            for rid in range(len(ctx.rooms)):
                counts.append(sum(ctx.assign_room[h, rid] for h in rule.helper_ids))
        else:
            for role in ctx.roles:
                counts.append(sum(ctx.assign_role[h, role] for h in rule.helper_ids))
        size = len(rule.helper_ids)
        largest = ctx.model.NewIntVar(0, size, f"forced_{rule.group.id}_{rule.axis}_largest")
        ctx.model.AddMaxEquality(largest, counts)
        slack = ctx.model.NewIntVar(0, size - 1, f"forced_{rule.group.id}_{rule.axis}_apart")
        ctx.model.Add(slack == size - largest)
        relaxations.append(
            Relaxation(
                instance=rule.instance,
                slack=slack,
                max_units=rule.max_units,
                describe=lambda _units, rule=rule: rule.line(),
                describe_placed=lambda _units, assignments, rule=rule: rule.line(assignments),
            )
        )
    return relaxations


def _check_forced_friends(ctx: CheckContext) -> list[BrokenRule]:
    comp = ctx.competition
    if not comp.forced_groups:
        return []
    placed = {a.helper_id: a for a in ctx.assignments}
    known_rooms = {(b.name, r.name) for b in comp.buildings.values() for r in b.rooms}
    helpers = {h.id: h for h in comp.helpers}
    broken: list[BrokenRule] = []
    for rule in forced_friends.group_rules(comp.helpers, comp.forced_groups):
        # A member with no Assignment, or one in a Room the configuration no
        # longer has, is judged by nothing (like the other families).
        members = [
            placed[h]
            for h in rule.helper_ids
            if h in placed and (placed[h].building, placed[h].room) in known_rooms
        ]
        units = forced_friends.split_units(
            [forced_friends.place_value(rule.axis, a.building, a.room, a.role.name) for a in members]
        )
        if not units:
            continue
        broken.append(
            BrokenRule(
                instance=rule.instance,
                family="forced_friends",
                amount=units,
                line=rule.line(members),
                cells=tuple(dict.fromkeys((a.building, a.room, None) for a in members)),
                helper_ids=tuple(a.helper_id for a in members),
                fix=FixTarget("forced_friends", group_id=rule.group.id),
            )
        )
    return broken


MINIMUMS_FAMILY = RuleFamily("minimums", Tier.MINIMUMS, _minimums, check=_check_minimums)
TAG_RESTRICTIONS_FAMILY = RuleFamily(
    "tag_restrictions", Tier.TAG_RESTRICTIONS, _tag_restrictions, check=_check_tag_restrictions
)
FORCED_FRIENDS_FAMILY = RuleFamily(
    "forced_friends", Tier.FORCED_FRIENDS, _forced_friends, check=_check_forced_friends
)
EQUIPMENT_FAMILY = RuleFamily("equipment", Tier.EQUIPMENT, _equipment, check=_check_equipment)

_registry: list[RuleFamily] = [MINIMUMS_FAMILY, TAG_RESTRICTIONS_FAMILY, FORCED_FRIENDS_FAMILY, EQUIPMENT_FAMILY]


def register_rule_family(family: RuleFamily) -> None:
    """Add a rule family to every later solve and live check (see the module
    docstring). Refuses a family with no live ``check``."""
    if family.check is None:
        raise ValueError(f"Rule family {family.name} has no live check; a rule must be stated for both")
    if any(existing.name == family.name for existing in _registry):
        raise ValueError(f"Rule family already registered: {family.name}")
    _registry.append(family)


def rule_families() -> list[RuleFamily]:
    return list(_registry)


def tier_weights(ordinary_max: int, max_units_by_tier: dict[Tier, int]) -> dict[Tier, int]:
    """Dominance-ordered penalty per unit of violation for each tier.

    A tier's weight exceeds the most the ordinary objective (``ordinary_max``)
    plus every cheaper tier (weight times its ``max_units``) could add up to,
    so one unit of a stricter tier can never be paid to save a cheaper one.
    """
    weights: dict[Tier, int] = {}
    running = ordinary_max
    for tier in Tier:
        weights[tier] = running + 1
        running += weights[tier] * max_units_by_tier.get(tier, 0)
    return weights


def to_broken_rule(
    family: RuleFamily, relaxation: Relaxation, units: int, assignments: Sequence[Assignment] = ()
) -> BrokenRule:
    """The solver's report of one bent rule instance; ``assignments`` is the
    roster it returns, for a rule whose line names where people ended up."""
    line = (
        relaxation.describe_placed(units, assignments)
        if relaxation.describe_placed is not None
        else relaxation.describe(units)
    )
    return BrokenRule(instance=relaxation.instance, family=family.name, amount=units, line=line)
