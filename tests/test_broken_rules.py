"""Soft-relaxation solve: hard rules bend in strict tiers instead of failing.

Small hand-built competitions with short time limits, asserting only on the
roster returned and the Broken rules reported (never on penalty values).
"""
import pytest

from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    Preference,
    Role,
    RoleCapacity,
    Room,
    RuleInstance,
)
from rostering.solver.model import NoRosterFound, SolverConfig, solve_competition
from rostering.solver.rules import Relaxation, RuleFamily, Tier, rule_families, tier_weights


def _room(name, **role_caps):
    caps = {Role.Zaloha: RoleCapacity(minimum=0)}
    for role_name, minimum in role_caps.items():
        caps[Role[role_name]] = RoleCapacity(minimum=minimum)
    return Room(name=name, capacities=caps)


def _config():
    return SolverConfig(time_limit_seconds=5)


def _broken(result):
    return {b.instance: b for b in result.broken_rules}


def test_unmeetable_room_minimum_returns_a_full_roster_and_the_broken_rule():
    building = Building(name="B", rooms=[_room("R1", Skenovac=3)])
    helpers = [Helper(id=1, name="A"), Helper(id=2, name="B")]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, _config())

    assert {a.helper_id for a in result.assignments} == {1, 2}
    # Everyone who can is put where the rule needs them; the shortfall is reported.
    assert all(a.role == Role.Skenovac for a in result.assignments)
    instance = RuleInstance("room_exact", ("B", "R1", "Skenovac"))
    broken = _broken(result)
    assert list(broken) == [instance]
    assert broken[instance].family == "minimums"
    assert broken[instance].amount == 1
    assert broken[instance].line == "Místnost R1 · Skenovač: 2 z 3 požadovaných (chybí 1)"


def test_unmeetable_building_limit_is_reported():
    building = Building(
        name="B",
        rooms=[_room("R1"), _room("R2")],
        capacities={Role.Menic: RoleCapacity(minimum=2)},
    )
    comp = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="A")])

    result = solve_competition(comp, _config())

    instance = RuleInstance("building_exact", ("B", "Menic"))
    broken = _broken(result)
    assert list(broken) == [instance]
    assert broken[instance].line == "Budova B · Měnič: 1 z 2 požadovaných (chybí 1)"


def test_a_room_count_is_exact_so_the_solver_never_overfills_it():
    building = Building(name="B", rooms=[_room("R1", Skenovac=2), _room("R2")])
    helpers = [
        Helper(id=i, name=f"H{i}", role_preferences={Role.Skenovac: Preference.Ano}) for i in range(1, 6)
    ]

    result = solve_competition(Competition(buildings={"B": building}, helpers=helpers), _config())

    assert result.broken_rules == []
    assert sum(1 for a in result.assignments if (a.room, a.role) == ("R1", Role.Skenovac)) == 2


def test_an_unmeetable_room_count_reports_the_overshoot():
    # Four Helpers are pinned to R1's Skenovač, whose count is exactly one.
    building = Building(name="B", rooms=[_room("R1", Skenovac=1)])
    helpers = [Helper(id=i, name=f"H{i}") for i in range(1, 5)]
    pinned = [Assignment(helper_id=i, helper_name=f"H{i}", building="B", room="R1", role=Role.Skenovac) for i in range(1, 5)]

    result = solve_competition(
        Competition(buildings={"B": building}, helpers=helpers), _config(), fixed_assignments=pinned
    )

    broken = _broken(result)
    instance = RuleInstance("room_exact", ("B", "R1", "Skenovac"))
    assert broken[instance].amount == 3
    assert broken[instance].line == "Místnost R1 · Skenovač: 4 z 1 požadovaných (přebývá 3)"


def test_a_building_limit_is_exact_so_the_solver_never_overfills_it():
    building = Building(
        name="B",
        rooms=[_room("R1"), _room("R2")],
        capacities={Role.Skenovac: RoleCapacity(minimum=2)},
    )
    helpers = [
        Helper(id=i, name=f"H{i}", role_preferences={Role.Skenovac: Preference.Ano}) for i in range(1, 6)
    ]

    result = solve_competition(Competition(buildings={"B": building}, helpers=helpers), _config())

    assert result.broken_rules == []
    assert sum(1 for a in result.assignments if a.role is Role.Skenovac) == 2


