"""Forced friends groups: named hard constraints on a set of Persons who must
share the ticked axes (Building, Room and/or Role; Room implies Building), their
enforcement by the solver (as the Forced-friend tier of the relaxation) and by
the live Broken-rule checker, and their lifecycle through the mutation layer.

Mutation-layer tests run against a temp-dir workspace seeded with synthetic
Helpers (never anything from data/); the solver tests drive it on domain objects.
"""
import importlib
import random

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
from rostering.forced_friends import ForcedGroup
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.webapp import forced_groups, mutations
from rostering.tags import Tag

# -- the solver, on domain objects ------------------------------------------------


def _solver_config():
    return SolverConfig(time_limit_seconds=10)


def _room(name, **minimums):
    caps = {Role.Zaloha: RoleCapacity(minimum=0)}
    caps.update({Role[k]: RoleCapacity(minimum=v) for k, v in minimums.items()})
    return Room(name=name, capacities=caps)


def _building(name, *rooms, **capacities):
    return Building(
        name=name,
        rooms=list(rooms) or [_room(f"{name}-R1")],
        capacities={Role[k]: RoleCapacity(minimum=v) for k, v in capacities.items()},
    )


def _helper(hid, **extra):
    return Helper(id=hid, name=f"H{hid}", person_id=f"p{hid}", **extra)


def _group(gid, axes, *hids, name=None):
    return ForcedGroup(id=gid, name=name or f"G{gid}", axes=tuple(axes), person_ids=tuple(f"p{h}" for h in hids))


def _competition(buildings, helpers, groups, tags=()):
    return Competition(
        buildings={b.name: b for b in buildings}, helpers=helpers, tags=list(tags), forced_groups=list(groups)
    )


def _by_helper(result):
    return {a.helper_id: a for a in result.assignments}


def _pin(hid, building, room, role=Role.Zaloha):
    return Assignment(helper_id=hid, helper_name=f"H{hid}", building=building, room=room, role=role)


def _scattering_preferences():
    """Preferences that pull each Helper to a different Building/Role, so a
    group only holds because the rule makes it."""
    return {Role.Zaloha: Preference.Ne, Role.Opravovatel: Preference.Ano}


def test_a_building_group_is_placed_in_one_building():
    # Each member would rather be somewhere else (building preference), and the
    # buildings have room for everybody: only the group rule keeps them together.
    helpers = [
        _helper(1, building_preferences=frozenset({"A"})),
        _helper(2, building_preferences=frozenset({"B"})),
        _helper(3, building_preferences=frozenset({"C"})),
    ]
    comp = _competition(
        [_building("A"), _building("B"), _building("C")], helpers, [_group(1, ["building"], 1, 2, 3)]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert len({a.building for a in result.assignments}) == 1


def test_a_room_group_shares_a_room_and_so_a_building():
    helpers = [
        _helper(1, building_preferences=frozenset({"A"})),
        _helper(2, building_preferences=frozenset({"B"})),
    ]
    buildings = [_building("A", _room("A1"), _room("A2")), _building("B", _room("B1"), _room("B2"))]
    comp = _competition(buildings, helpers, [_group(1, ["building", "room"], 1, 2)])

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert (placed[1].building, placed[1].room) == (placed[2].building, placed[2].room)


def test_a_room_and_role_group_shares_both():
    helpers = [
        _helper(1, role_preferences={Role.Skenovac: Preference.Ano}, building_preferences=frozenset({"A"})),
        _helper(2, role_preferences={Role.Menic: Preference.Ano}, building_preferences=frozenset({"B"})),
    ]
    buildings = [_building("A", _room("A1"), _room("A2")), _building("B", _room("B1"))]
    comp = _competition(buildings, helpers, [_group(1, ["building", "room", "role"], 1, 2)])

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert (placed[1].building, placed[1].room, placed[1].role) == (
        placed[2].building,
        placed[2].room,
        placed[2].role,
    )


def test_overlapping_groups_both_hold_and_are_never_merged():
    # 1+2 share a Building, 2+3 share a Building: transitively one Building for
    # all three, but 4 (in neither group) is left free, and the groups differ in
    # axes (2+3 also share a Role) without leaking into each other.
    helpers = [
        _helper(1, building_preferences=frozenset({"A"})),
        _helper(2, building_preferences=frozenset({"B"})),
        _helper(3, building_preferences=frozenset({"C"}), role_preferences={Role.Skenovac: Preference.Ano}),
        _helper(4, building_preferences=frozenset({"C"})),
    ]
    groups = [_group(1, ["building"], 1, 2), _group(2, ["building", "role"], 2, 3)]
    comp = _competition([_building("A"), _building("B"), _building("C")], helpers, groups)

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].building == placed[2].building == placed[3].building
    assert placed[2].role == placed[3].role


