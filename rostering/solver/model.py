"""CP-SAT solver: assigns each helper exactly one (room, role).

Hard constraints:
- each helper gets exactly one room and exactly one role;
- room/building role headcounts stay within their configured min/max;
- a helper without a notebook can never be Kreslič; without a camera, never
  Fotograf (see CLAUDE.md "Equipment eligibility").

Soft (minimized) objective terms:
- role-preference mismatch (weighted by how far from the helper's top choice);
- being placed in a building outside the helper's acceptable set (see
  CLAUDE.md "Building preference is a SET, not a single choice");
- unsatisfied friend requests, scored via ``rostering.solver.scoring``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ortools.sat.python import cp_model

from rostering.domain import (
    Assignment,
    Competition,
    Preference,
    Role,
    RoleCapacity,
    Room,
    SolveResult,
)
from rostering.solver.scoring import FriendScoringConfig, build_friend_pairs


@dataclass
class SolverWeights:
    role_preference: int = 1
    building_mismatch: int = 10
    friend_unsatisfied: int = 5


@dataclass
class SolverConfig:
    weights: SolverWeights = field(default_factory=SolverWeights)
    friend_scoring: FriendScoringConfig = field(default_factory=FriendScoringConfig)
    time_limit_seconds: float = 10.0


def solve_competition(comp: Competition, config: Optional[SolverConfig] = None) -> Optional[SolveResult]:
    config = config or SolverConfig()
    model = cp_model.CpModel()

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
            synthetic = Room(name=f"{b.name} (unconfigured)", capacities={Role.Zaloha: RoleCapacity(0, None)})
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

    # Equipment eligibility (hard).
    for h in helpers:
        if not h.can_bring_notebook:
            model.Add(assign_role[h.id, Role.Kreslic] == 0)
        if not h.can_bring_camera:
            model.Add(assign_role[h.id, Role.Fotograf] == 0)

    # Room-level capacities.
    for room_id, (_bname, room) in enumerate(rooms):
        for role, cap in room.capacities.items():
            terms = [role_room_var[h.id, role, room_id] for h in helpers]
            if cap.minimum:
                model.Add(sum(terms) >= cap.minimum)
            if cap.maximum is not None:
                model.Add(sum(terms) <= cap.maximum)

    # Building-level capacities (aggregated across the building's rooms).
    for b in buildings:
        room_ids = building_rooms.get(b.name, [])
        for role, cap in b.capacities.items():
            terms = [role_room_var[h.id, role, rid] for rid in room_ids for h in helpers]
            if cap.minimum:
                model.Add(sum(terms) >= cap.minimum)
            if cap.maximum is not None:
                model.Add(sum(terms) <= cap.maximum)

    penalty_terms: list[cp_model.LinearExprT] = []
    max_pref = max(p.value for p in Preference)

    for h in helpers:
        for role, pref in h.role_preferences.items():
            weight = (max_pref - int(pref)) * config.weights.role_preference
            if weight:
                penalty_terms.append(weight * assign_role[h.id, role])

        if h.building_preferences:
            for room_id, (bname, _room) in enumerate(rooms):
                if bname not in h.building_preferences:
                    penalty_terms.append(config.weights.building_mismatch * assign_room[h.id, room_id])

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

    model.Minimize(sum(penalty_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignments: list[Assignment] = []
    for h in helpers:
        chosen_room = next(rid for rid in range(num_rooms) if solver.Value(assign_room[h.id, rid]) == 1)
        chosen_role = next(r for r in roles if solver.Value(assign_role[h.id, r]) == 1)
        bname, room = rooms[chosen_room]
        assignments.append(
            Assignment(helper_id=h.id, helper_name=h.name, building=bname, room=room.name, role=chosen_role)
        )

    unsatisfied_pairs = [pair for pair, var in satisfied_vars.items() if solver.Value(var) == 0]
    status_name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"

    return SolveResult(
        assignments=assignments,
        status=status_name,
        objective_value=solver.ObjectiveValue(),
        unsatisfied_friend_pairs=unsatisfied_pairs,
    )