def test_an_unmeetable_building_limit_reports_the_overshoot():
    building = Building(
        name="B",
        rooms=[_room("R1")],
        capacities={Role.Skenovac: RoleCapacity(minimum=2)},
    )
    helpers = [Helper(id=i, name=f"H{i}") for i in range(1, 5)]
    pinned = [Assignment(helper_id=i, helper_name=f"H{i}", building="B", room="R1", role=Role.Skenovac) for i in range(1, 4)]

    result = solve_competition(
        Competition(buildings={"B": building}, helpers=helpers), _config(), fixed_assignments=pinned
    )

    broken = _broken(result)
    instance = RuleInstance("building_exact", ("B", "Skenovac"))
    assert instance in broken
    assert broken[instance].amount == 1
    assert broken[instance].line == "Budova B · Skenovač: 3 z 2 požadovaných (přebývá 1)"


def test_achievable_competition_has_no_broken_rules():
    building = Building(name="B", rooms=[_room("R1", Skenovac=1)])
    comp = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="A"), Helper(id=2, name="B")])

    result = solve_competition(comp, _config())

    assert result.broken_rules == []


def test_a_minimum_bends_before_equipment():
    # The only helper has no camera; the room needs a Fotograf. Either the
    # minimum or Equipment eligibility must give — minimums bend first.
    building = Building(name="B", rooms=[_room("R1", Fotograf=1)])
    helper = Helper(id=1, name="No camera", role_preferences={Role.Fotograf: Preference.Ano}, can_bring_camera=False)
    comp = Competition(buildings={"B": building}, helpers=[helper])

    result = solve_competition(comp, _config())

    assert result.assignments[0].role != Role.Fotograf
    assert list(_broken(result)) == [RuleInstance("room_exact", ("B", "R1", "Fotograf"))]


def test_equipment_bends_only_when_nothing_else_can():
    # Nothing but a fixed Assignment can force the camera rule to bend.
    building = Building(name="B", rooms=[_room("R1")])
    helper = Helper(id=1, name="Nocam", can_bring_camera=False)
    comp = Competition(buildings={"B": building}, helpers=[helper])
    fixed = Assignment(helper_id=1, helper_name="Nocam", building="B", room="R1", role=Role.Fotograf)

    result = solve_competition(comp, _config(), fixed_assignments=[fixed])

    instance = RuleInstance("equipment", (1,))
    assert result.assignments[0].role == Role.Fotograf
    broken = _broken(result)
    assert list(broken) == [instance]
    assert broken[instance].family == "equipment"
    assert broken[instance].line == "Pomocník Nocam nemá fotoaparát, ale je Fotograf"


def test_ordinary_preferences_never_outweigh_a_rule():
    # Nobody wants to be Fotograf, but the room needs one and only one helper
    # has a camera: preferences yield, the minimum holds.
    building = Building(name="B", rooms=[_room("R1", Fotograf=1)])
    helpers = [
        Helper(id=1, name="Camera", role_preferences={Role.Fotograf: Preference.Ne}, can_bring_camera=True),
        Helper(id=2, name="No camera", role_preferences={Role.Fotograf: Preference.Ano}, can_bring_camera=False),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, _config())

    roles = {a.helper_id: a.role for a in result.assignments}
    assert roles[1] == Role.Fotograf
    assert result.broken_rules == []


def test_objective_value_excludes_rule_penalties():
    building = Building(name="B", rooms=[_room("R1", Skenovac=2)])
    # Ano on Skenovač costs nothing, so the whole objective is the rule penalty's absence.
    helper = Helper(id=1, name="A", role_preferences={Role.Skenovac: Preference.Ano})
    comp = Competition(buildings={"B": building}, helpers=[helper])

    result = solve_competition(comp, _config())

    assert result.broken_rules
    assert result.objective_value == 0


def test_fixed_assignments_are_held_and_the_rest_solved_around_them():
    building = Building(name="B", rooms=[_room("R1", Skenovac=1), _room("R2")])
    helpers = [Helper(id=1, name="A"), Helper(id=2, name="B")]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    fixed = [Assignment(helper_id=1, helper_name="A", building="B", room="R2", role=Role.Zaloha)]

    result = solve_competition(comp, _config(), fixed_assignments=fixed)

    by_id = {a.helper_id: a for a in result.assignments}
    assert (by_id[1].room, by_id[1].role) == ("R2", Role.Zaloha)
    assert (by_id[2].room, by_id[2].role) == ("R1", Role.Skenovac)
    assert result.broken_rules == []


def test_a_fixed_assignment_never_moves_to_save_a_minimum():
    building = Building(name="B", rooms=[_room("R1", Skenovac=1)])
    comp = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="A")])
    fixed = [Assignment(helper_id=1, helper_name="A", building="B", room="R1", role=Role.Zaloha)]

    result = solve_competition(comp, _config(), fixed_assignments=fixed)

    assert result.assignments[0].role == Role.Zaloha
    assert list(_broken(result)) == [RuleInstance("room_exact", ("B", "R1", "Skenovac"))]