def test_a_member_who_cant_attend_is_ignored():
    helpers = [
        _helper(1, building_preferences=frozenset({"A"})),
        _helper(2, building_preferences=frozenset({"B"}), cant_attend=True),
        _helper(3, building_preferences=frozenset({"A"})),
    ]
    comp = _competition([_building("A"), _building("B")], helpers, [_group(1, ["building"], 1, 2, 3)])

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert {a.building for a in result.assignments} == {"A"}


def test_a_member_who_is_not_registered_is_ignored_and_a_group_of_one_constrains_nothing():
    helpers = [_helper(1, building_preferences=frozenset({"A"})), _helper(2, building_preferences=frozenset({"B"}))]
    # p9 registered nobody this Season; with p2 absent the group has one active member.
    group = ForcedGroup(id=1, name="G", axes=("building",), person_ids=("p1", "p9"))
    comp = _competition([_building("A"), _building("B")], helpers, [group])

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    placed = _by_helper(result)
    assert (placed[1].building, placed[2].building) == ("A", "B")


def test_a_group_that_cannot_hold_still_yields_a_roster_and_is_reported():
    comp = _competition(
        [_building("A"), _building("B")], [_helper(1), _helper(2)], [_group(1, ["building"], 1, 2, name="Rodina")]
    )
    fixed = [_pin(1, "A", "A-R1"), _pin(2, "B", "B-R1")]

    result = solve_competition(comp, _solver_config(), fixed_assignments=fixed)

    assert len(result.assignments) == 2
    (broken,) = result.broken_rules
    assert broken.family == "forced_friends"
    assert broken.instance == RuleInstance("forced_friends", (1, "building"))
    assert broken.amount == 1
    assert broken.line.startswith("Skupinka Rodina")


def test_a_minimum_bends_before_a_forced_group_does():
    # Building A needs a Skenovač, but the whole group is pulled to B.
    helpers = [
        _helper(1, building_preferences=frozenset({"A"}), role_preferences={Role.Skenovac: Preference.Ano}),
        _helper(2, building_preferences=frozenset({"B"})),
    ]
    buildings = [_building("A", _room("A-R1", Skenovac=1)), _building("B")]
    fixed = [_pin(2, "B", "B-R1")]
    comp = _competition(buildings, helpers, [_group(1, ["building"], 1, 2)])

    result = solve_competition(comp, _solver_config(), fixed_assignments=fixed)

    assert _by_helper(result)[1].building == "B"
    assert [b.family for b in result.broken_rules] == ["minimums"]


def test_a_tag_restriction_bends_before_a_forced_group_does():
    # 1 may only be in A, 2 is fixed in B: the group is kept and the Tag bent.
    tags = [Tag(id=1, name="OnlyA", colour="#3366cc", building_allow=("A",))]
    helpers = [_helper(1, tags=[1]), _helper(2)]
    comp = _competition([_building("A"), _building("B")], helpers, [_group(1, ["building"], 1, 2)], tags)

    result = solve_competition(comp, _solver_config(), fixed_assignments=[_pin(2, "B", "B-R1")])

    assert _by_helper(result)[1].building == "B"
    assert [b.family for b in result.broken_rules] == ["tag_restrictions"]


def test_a_forced_group_bends_before_equipment_does():
    # The group shares its Role; 1 is fixed as Fotograf, 2 has no camera: the
    # group breaks rather than making 2 an equipment-less Fotograf.
    comp = _competition([_building("A")], [_helper(1, can_bring_camera=True), _helper(2)], [_group(1, ["role"], 1, 2)])

    result = solve_competition(comp, _solver_config(), fixed_assignments=[_pin(1, "A", "A-R1", Role.Fotograf)])

    assert _by_helper(result)[2].role != Role.Fotograf
    assert [b.family for b in result.broken_rules] == ["forced_friends"]


