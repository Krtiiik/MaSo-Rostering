from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    Preference,
    Role,
    RoleCapacity,
    Room,
)
from rostering.solver.model import RoleCosts, SolverConfig, SolverWeights, solve_competition


# An "Ano" makes one Role free, so a lone Helper's role cost is 0 and the
# objective isolates the Building term (a blank Role counts as Nevadí, not 0).
CONTENT = {Role.Opravovatel: Preference.Ano}


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


def test_kreslic_has_no_equipment_hard_constraint():
    # The notebook/Kreslič hard constraint was removed: a helper who can't
    # bring a notebook can still be assigned Kreslič.
    room = _room("R1")
    building = Building(name="B", rooms=[room])
    helper = Helper(
        id=1,
        name="No notebook",
        role_preferences={
            Role.Opravovatel: Preference.Ne,
            Role.Menic: Preference.Ne,
            Role.Skenovac: Preference.Ne,
            Role.Kreslic: Preference.Ano,
            Role.Fotograf: Preference.Ne,
        },
        can_bring_notebook=False,
    )
    comp = Competition(buildings={"B": building}, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.assignments[0].role == Role.Kreslic


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
    helper = Helper(id=1, name="Flexible", building_preferences=frozenset({"A", "B"}), role_preferences=CONTENT)
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


def _zero_cap_building(name):
    return Building(name=name, rooms=[Room(name=f"{name}-R", capacities={Role.Zaloha: RoleCapacity(0)})])


def test_building_preference_matches_config_name_without_diacritics():
    # Ingestion yields "Malá Strana"; the season config may spell it
    # "Mala Strana" (real 2026-jaro config does). It's the same Building.
    buildings = {
        "Mala Strana": _zero_cap_building("Mala Strana"),
        "Karlov": _zero_cap_building("Karlov"),
    }
    helper = Helper(id=1, name="H", building_preferences=frozenset({"Malá Strana"}), role_preferences=CONTENT)
    comp = Competition(buildings=buildings, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.objective_value == 0
    assert result.assignments[0].building == "Mala Strana"


def test_building_preference_matches_config_alias_of_impakt_troja():
    # Ingestion maps both "Impakt" and "Troja" answers to "Impakt + Troja";
    # a season config naming that building just "Troja" must still match.
    buildings = {
        "Troja": _zero_cap_building("Troja"),
        "Karlin": _zero_cap_building("Karlin"),
    }
    helper = Helper(id=1, name="H", building_preferences=frozenset({"Impakt + Troja"}), role_preferences=CONTENT)
    comp = Competition(buildings=buildings, helpers=[helper])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5))

    assert result is not None
    assert result.objective_value == 0
    assert result.assignments[0].building == "Troja"


def test_building_preference_still_penalizes_a_genuinely_different_building():
    buildings = {"Karlov": _zero_cap_building("Karlov")}
    helper = Helper(id=1, name="H", building_preferences=frozenset({"Malá Strana"}), role_preferences=CONTENT)
    comp = Competition(buildings=buildings, helpers=[helper])
    config = SolverConfig(time_limit_seconds=5)

    result = solve_competition(comp, config)

    assert result is not None
    assert result.objective_value == config.weights.building_mismatch


def test_fixed_assignments_come_back_unchanged_and_an_empty_set_changes_nothing():
    building = Building(name="B", rooms=[_room("R1"), _room("R2")])
    helpers = [Helper(id=1, name="A"), Helper(id=2, name="B")]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    fixed = [Assignment(helper_id=1, helper_name="A", building="B", room="R2", role=Role.Kreslic)]

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5), fixed_assignments=fixed)

    kept = next(a for a in result.assignments if a.helper_id == 1)
    assert (kept.building, kept.room, kept.role) == ("B", "R2", Role.Kreslic)
    plain = solve_competition(comp, SolverConfig(time_limit_seconds=5), fixed_assignments=[])
    assert plain.broken_rules == []


