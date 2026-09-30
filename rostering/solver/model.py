"""CP-SAT solver: assigns each helper exactly one (room, role).

Structural constraints (never relaxed):
- each helper gets exactly one room and exactly one role;
- fixed Assignments (``fixed_assignments``) are held as given.

Hard rules (relaxed — see ``rostering.solver.rules``): room/building role
minimums, Tag constraints on Building/Role and Equipment eligibility. A solve never fails because they clash;
each rule carries a slack penalized in strict priority tiers, and the rules
the solver had to bend come back as ``SolveResult.broken_rules``.

Soft (minimized) objective terms, dominated by any rule penalty:
- role-preference mismatch (weighted by how far from the helper's top choice);
- being placed in a building outside the helper's acceptable set (see
  CLAUDE.md "Building preference is a SET, not a single choice");
- unsatisfied friend requests, scored via ``rostering.solver.scoring``.

The only failure left is the time limit expiring before any roster is found
(``NoRosterFound``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ortools.sat.python import cp_model

from rostering.domain import (
    Assignment,
    BrokenRule,
    Competition,
    Preference,
    Role,
    RoleCapacity,
    Room,
    SolveResult,
)
from rostering.ingest.mapping import building_keys
from rostering.solver.rules import (
    ModelContext,
    RuleFamily,
    Tier,
    rule_families,
    tier_weights,
    to_broken_rule,
)
from rostering.solver.scoring import FriendScoringConfig, build_friend_pairs


@dataclass
class SolverWeights:
    role_preference: int = 4
    building_mismatch: int = 3
    friend_unsatisfied: int = 5


@dataclass
class SolverConfig:
    weights: SolverWeights = field(default_factory=SolverWeights)
    friend_scoring: FriendScoringConfig = field(default_factory=FriendScoringConfig)
    time_limit_seconds: float = 60.0


class NoRosterFound(Exception):
    """The time limit expired before the solver found any roster. Not a
    verdict on the rules — they can no longer make a solve infeasible."""

    def __init__(self, time_limit_seconds: float) -> None:
        self.time_limit_seconds = time_limit_seconds
        shown = int(time_limit_seconds) if float(time_limit_seconds).is_integer() else time_limit_seconds
        super().__init__(
            f"No roster found within {shown} seconds. "
            "Raise the time limit in the solver settings or solve again."
        )


def solve_competition(
    comp: Competition,
    config: Optional[SolverConfig] = None,
    *,
    fixed_assignments: Sequence[Assignment] = (),
    families: Optional[Sequence[RuleFamily]] = None,
) -> SolveResult:
    """Solve ``comp`` into a full roster, bending hard rules in tier order if
    it must. ``fixed_assignments`` pin those Helpers to a Room and Role
    exactly (a fixed Assignment never bends, even if it breaks a rule);
    ``families`` overrides the registered rule families (default: all of
    ``rostering.solver.rules.rule_families()``). Raises ``NoRosterFound`` when
    the time limit expires with no roster."""
    config = config or SolverConfig()
    families = list(rule_families() if families is None else families)
    model = cp_model.CpModel()

    comp = comp.attending()
    helpers = comp.helpers
    buildings = list(comp.buildings.values())
    roles = list(Role)

    # Flatten (building_name, Room) into a single indexable list.
    rooms: list[tuple[str, Room]] = []
    building_rooms: dict[str, list[int]] = {}
    for b in buildings:
        building_rooms[b.name] = []
        for room in b.rooms:
            room_id = len(rooms)
            rooms.append((b.name, room))
            building_rooms[b.name].append(room_id)

    if not rooms:
        # No rooms configured anywhere: fall back to one unlimited synthetic
        # room per building so the model stays feasible instead of crashing.
        for b in buildings:
            synthetic = Room(name=f"{b.name} (unconfigured)", capacities={Role.Zaloha: RoleCapacity(0)})
            room_id = len(rooms)
            rooms.append((b.name, synthetic))
            building_rooms[b.name].append(room_id)

    num_rooms = len(rooms)

    assign_room: dict[tuple[int, int], cp_model.IntVar] = {}
    assign_role: dict[tuple[int, Role], cp_model.IntVar] = {}
    role_room_var: dict[tuple[int, Role, int], cp_model.IntVar] = {}

    for h in helpers:
        for room_id in range(num_rooms):
            assign_room[h.id, room_id] = model.NewBoolVar(f"room_h{h.id}_r{room_id}")
        for r in roles:
            assign_role[h.id, r] = model.NewBoolVar(f"role_h{h.id}_{r.name}")

    # Linearize assign_role AND assign_room -> role_room_var (standard
    # boolean-AND encoding), needed for per-room/building role capacities.
    for h in helpers:
        for r in roles:
            for room_id in range(num_rooms):
                p = model.NewBoolVar(f"rr_h{h.id}_{r.name}_{room_id}")
                role_room_var[h.id, r, room_id] = p
                model.Add(p <= assign_role[h.id, r])
                model.Add(p <= assign_room[h.id, room_id])
                model.Add(p >= assign_role[h.id, r] + assign_room[h.id, room_id] - 1)

    for h in helpers:
        model.Add(sum(assign_room[h.id, room_id] for room_id in range(num_rooms)) == 1)
        model.Add(sum(assign_role[h.id, r] for r in roles) == 1)

    # Fixed Assignments: pinned exactly, never relaxed.
    room_ids_by_name = {(bname, room.name): room_id for room_id, (bname, room) in enumerate(rooms)}
    helper_ids = {h.id for h in helpers}
    for fixed in fixed_assignments:
        if fixed.helper_id not in helper_ids:
            raise ValueError(f"Fixed Assignment for unknown helper {fixed.helper_id}")
        fixed_room = room_ids_by_name.get((fixed.building, fixed.room))
        if fixed_room is None:
            raise ValueError(
                f"Fixed Assignment of helper {fixed.helper_id} names unknown room {fixed.building}/{fixed.room}"
            )
        model.Add(assign_room[fixed.helper_id, fixed_room] == 1)
        model.Add(assign_role[fixed.helper_id, fixed.role] == 1)

    # Hard rules, each relaxed by a slack. They are penalized only once the
    # ordinary objective is built, since their weights must dominate it.
    ctx = ModelContext(
        model=model,
        helpers=helpers,
        buildings=buildings,
        rooms=rooms,
        building_rooms=building_rooms,
        roles=roles,
        assign_room=assign_room,
        assign_role=assign_role,
        role_room_var=role_room_var,
        tags=comp.tags,
    )
    relaxed = [(family, relaxation) for family in families for relaxation in family.relax(ctx)]

    penalty_terms: list[cp_model.LinearExprT] = []
    ordinary_max = 0  # upper bound of the ordinary objective, for the tier weights
    max_pref = max(p.value for p in Preference)

    # Season configs and the survey spell buildings differently (diacritics,
    # "Troja" vs "Impakt + Troja"), so preferences are matched by key.
    room_building_keys = [building_keys(bname) for bname, _room in rooms]

    for h in helpers:
        for role, pref in h.role_preferences.items():
            weight = (max_pref - int(pref)) * config.weights.role_preference
            if weight:
                penalty_terms.append(weight * assign_role[h.id, role])
                ordinary_max += weight

        if h.building_preferences:
            preferred_keys = frozenset().union(*(building_keys(p) for p in h.building_preferences))
            for room_id, keys in enumerate(room_building_keys):
                if keys.isdisjoint(preferred_keys):
                    penalty_terms.append(config.weights.building_mismatch * assign_room[h.id, room_id])
                    ordinary_max += config.weights.building_mismatch

    # Friends: soft, scored per rostering.solver.scoring's configured mode.
    friend_pairs = build_friend_pairs(helpers, config.friend_scoring)
    satisfied_vars: dict[tuple[int, int], cp_model.IntVar] = {}
    for a_id, b_id, weight in friend_pairs:
        colocated_terms = []
        for room_id in range(num_rooms):
            z = model.NewBoolVar(f"colo_{a_id}_{b_id}_{room_id}")
            model.Add(z <= assign_room[a_id, room_id])
            model.Add(z <= assign_room[b_id, room_id])
            model.Add(z >= assign_room[a_id, room_id] + assign_room[b_id, room_id] - 1)
            colocated_terms.append(z)
        satisfied = model.NewBoolVar(f"friendsat_{a_id}_{b_id}")
        model.Add(satisfied == sum(colocated_terms))
        satisfied_vars[a_id, b_id] = satisfied
        weighted = weight * config.weights.friend_unsatisfied
        if weighted:
            penalty_terms.append(weighted * (1 - satisfied))
            ordinary_max += weighted

    ordinary_objective = sum(penalty_terms)
    units_by_tier: dict[Tier, int] = {}
    for family, relaxation in relaxed:
        units_by_tier[family.tier] = units_by_tier.get(family.tier, 0) + relaxation.max_units
    weights = tier_weights(ordinary_max, units_by_tier)
    rule_penalty = sum(weights[family.tier] * relaxation.slack for family, relaxation in relaxed)
    model.Minimize(ordinary_objective + rule_penalty)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    status = solver.Solve(model)

    if status == cp_model.UNKNOWN:
        raise NoRosterFound(config.time_limit_seconds)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Relaxation leaves nothing provably infeasible; anything else is a bug.
        raise RuntimeError(f"Unexpected solver status: {solver.StatusName(status)}")

    assignments: list[Assignment] = []
    for h in helpers:
        chosen_room = next(rid for rid in range(num_rooms) if solver.Value(assign_room[h.id, rid]) == 1)
        chosen_role = next(r for r in roles if solver.Value(assign_role[h.id, r]) == 1)
        bname, room = rooms[chosen_room]
        assignments.append(
            Assignment(helper_id=h.id, helper_name=h.name, building=bname, room=room.name, role=chosen_role)
        )

    unsatisfied_pairs = [pair for pair, var in satisfied_vars.items() if solver.Value(var) == 0]
    satisfied_pairs = [pair for pair, var in satisfied_vars.items() if solver.Value(var) == 1]
    status_name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"

    # Bent rules, the tier that bends first at the top.
    broken_rules: list[BrokenRule] = []
    for family, relaxation in sorted(relaxed, key=lambda pair: pair[0].tier):
        units = solver.Value(relaxation.slack)
        if units > 0:
            broken_rules.append(to_broken_rule(family, relaxation, units))

    return SolveResult(
        assignments=assignments,
        status=status_name,
        objective_value=solver.Value(ordinary_objective),
        unsatisfied_friend_pairs=unsatisfied_pairs,
        satisfied_friend_pairs=satisfied_pairs,
        broken_rules=broken_rules,
    )