def _random_group_competition(rng):
    buildings = [
        Building(name=f"B{b}", rooms=[_room(f"B{b}R{r}", **({"Skenovac": 1} if rng.random() < 0.4 else {})) for r in range(2)])
        for b in range(3)
    ]
    n = rng.randint(3, 8)
    helpers = [
        _helper(
            i,
            can_bring_camera=rng.random() < 0.4,
            building_preferences=frozenset({f"B{rng.randrange(3)}"}),
        )
        for i in range(1, n + 1)
    ]
    groups = []
    for gid in range(1, rng.randint(2, 3) + 1):
        axes = rng.choice([["building"], ["building", "room"], ["role"], ["building", "room", "role"]])
        groups.append(_group(gid, axes, *rng.sample(range(1, n + 1), rng.randint(2, min(4, n)))))
    return _competition(buildings, helpers, groups)


def _projection(broken_rules):
    return {b.instance: (b.family, b.amount, b.line) for b in broken_rules}


@pytest.mark.parametrize("seed", range(12))
def test_the_checker_agrees_with_the_solvers_own_bent_groups(seed):
    comp = _random_group_competition(random.Random(seed))
    fixed = [_pin(h.id, "B0", "B0R0") for h in comp.helpers if h.id % 3 == 0]
    fixed += [_pin(h.id, "B1", "B1R1") for h in comp.helpers if h.id % 3 == 1 and h.id % 2 == 0]

    result = solve_competition(comp, _solver_config(), fixed_assignments=fixed)

    assert _projection(check_roster(comp, result.assignments)) == _projection(result.broken_rules)


# -- through the mutation layer: a temp-dir workspace of synthetic Helpers --------


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "workspace")


TWO_BUILDINGS = [
    {
        "name": name,
        "rooms": [
            {"name": f"{name}1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": f"{name}2", "capacities": {"Zaloha": {"minimum": 0}}},
        ],
        "capacities": {},
    }
    for name in ("A", "B")
]


def _record(hid, name, **extra):
    return {
        "id": hid,
        "name": name,
        "person_id": f"p{hid}",
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
        **extra,
    }


def _season(workspace, names=("Anna", "Petr", "Jana", "Eva"), label="2026-jaro"):
    """An open Season of synthetic Helpers p1.. (one per name) and two Buildings."""
    state = workspace.empty_state()
    state["helpers"] = [_record(i, name) for i, name in enumerate(names, start=1)]
    state["config"] = TWO_BUILDINGS
    workspace.create_season(label, state)
    return workspace.load()


def _placed(workspace, *cells):
    """Place helpers 1.. by hand: each cell is (building, room, role)."""
    for hid, (building, room, role) in enumerate(cells, start=1):
        state = mutations.move_helper(workspace, hid, building, room, role)
    return state


def _group_named(state, name):
    return next(g for g in forced_groups.list_groups(state) if g["name"] == name)


def test_a_group_has_a_required_name_axes_and_members_who_are_persons(workspace):
    _season(workspace)

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])

    group = _group_named(state, "Rodina")
    assert group["axes"] == ["building", "room"]  # ticking Room implies Building
    assert [(m["person_id"], m["name"], m["state"]) for m in group["members"]] == [
        ("p1", "Anna", "active"),
        ("p2", "Petr", "active"),
    ]
    assert group["active"] is True
    assert forced_groups.list_groups(mutations.get_state(workspace)) == forced_groups.list_groups(state)  # saved


def test_a_group_needs_a_name_and_at_least_one_axis(workspace):
    _season(workspace)

    with pytest.raises(mutations.RosteringError, match="název"):
        forced_groups.add_group(workspace, "  ", ["p1", "p2"], ["building"])
    with pytest.raises(mutations.RosteringError, match="osu"):
        forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], [])
    assert forced_groups.list_groups(mutations.get_state(workspace)) == []


def test_only_registered_people_can_be_picked(workspace):
    _season(workspace)

    with pytest.raises(mutations.RosteringError, match="registrováni"):
        forced_groups.add_group(workspace, "Rodina", ["p1", "p99"], ["building"])


def test_a_group_can_be_renamed_and_edited(workspace):
    _season(workspace)
    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    gid = _group_named(state, "Rodina")["id"]

    state = forced_groups.update_group(workspace, gid, name="Tým", person_ids=["p1", "p2", "p3"], axes=["role"])

    group = _group_named(state, "Tým")
    assert group["axes"] == ["role"]
    assert [m["person_id"] for m in group["members"]] == ["p1", "p2", "p3"]
    with pytest.raises(mutations.RosteringError, match="název"):
        forced_groups.update_group(workspace, gid, name="")


