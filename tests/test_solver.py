from rostering.domain import (
    Building,
    Competition,
    Helper,
    Preference,
    Role,
    RoleCapacity,
    Room,
)
from rostering.solver.model import SolverConfig, solve_competition


def _room(name, **role_caps):
    caps = {Role.Zaloha: RoleCapacity(minimum=0, maximum=None)}
    for role_name, (minimum, maximum) in role_caps.items():
        caps[Role[role_name]] = RoleCapacity(minimum=minimum, maximum=maximum)
    return Room(name=name, capacities=caps)


def _single_slot_room(name):
    """A room that can hold exactly one helper, regardless of role — every
    role is forbidden (max=0) except Záloha, capped at 1."""
    caps = {role: RoleCapacity(minimum=0, maximum=0) for role in Role}
    caps[Role.Zaloha] = RoleCapacity(minimum=0, maximum=1)
    return Room(name=name, capacities=caps)


def test_room_capacity_maximum_is_enforced():
    # Forbid every role except Opravovatel (capped at 1) and Zaloha, so the
    # only way to place a second helper is to fall back to Zaloha — this
    # isolates the max=1 check from the solver simply picking some other
    # zero-cost role instead.
    room = Room(
        name="R1",
        capacities={
            Role.Opravovatel: RoleCapacity(0, 1),
            Role.Menic: RoleCapacity(0, 0),
            Role.Skenovac: RoleCapacity(0, 0),
            Role.Kreslic: RoleCapacity(0, 0),
            Role.Fotograf: RoleCapacity(0, 0),
            Role.Zaloha: RoleCapacity(0, None),
        },
    )
    building = Building(name="B", rooms=[room])
    # Both strongly prefer Opravovatel and strongly dislike the only
    # fallback (Zaloha), so the solver would put both in Opravovatel if the
    # max=1 cap didn't stop it.
    prefs = {Role.Opravovatel: Preference.Ano, Role.Zaloha: Preference.Ne}
    helpers = [
        Helper(id=1, name="A", role_preferences=prefs),
        Helper(id=2, name="B", role_preferences=prefs),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    roles_assigned = [a.role for a in result.assignments]
    assert roles_assigned.count(Role.Opravovatel) == 1
    assert roles_assigned.count(Role.Zaloha) == 1


def test_room_capacity_minimum_is_enforced_even_against_preference():
    room = _room("R1", Skenovac=(2, None))
    building = Building(name="B", rooms=[room])
    # Both helpers would rather do anything but Skenovač, but the room needs 2.
    helpers = [
        Helper(id=1, name="A", role_preferences={Role.Skenovac: Preference.Ne}),
        Helper(id=2, name="B", role_preferences={Role.Skenovac: Preference.Ne}),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert all(a.role == Role.Skenovac for a in result.assignments)


def test_equipment_eligibility_is_hard_even_with_strong_preference():
    room = _room("R1")
    building = Building(name="B", rooms=[room])
    helper = Helper(
        id=1,
        name="No notebook",
        role_preferences={Role.Kreslic: Preference.Ano},
        can_bring_notebook=False,
    )
    comp = Competition(buildings={"B": building}, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.assignments[0].role != Role.Kreslic


def test_fotograf_requires_camera():
    room = _room("R1")
    building = Building(name="B", rooms=[room])
    helper = Helper(
        id=1,
        name="No camera",
        role_preferences={Role.Fotograf: Preference.Ano},
        can_bring_camera=False,
    )
    comp = Competition(buildings={"B": building}, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.assignments[0].role != Role.Fotograf


def test_friends_are_soft_not_hard_when_rooms_force_separation():
    # Each room can only hold one helper (Zaloha max=1), so two mutual
    # friends CANNOT be co-located. This must stay solvable (soft
    # preference) rather than the old behaviour of a hard same-room
    # constraint, which would make this infeasible.
    room1 = _single_slot_room("R1")
    room2 = _single_slot_room("R2")
    building = Building(name="B", rooms=[room1, room2])
    helpers = [
        Helper(id=1, name="A", friends=[2]),
        Helper(id=2, name="B", friends=[1]),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None, "should stay feasible even though the friend request can't be satisfied"
    assert len(result.assignments) == 2
    rooms_used = {a.room for a in result.assignments}
    assert rooms_used == {"R1", "R2"}
    assert (1, 2) in result.unsatisfied_friend_pairs or (2, 1) in result.unsatisfied_friend_pairs


def test_friends_are_colocated_when_feasible():
    room1 = Room(name="R1", capacities={Role.Zaloha: RoleCapacity(minimum=0, maximum=None)})
    room2 = Room(name="R2", capacities={Role.Zaloha: RoleCapacity(minimum=0, maximum=None)})
    building = Building(name="B", rooms=[room1, room2])
    helpers = [
        Helper(id=1, name="A", friends=[2]),
        Helper(id=2, name="B", friends=[1]),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.unsatisfied_friend_pairs == []
    rooms_used = {a.room for a in result.assignments}
    assert rooms_used == {"R1"} or rooms_used == {"R2"}


def test_building_preference_is_a_set_not_a_single_choice():
    room_a = Room(name="RA", capacities={Role.Zaloha: RoleCapacity(0, None)})
    room_b = Room(name="RB", capacities={Role.Zaloha: RoleCapacity(0, None)})
    buildings = {
        "A": Building(name="A", rooms=[room_a]),
        "B": Building(name="B", rooms=[room_b]),
    }
    # Accepts either building -> no penalty regardless of which is chosen.
    helper = Helper(id=1, name="Flexible", building_preferences=frozenset({"A", "B"}))
    comp = Competition(buildings=buildings, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.objective_value == 0


def test_no_rooms_configured_falls_back_to_synthetic_room():
    building = Building(name="Empty", rooms=[])
    helper = Helper(id=1, name="Solo")
    comp = Competition(buildings={"Empty": building}, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert len(result.assignments) == 1
