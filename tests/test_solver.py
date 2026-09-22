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
    caps = {Role.Zaloha: RoleCapacity(minimum=0)}
    for role_name, minimum in role_caps.items():
        caps[Role[role_name]] = RoleCapacity(minimum=minimum)
    return Room(name=name, capacities=caps)


def test_room_capacity_minimum_is_enforced_even_against_preference():
    room = _room("R1", Skenovac=2)
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


def test_friends_are_colocated_when_feasible():
    room1 = Room(name="R1", capacities={Role.Zaloha: RoleCapacity(minimum=0)})
    room2 = Room(name="R2", capacities={Role.Zaloha: RoleCapacity(minimum=0)})
    building = Building(name="B", rooms=[room1, room2])
    helpers = [
        Helper(id=1, name="A", friends=[2]),
        Helper(id=2, name="B", friends=[1]),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.unsatisfied_friend_pairs == []
    assert (1, 2) in result.satisfied_friend_pairs or (2, 1) in result.satisfied_friend_pairs
    rooms_used = {a.room for a in result.assignments}
    assert rooms_used == {"R1"} or rooms_used == {"R2"}


def test_building_preference_is_a_set_not_a_single_choice():
    room_a = Room(name="RA", capacities={Role.Zaloha: RoleCapacity(0)})
    room_b = Room(name="RB", capacities={Role.Zaloha: RoleCapacity(0)})
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