def test_a_person_may_belong_to_several_groups_which_stay_separate(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "One", ["p1", "p2"], ["building"])
    state = forced_groups.add_group(workspace, "Two", ["p2", "p3"], ["role"])

    assert [g["name"] for g in forced_groups.list_groups(state)] == ["One", "Two"]
    assert _group_named(state, "One")["axes"] == ["building"]
    assert _group_named(state, "Two")["axes"] == ["role"]


def test_a_solve_through_the_workspace_honours_the_groups(workspace):
    _season(workspace)
    state = workspace.load()
    for helper, building in zip(state["helpers"], ("A", "B", "A", "B")):
        helper["building_preferences"] = [building]
    workspace.save(state)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])

    state = mutations.solve(workspace)

    by_helper = {a["helper_id"]: a for a in state["assignments"]}
    assert (by_helper[1]["building"], by_helper[1]["room"]) == (by_helper[2]["building"], by_helper[2]["room"])
    assert mutations.broken_rules(state) == []


# -- member states -----------------------------------------------------------------


def test_a_member_who_cant_attend_stays_but_is_inactive_and_flagged_and_is_restored(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2", "p3"], ["building"])

    state = mutations.set_cant_attend(workspace, 2, True)

    group = _group_named(state, "Rodina")
    assert [(m["name"], m["state"]) for m in group["members"]] == [
        ("Anna", "active"),
        ("Petr", "cant_attend"),
        ("Jana", "active"),
    ]
    assert group["active"] is True

    state = mutations.set_cant_attend(workspace, 2, False)

    assert [m["state"] for m in _group_named(state, "Rodina")["members"]] == ["active"] * 3


def test_a_member_not_registered_this_season_is_shown_as_such_and_never_blocks(workspace):
    _season(workspace)
    state = workspace.load()
    state["forced_groups"] = [
        {
            "id": 1,
            "name": "Rodina",
            "axes": ["building"],
            "members": [{"person_id": "p1", "name": "Anna"}, {"person_id": "gone", "name": "Karel"}],
        }
    ]
    workspace.save(state)

    group = _group_named(mutations.get_state(workspace), "Rodina")

    assert [(m["name"], m["state"]) for m in group["members"]] == [("Anna", "active"), ("Karel", "not_registered")]
    assert group["active"] is False  # one active member only


def test_an_unregistered_member_becomes_live_when_registered_and_recognized(workspace):
    earlier = workspace.empty_state()
    earlier["helpers"] = [_record(1, "Karel", email="karel@example.com", person_id="karel-person")]
    workspace.create_season("2025-podzim", earlier)
    _season(workspace, label="2026-jaro")
    state = workspace.load()
    state["forced_groups"] = [
        {
            "id": 1,
            "name": "Rodina",
            "axes": ["building"],
            "members": [{"person_id": "p1", "name": "Anna"}, {"person_id": "karel-person", "name": "Karel"}],
        }
    ]
    workspace.save(state)
    assert _group_named(mutations.get_state(workspace), "Rodina")["members"][1]["state"] == "not_registered"

    # Karel registers this Season, recognized by e-mail as the same Person.
    state = mutations.add_helper(workspace, "Karel Novák", "karel@example.com")

    group = _group_named(state, "Rodina")
    assert group["members"][1]["state"] == "active"
    assert group["active"] is True


def test_a_group_with_fewer_than_two_active_members_is_inactive_and_constrains_nothing(workspace):
    _season(workspace)
    state = workspace.load()
    for helper, building in zip(state["helpers"], ("A", "B")):
        helper["building_preferences"] = [building]
    workspace.save(state)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    state = mutations.set_cant_attend(workspace, 2, True)

    group = _group_named(state, "Rodina")
    assert group["active"] is False
    assert "méně než dva" in group["reason"].lower()

    state = mutations.solve(workspace)

    assert mutations.broken_rules(state) == []


# -- the stale roster --------------------------------------------------------------


def test_creating_a_group_after_a_solve_moves_no_one_and_makes_the_roster_stale(workspace):
    _season(workspace)
    solved = mutations.solve(workspace)
    assert mutations.stale_reasons(solved) == []

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    assert state["assignments"] == solved["assignments"]
    assert any("Rodina" in reason for reason in mutations.stale_reasons(state))


def test_editing_a_groups_members_or_axes_after_a_solve_makes_the_roster_stale(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"]), "Rodina")["id"]
    solved = mutations.solve(workspace)
    assert mutations.stale_reasons(solved) == []

    state = forced_groups.update_group(workspace, gid, axes=["role"])

    assert state["assignments"] == solved["assignments"]  # nobody moved
    assert any("Rodina" in reason for reason in mutations.stale_reasons(state))

    mutations.solve(workspace)
    state = forced_groups.update_group(workspace, gid, person_ids=["p1", "p2", "p3"])

    assert any("Rodina" in reason for reason in mutations.stale_reasons(state))


def test_creating_a_group_before_any_solve_raises_no_banner(workspace):
    _season(workspace)

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    assert mutations.stale_reasons(state) == []


def test_a_rename_alone_does_not_make_the_roster_stale(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"]), "Rodina")["id"]
    mutations.solve(workspace)

    state = forced_groups.update_group(workspace, gid, name="Rodinka")

    assert mutations.stale_reasons(state) == []


def test_dissolving_a_group_the_members_satisfy_raises_the_banner(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"]), "Rodina")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"), ("A", "A2", "Zaloha"))

    state = forced_groups.dissolve_group(workspace, gid)

    assert forced_groups.list_groups(state) == []
    assert any("Rodina" in reason for reason in mutations.stale_reasons(state))


def test_dissolving_a_group_that_was_not_pulling_anyone_raises_no_banner(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"]), "Rodina")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"), ("B", "B1", "Zaloha"))  # already split: it pulled nobody

    state = forced_groups.dissolve_group(workspace, gid)

    assert mutations.stale_reasons(state) == []


def test_dissolving_an_inactive_group_raises_no_banner(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1"], ["building"]), "Rodina")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"), ("A", "A2", "Zaloha"))

    state = forced_groups.dissolve_group(workspace, gid)

    assert mutations.stale_reasons(state) == []


