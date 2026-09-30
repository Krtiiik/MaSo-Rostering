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
A later rule family (Tag constraints, Forced-friend groups) plugs in by
building a ``RuleFamily`` and passing it through ``register_rule_family``
(or to ``solve_competition(families=...)``), with no change to the model:

- ``RuleFamily.relax(ctx)`` adds the family's constraints to ``ctx.model``,
  each guarded by a slack, and returns one ``Relaxation`` per rule instance;
- each ``Relaxation`` carries the ``RuleInstance`` identity (rule kind plus
  entity) that the family's live checker must emit for the same violation —
  a relaxation cannot be registered without one, so the two cannot drift
  apart half-way;
- ``RuleFamily.tier`` picks the priority among the four tiers above.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable

from ortools.sat.python import cp_model

from rostering.domain import Building, BrokenRule, Helper, Role, Room, RuleInstance


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


@dataclass
class Relaxation:
    """One relaxed rule instance: ``slack`` is a non-negative expression that
    is exactly the size of the violation (0 when the rule holds), at most
    ``max_units``; ``describe`` words a violation of a given size."""

    instance: RuleInstance
    slack: cp_model.LinearExprT
    max_units: int
    describe: Callable[[int], str]


@dataclass(frozen=True)
class RuleFamily:
    name: str
    tier: Tier
    relax: Callable[[ModelContext], list[Relaxation]]


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


def _equipment(ctx: ModelContext) -> list[Relaxation]:
    # Camera/Fotograf only — the notebook/Kreslič rule was removed;
    # can_bring_notebook is display-only now.
    return [
        Relaxation(
            instance=RuleInstance("equipment", (h.id,)),
            slack=ctx.assign_role[h.id, Role.Fotograf],
            max_units=1,
            describe=lambda _short, name=h.name: f"Helper {name} has no camera but is Fotograf",
        )
        for h in ctx.helpers
        if not h.can_bring_camera
    ]


MINIMUMS_FAMILY = RuleFamily("minimums", Tier.MINIMUMS, _minimums)
EQUIPMENT_FAMILY = RuleFamily("equipment", Tier.EQUIPMENT, _equipment)

_registry: list[RuleFamily] = [MINIMUMS_FAMILY, EQUIPMENT_FAMILY]


def register_rule_family(family: RuleFamily) -> None:
    """Add a rule family to every later solve (see the module docstring)."""
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


def to_broken_rule(family: RuleFamily, relaxation: Relaxation, units: int) -> BrokenRule:
    return BrokenRule(
        instance=relaxation.instance,
        family=family.name,
        amount=units,
        line=relaxation.describe(units),
    )