def test_fixed_helpers_count_toward_a_room_minimum():
    # R1 needs 3 Skenovač; two Helpers are fixed there, so the one free Helper
    # completes it and no rule bends.
    building = Building(name="B", rooms=[_room("R1", Skenovac=3), _room("R2")])
    helpers = [Helper(id=1, name="A"), Helper(id=2, name="B"), Helper(id=3, name="C")]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    fixed = [
        Assignment(helper_id=1, helper_name="A", building="B", room="R1", role=Role.Skenovac),
        Assignment(helper_id=2, helper_name="B", building="B", room="R1", role=Role.Skenovac),
    ]

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5), fixed_assignments=fixed)

    assert result.broken_rules == []
    third = next(a for a in result.assignments if a.helper_id == 3)
    assert (third.room, third.role) == ("R1", Role.Skenovac)


def test_fixed_helpers_count_toward_friend_colocation():
    building = Building(name="B", rooms=[_room("R1"), _room("R2")])
    helpers = [Helper(id=1, name="A", friends=[2]), Helper(id=2, name="B"), Helper(id=3, name="C")]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    fixed = [Assignment(helper_id=2, helper_name="B", building="B", room="R2", role=Role.Zaloha)]

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5), fixed_assignments=fixed)

    friend = next(a for a in result.assignments if a.helper_id == 1)
    assert friend.room == "R2"
    assert (1, 2) in result.satisfied_friend_pairs


# --- Role Preference scoring by rating cost -------------------------------

REAL_ROLES = [Role.Opravovatel, Role.Menic, Role.Skenovac, Role.Kreslic, Role.Fotograf]


def _all_roles(pref):
    return {role: pref for role in REAL_ROLES}


def _solve(comp, config=None):
    return solve_competition(comp, config or SolverConfig(time_limit_seconds=5))


def test_an_ano_beats_a_blank_for_a_contested_role():
    building = Building(name="B", rooms=[_room("R1", Opravovatel=1)])
    helpers = [
        Helper(id=1, name="Blank"),
        Helper(id=2, name="Ano", role_preferences={Role.Opravovatel: Preference.Ano}),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)

    result = _solve(comp)

    winner = next(a for a in result.assignments if a.role == Role.Opravovatel)
    assert winner.helper_id == 2


def test_a_blank_role_scores_the_same_as_an_explicit_nevadi():
    building = Building(name="B", rooms=[_room("R1")])
    blank = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="H")])
    nevadi = Competition(
        buildings={"B": building},
        helpers=[Helper(id=1, name="H", role_preferences=_all_roles(Preference.Nevadi))],
    )

    assert _solve(blank).objective_value == _solve(nevadi).objective_value


def test_nevadi_on_a_real_role_is_placed_there_rather_than_in_zaloha():
    building = Building(name="B", rooms=[_room("R1")])
    helper = Helper(id=1, name="H", role_preferences=_all_roles(Preference.Nevadi))
    comp = Competition(buildings={"B": building}, helpers=[helper])

    assert _solve(comp).assignments[0].role != Role.Zaloha


def test_a_helper_who_refused_every_open_role_is_placed_in_zaloha():
    building = Building(name="B", rooms=[_room("R1")])
    prefs = {
        Role.Opravovatel: Preference.Spise_ne,
        Role.Menic: Preference.Ne,
        Role.Skenovac: Preference.Spise_ne,
        Role.Kreslic: Preference.Ne,
        Role.Fotograf: Preference.Spise_ne,
    }
    comp = Competition(buildings={"B": building}, helpers=[Helper(id=1, name="H", role_preferences=prefs)])

    assert _solve(comp).assignments[0].role == Role.Zaloha


def test_configured_costs_change_the_outcome():
    building = Building(name="B", rooms=[_room("R1")])
    helper = Helper(id=1, name="H", role_preferences=_all_roles(Preference.Spise_ne))
    comp = Competition(buildings={"B": building}, helpers=[helper])

    default = _solve(comp)
    dear_zaloha = _solve(comp, SolverConfig(time_limit_seconds=5, role_costs=RoleCosts(zaloha=8)))

    assert default.assignments[0].role == Role.Zaloha
    assert dear_zaloha.assignments[0].role != Role.Zaloha


def test_the_role_preference_weight_is_the_unit_of_the_role_cost():
    building = Building(name="B", rooms=[_room("R1", Skenovac=1)])
    helper = Helper(id=1, name="H", role_preferences={Role.Skenovac: Preference.Ne})
    comp = Competition(buildings={"B": building}, helpers=[helper])
    doubled = SolverConfig(time_limit_seconds=5, weights=SolverWeights(role_preference=2))

    assert _solve(comp).objective_value == RoleCosts().ne
    assert _solve(comp, doubled).objective_value == 2 * RoleCosts().ne