def test_a_fixed_assignment_naming_an_unknown_room_is_rejected():
    building = Building(name="B", rooms=[_room("R1")])
    comp = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="A")])
    fixed = [Assignment(helper_id=1, helper_name="A", building="B", room="nope", role=Role.Zaloha)]

    with pytest.raises(ValueError):
        solve_competition(comp, _config(), fixed_assignments=fixed)


def _must_be_fotograf(helper_id, tier):
    """A stand-in for a later rule family: `helper_id` must be Fotograf."""

    def relax(ctx):
        return [
            Relaxation(
                instance=RuleInstance("must_be_fotograf", (helper_id,)),
                slack=1 - ctx.assign_role[helper_id, Role.Fotograf],
                max_units=1,
                describe=lambda _n: f"Helper {helper_id} must be Fotograf",
            )
        ]

    return RuleFamily("must_be_fotograf", tier, relax)


def test_a_new_rule_family_plugs_in_and_bends_before_equipment():
    # Helper 1 has no camera. The extra rule (Tag tier) wants them Fotograf;
    # Equipment is the stricter tier, so the extra rule is the one that bends.
    building = Building(name="B", rooms=[_room("R1")])
    helper = Helper(id=1, name="No camera", can_bring_camera=False)
    comp = Competition(buildings={"B": building}, helpers=[helper])
    families = [*rule_families(), _must_be_fotograf(1, Tier.TAG_RESTRICTIONS)]

    result = solve_competition(comp, _config(), families=families)

    assert result.assignments[0].role != Role.Fotograf
    assert list(_broken(result)) == [RuleInstance("must_be_fotograf", (1,))]


def test_a_new_rule_family_holds_while_a_minimum_bends_instead():
    # The room needs a Skenovač; helper 1 alone must be Fotograf (Tag tier).
    # Minimums bend first, so the stricter Tag-tier rule holds.
    building = Building(name="B", rooms=[_room("R1", Skenovac=1)])
    helper = Helper(id=1, name="Camera", can_bring_camera=True)
    comp = Competition(buildings={"B": building}, helpers=[helper])
    families = [*rule_families(), _must_be_fotograf(1, Tier.TAG_RESTRICTIONS)]

    result = solve_competition(comp, _config(), families=families)

    assert result.assignments[0].role == Role.Fotograf
    assert list(_broken(result)) == [RuleInstance("room_exact", ("B", "R1", "Skenovac"))]


def test_tier_weights_are_dominance_ordered():
    weights = tier_weights(
        ordinary_max=100, max_units_by_tier={Tier.MINIMUMS: 7, Tier.TAG_RESTRICTIONS: 5, Tier.FORCED_FRIENDS: 2},
    )

    assert weights[Tier.MINIMUMS] > 100
    assert weights[Tier.TAG_RESTRICTIONS] > 100 + weights[Tier.MINIMUMS] * 7
    assert weights[Tier.FORCED_FRIENDS] > 100 + weights[Tier.MINIMUMS] * 7 + weights[Tier.TAG_RESTRICTIONS] * 5
    assert weights[Tier.EQUIPMENT] > weights[Tier.FORCED_FRIENDS]


def test_many_bent_minimums_never_cost_one_equipment_violation():
    # Three no-camera helpers, a room wanting three Fotografs: three units of
    # minimum shortfall are still cheaper than a single camera violation.
    building = Building(name="B", rooms=[_room("R1", Fotograf=3)])
    helpers = [Helper(id=i, name=str(i), can_bring_camera=False) for i in (1, 2, 3)]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, _config())

    instance = RuleInstance("room_exact", ("B", "R1", "Fotograf"))
    assert all(a.role != Role.Fotograf for a in result.assignments)
    assert list(_broken(result)) == [instance]
    assert _broken(result)[instance].amount == 3


def test_time_limit_with_no_roster_is_its_own_outcome():
    building = Building(name="B", rooms=[_room("R1", Skenovac=1)])
    comp = Competition(buildings={"B": building}, helpers=[Helper(id=i, name=str(i)) for i in range(1, 30)])

    with pytest.raises(NoRosterFound) as excinfo:
        solve_competition(comp, SolverConfig(time_limit_seconds=0))

    assert str(excinfo.value).startswith("Rozdělení se nepodařilo najít do 0 s.")
    assert "sestavte rozdělení znovu" in str(excinfo.value)