# -- the live check, Versions, Start over, re-upload -------------------------------


def test_a_hand_move_that_splits_a_group_shows_as_a_broken_rule_and_still_applies(workspace):
    _season(workspace)
    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])
    gid = _group_named(state, "Rodina")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"), ("A", "A1", "Skenovac"))
    before = mutations.get_state(workspace)

    after = mutations.move_helper(workspace, 2, "B", "B1", "Skenovac")

    (broken,) = mutations.broken_rules(after)
    assert broken.instance == RuleInstance("forced_friends", (gid, "room"))
    assert broken.fix.tab == "forced_friends" and broken.fix.group_id == gid
    assert set(broken.helper_ids) == {1, 2}
    assert mutations.move_toast_lines(before, after) == [broken.line]
    assert {a["helper_id"]: a["building"] for a in after["assignments"]} == {1: "A", 2: "B"}


def test_groups_are_saved_in_versions(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    version = mutations.save_version(workspace, "with group")
    state = workspace.load()
    forced_groups.dissolve_group(workspace, _group_named(state, "Rodina")["id"])
    assert forced_groups.list_groups(mutations.get_state(workspace)) == []

    restored = mutations.restore_version(workspace, version["slug"])

    assert [g["name"] for g in forced_groups.list_groups(restored)] == ["Rodina"]


def test_start_over_clears_the_groups(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    state = mutations.reset_workspace(workspace)

    assert forced_groups.list_groups(state) == []


def test_a_state_saved_before_groups_existed_has_none(workspace):
    _season(workspace)
    state = workspace.load()
    state.pop("forced_groups")
    workspace.save(state)

    assert forced_groups.list_groups(mutations.get_state(workspace)) == []


def test_groups_are_kept_on_re_upload(workspace):
    from tests.test_reupload import ANNA, KLARA, PETR, _row, _upload

    state = _upload(workspace, _row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR), label="2026-jaro")
    person_ids = [h["person_id"] for h in state["helpers"]]
    forced_groups.add_group(workspace, "Rodina", person_ids, ["building"])

    state = _upload(workspace, _row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR), _row("Klára Malá", KLARA))

    (group,) = forced_groups.list_groups(state)
    assert group["name"] == "Rodina"
    assert [m["state"] for m in group["members"]] == ["active", "active"]


def test_place_new_registrants_applies_groups_to_newcomers_with_existing_assignments_fixed(workspace):
    _season(workspace)
    state = workspace.load()
    state["helpers"][1]["building_preferences"] = ["B"]  # Petr would rather be in B
    workspace.save(state)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    mutations.move_helper(workspace, 1, "A", "A1", "Zaloha")

    state = mutations.place_new_registrants(workspace)

    by_helper = {a["helper_id"]: a for a in state["assignments"]}
    assert (by_helper[1]["building"], by_helper[1]["room"]) == ("A", "A1")
    assert by_helper[2]["building"] == "A"
    assert mutations.broken_rules(state) == []