# --- Concentration of "Ano" ------------------------------------------------


def _forced_into(role_name, *helpers):
    building = Building(name="B", rooms=[_room("R1", **{role_name: 1})])
    return Competition(buildings={"B": building}, helpers=list(helpers))


def _role_of(result, helper_id):
    return next(a.role for a in result.assignments if a.helper_id == helper_id)


def test_the_helper_with_a_single_ano_keeps_it_over_one_with_three():
    # Both are Nevadí on Kreslic, so a plain sum of costs would tie.
    many = Helper(
        id=1,
        name="Many",
        role_preferences={
            Role.Opravovatel: Preference.Ano,
            Role.Menic: Preference.Ano,
            Role.Skenovac: Preference.Ano,
            Role.Kreslic: Preference.Nevadi,
        },
    )
    one = Helper(
        id=2,
        name="One",
        role_preferences={Role.Opravovatel: Preference.Ano, Role.Kreslic: Preference.Nevadi},
    )

    result = _solve(_forced_into("Kreslic", many, one))

    assert _role_of(result, 1) == Role.Kreslic
    assert _role_of(result, 2) == Role.Opravovatel


def test_the_concentration_factor_is_one_plus_one_over_k():
    def forced_cost(anos):
        prefs = {role: Preference.Ano for role in REAL_ROLES[:anos]}
        prefs[Role.Kreslic] = Preference.Nevadi
        comp = _forced_into("Kreslic", Helper(id=1, name="H", role_preferences=prefs))
        return _solve(comp).objective_value

    nevadi = RoleCosts().nevadi
    assert forced_cost(1) == nevadi * 2
    assert forced_cost(2) == nevadi * 1.5
    assert forced_cost(3) == nevadi * (1 + 1 / 3)


def test_a_blank_never_counts_towards_the_number_of_anos():
    # One "Ano" and four blanks is k = 1, so the forced blank costs Nevadí x 2.
    helper = Helper(id=1, name="H", role_preferences={Role.Opravovatel: Preference.Ano})

    result = _solve(_forced_into("Kreslic", helper))

    assert result.objective_value == RoleCosts().nevadi * 2


def test_a_helper_without_an_ano_is_scored_with_factor_one():
    helper = Helper(id=1, name="H", role_preferences=_all_roles(Preference.Klidne))

    result = _solve(_forced_into("Kreslic", helper))

    assert result.objective_value == RoleCosts().klidne


def test_concentration_scales_ne_by_the_shared_factor_only():
    many = Helper(
        id=1,
        name="Many",
        role_preferences={
            Role.Opravovatel: Preference.Ano,
            Role.Menic: Preference.Ano,
            Role.Skenovac: Preference.Ano,
            Role.Kreslic: Preference.Ne,
        },
    )
    one = Helper(id=2, name="One", role_preferences={Role.Opravovatel: Preference.Ano, Role.Kreslic: Preference.Ne})

    result = _solve(_forced_into("Kreslic", many, one))

    assert _role_of(result, 1) == Role.Kreslic
    assert result.objective_value == RoleCosts().ne * (1 + 1 / 3)


def test_ne_is_never_chosen_over_spise_ne_or_zaloha_when_cheaper_exists():
    building = Building(name="B", rooms=[_room("R1")])
    no_ano = {
        Role.Opravovatel: Preference.Ne,
        Role.Menic: Preference.Ne,
        Role.Skenovac: Preference.Ne,
        Role.Kreslic: Preference.Ne,
        Role.Fotograf: Preference.Spise_ne,
    }
    with_ano = {**no_ano, Role.Opravovatel: Preference.Ano}
    comp = Competition(
        buildings={"B": building},
        helpers=[
            Helper(id=1, name="NoAno", role_preferences=no_ano),
            Helper(id=2, name="Ano", role_preferences=with_ano),
        ],
    )

    result = _solve(comp)

    assert _role_of(result, 1) == Role.Zaloha
    assert _role_of(result, 2) == Role.Opravovatel
