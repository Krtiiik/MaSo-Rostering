"""Forced friends groups as a list of rules: ``share`` a Building / Room / Role,
and ``be`` (must / must not) in some Buildings or Rooms or have some Roles, all
holding at once. Covers the rule model, its migration from the old axes, the
provable contradictions, the solver and the live checker (which must agree), the
Organizer anchors, inert places, a group of one, and the Tag check against the
rules. Solver tests drive plain domain objects; mutation tests a temp-dir
workspace of synthetic Helpers (never anything from data/).
"""
import json
import random

import pytest

from rostering import forced_friends
from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    Organizer,
    Preference,
    Role,
    RoleCapacity,
    Room,
    RuleInstance,
)
from rostering.forced_friends import ForcedGroup, Rule
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.tags import Tag
from rostering.webapp import forced_groups, mutations

from tests.test_forced_friends import TWO_BUILDINGS, _group_named, _placed, _season, workspace  # noqa: F401

# -- the rule model ----------------------------------------------------------------


def test_rules_are_worded_in_czech():
    assert Rule.share("room").text() == "musí sdílet místnost"
    assert Rule.share("building").text() == "musí sdílet budovu"
    assert Rule.share("role").text() == "musí sdílet roli"
    assert Rule.be("building", ["Troja", "Impakt"]).text() == "musí být v budově Impakt nebo Troja"
    assert Rule.be("building", ["Troja", "Impakt", "Karlín"], must=False).text() == (
        "nesmí být v budově Impakt, Karlín ani Troja"
    )
    assert Rule.be("room", [("Troja", "N4")]).text() == "musí být v místnosti N4 (Troja)"
    assert Rule.be("role", ["Menic", "Skenovac"]).text() == "musí mít roli Měnič nebo Skenovač"
    assert Rule.be("role", ["Fotograf"], must=False).text() == "nesmí mít roli Fotograf"


def test_a_rules_values_are_a_set_so_their_order_does_not_matter():
    assert Rule.be("building", ["B", "A", "B"]) == Rule.be("building", ["A", "B"])
    assert Rule.be("building", ["B", "A"]).key == Rule.be("building", ["A", "B"]).key
    assert Rule.be("building", ["A"]).key != Rule.be("building", ["A"], must=False).key


def test_a_rule_survives_its_saved_form():
    for rule in (
        Rule.share("room"),
        Rule.be("building", ["A", "B"], must=False),
        Rule.be("room", [("A", "A1"), ("B", "B2")]),
        Rule.be("role", ["Menic"]),
    ):
        assert Rule.from_dict(json.loads(json.dumps(rule.to_dict()))) == rule


def test_malformed_rules_are_refused_in_czech():
    with pytest.raises(ValueError, match="alespoň jednu hodnotu"):
        Rule.be("building", [])
    with pytest.raises(ValueError, match="role neexistuje"):
        Rule.be("role", ["Kuchar"])
    with pytest.raises(ValueError, match="budova a název"):
        Rule.be("room", ["N4"])
    with pytest.raises(ValueError, match="alespoň jedno pravidlo"):
        forced_friends.normalize_rules([])
    with pytest.raises(ValueError, match="opakuje"):
        forced_friends.normalize_rules(["room", "room"])


def test_a_shared_room_already_is_a_shared_building():
    both = forced_friends.effective_rules(forced_friends.share_rules("building", "room"))
    assert both == forced_friends.effective_rules(forced_friends.share_rules("room"))
    assert both != forced_friends.effective_rules(forced_friends.share_rules("room", "role"))


def test_a_group_saved_with_axes_becomes_share_rules():
    assert forced_friends.legacy_rules(["building", "room"]) == [{"kind": "share", "axis": "room"}]
    assert forced_friends.legacy_rules(["building", "role"]) == [
        {"kind": "share", "axis": "building"},
        {"kind": "share", "axis": "role"},
    ]
    state = {"forced_groups": [{"id": 1, "name": "G", "axes": ["building", "room"], "members": []}]}
    assert forced_friends.migrate_state(state) is True
    assert state["forced_groups"] == [{"id": 1, "name": "G", "rules": [{"kind": "share", "axis": "room"}], "members": []}]
    assert forced_friends.migrate_state(state) is False


def test_a_stored_season_with_axes_is_migrated_on_load_and_in_versions(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])
    state = workspace.load()
    path = workspace.open_season_dir() / "state.json"
    state["forced_groups"][0].pop("rules")
    state["forced_groups"][0]["axes"] = ["building", "room"]
    path.write_text(json.dumps(state), encoding="utf-8")

    loaded = workspace.load()

    assert loaded["forced_groups"][0]["rules"] == [{"kind": "share", "axis": "room"}]
    assert "axes" not in loaded["forced_groups"][0]
    assert "axes" not in json.loads(path.read_text(encoding="utf-8"))["forced_groups"][0]  # written back


# -- provable contradictions -------------------------------------------------------

LAYOUT = {"A": ["A1", "A2"], "B": ["B1", "B2"]}


def _contradictions(*rules):
    return forced_friends.contradictions([Rule.from_dict(r) for r in rules], LAYOUT)


def test_rules_that_can_all_hold_for_one_member_are_not_contradictory():
    assert _contradictions(Rule.be("building", ["A"]), Rule.be("room", [("A", "A1"), ("B", "B1")])) == []
    assert _contradictions(Rule.be("building", ["A"]), Rule.be("building", ["B"], must=False)) == []
    assert _contradictions(Rule.be("room", [("A", "A1")]), Rule.be("room", [("A", "A2")], must=False)) == []
    assert _contradictions(Rule.be("role", ["Menic", "Skenovac"]), Rule.be("role", ["Menic"], must=False)) == []
    assert _contradictions(Rule.share("room"), Rule.be("building", ["A"])) == []


def test_two_must_rules_with_nothing_in_common_contradict():
    (problem,) = _contradictions(Rule.be("building", ["A"]), Rule.be("building", ["B"]))
    assert problem.startswith("žádná budova nevyhovuje")
    (problem,) = _contradictions(Rule.be("role", ["Menic"]), Rule.be("role", ["Skenovac"]))
    assert problem.startswith("žádná role nevyhovuje")


def test_a_must_rule_and_a_must_not_rule_covering_the_same_values_contradict():
    assert _contradictions(Rule.be("building", ["A"]), Rule.be("building", ["A"], must=False))
    assert _contradictions(Rule.be("building", ["A", "B"], must=False))  # no building is left
    assert _contradictions(Rule.be("role", ["Menic"]), Rule.be("role", ["Menic"], must=False))


def test_a_room_in_a_forbidden_building_contradicts():
    assert _contradictions(Rule.be("room", [("A", "A1")]), Rule.be("building", ["A"], must=False))
    assert _contradictions(Rule.be("building", ["B"]), Rule.be("room", [("A", "A1")]))
    problems = _contradictions(Rule.be("room", [("A", "A1")]), Rule.be("room", [("A", "A1")], must=False))
    assert problems and "místnost" in problems[0]


def test_rooms_all_forbidden_in_the_allowed_building_contradict():
    problems = _contradictions(Rule.be("building", ["A"]), Rule.be("room", [("A", "A1"), ("A", "A2")], must=False))
    assert problems and "místnost" in problems[0]


def test_values_the_layout_lacks_are_inert_and_so_never_contradict():
    assert _contradictions(Rule.be("building", ["A"]), Rule.be("building", ["Nikde"])) == []  # the second names nothing
    assert _contradictions(Rule.be("building", ["Nikde"], must=False)) == []


# -- the solver and the live checker, on domain objects ----------------------------


def _solver_config():
    return SolverConfig(time_limit_seconds=10)


def _room(name, **minimums):
    caps = {Role.Zaloha: RoleCapacity(minimum=0)}
    caps.update({Role[k]: RoleCapacity(minimum=v) for k, v in minimums.items()})
    return Room(name=name, capacities=caps)


def _building(name, *rooms):
    return Building(name=name, rooms=list(rooms) or [_room(f"{name}1"), _room(f"{name}2")])


def _helper(hid, **extra):
    return Helper(id=hid, name=f"H{hid}", person_id=f"p{hid}", **extra)


def _organizer(oid, building=None, room=None):
    return Organizer(id=oid, name=f"Org{oid}", person_id=f"o{oid}", building=building, room=room)


def _group(gid, rules, *members, name=None):
    return ForcedGroup(
        id=gid, name=name or f"G{gid}", rules=forced_friends.normalize_rules(rules), person_ids=tuple(members)
    )


def _competition(buildings, helpers, groups, organizers=()):
    return Competition(
        buildings={b.name: b for b in buildings},
        helpers=helpers,
        organizers=list(organizers),
        forced_groups=list(groups),
    )


def _by_helper(result):
    return {a.helper_id: a for a in result.assignments}


def _pin(hid, building, room, role=Role.Zaloha):
    return Assignment(helper_id=hid, helper_name=f"H{hid}", building=building, room=room, role=role)


def _prefers(building):
    return {"building_preferences": frozenset({building})}


def test_a_must_be_in_building_rule_holds_everyone_in_the_building():
    helpers = [_helper(1, **_prefers("B")), _helper(2, **_prefers("B")), _helper(3, **_prefers("B"))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_group(1, [Rule.be("building", ["A"])], "p1", "p2")]
    )

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].building == placed[2].building == "A"
    assert placed[3].building == "B"  # not in the group: left free


def test_a_must_not_be_in_building_rule_keeps_everyone_out():
    helpers = [_helper(1, **_prefers("A")), _helper(2, **_prefers("A"))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_group(1, [Rule.be("building", ["A"], must=False)], "p1", "p2")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert {a.building for a in result.assignments} == {"B"}


def test_a_building_rule_takes_any_of_its_values():
    helpers = [_helper(1, **_prefers("C")), _helper(2, **_prefers("C"))]
    comp = _competition(
        [_building("A"), _building("B"), _building("C")],
        helpers,
        [_group(1, [Rule.be("building", ["A", "B"])], "p1", "p2")],
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert {a.building for a in result.assignments} <= {"A", "B"}


def test_a_room_rule_pins_the_members_to_the_room_and_a_negated_one_keeps_them_out():
    helpers = [_helper(1, **_prefers("A")), _helper(2, **_prefers("A"))]
    buildings = [_building("A", _room("A1"), _room("A2")), _building("B", _room("B1"), _room("B2"))]
    inside = _competition(buildings, helpers, [_group(1, [Rule.be("room", [("B", "B2")])], "p1", "p2")])
    outside = _competition(
        buildings, helpers, [_group(1, [Rule.be("room", [("A", "A1"), ("A", "A2")], must=False)], "p1", "p2")]
    )

    result = solve_competition(inside, _solver_config())
    assert result.broken_rules == []
    assert {(a.building, a.room) for a in result.assignments} == {("B", "B2")}

    result = solve_competition(outside, _solver_config())
    assert result.broken_rules == []
    assert {a.building for a in result.assignments} == {"B"}


def test_a_role_rule_gives_every_member_one_of_the_roles_and_a_negated_one_denies_them():
    helpers = [_helper(1, role_preferences={Role.Skenovac: Preference.Ano}), _helper(2)]
    buildings = [_building("A")]
    must = _competition(buildings, helpers, [_group(1, [Rule.be("role", ["Menic", "Opravovatel"])], "p1", "p2")])
    denied = _competition(
        buildings,
        [_helper(1, role_preferences={Role.Skenovac: Preference.Ano}), _helper(2, role_preferences={Role.Skenovac: Preference.Ano})],
        [_group(1, [Rule.be("role", ["Skenovac"], must=False)], "p1", "p2")],
    )

    result = solve_competition(must, _solver_config())
    assert result.broken_rules == []
    assert {a.role for a in result.assignments} <= {Role.Menic, Role.Opravovatel}

    result = solve_competition(denied, _solver_config())
    assert result.broken_rules == []
    assert Role.Skenovac not in {a.role for a in result.assignments}


def test_rules_hold_together_a_shared_room_inside_the_allowed_building():
    helpers = [_helper(1, **_prefers("A")), _helper(2, **_prefers("B"))]
    buildings = [_building("A"), _building("B")]
    rules = [Rule.share("room"), Rule.be("building", ["B"])]
    comp = _competition(buildings, helpers, [_group(1, rules, "p1", "p2")])

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].building == placed[2].building == "B"
    assert placed[1].room == placed[2].room


def test_a_group_of_one_is_pinned_by_its_be_rule_but_a_share_rule_needs_two():
    helpers = [_helper(1, **_prefers("A")), _helper(2, **_prefers("A"))]
    buildings = [_building("A"), _building("B")]
    comp = _competition(
        buildings,
        helpers,
        [_group(1, [Rule.be("building", ["B"])], "p1"), _group(2, [Rule.share("room")], "p2")],
    )

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].building == "B"
    assert placed[2].building == "A"


def test_a_be_rule_that_cannot_hold_bends_and_names_who_breaks_it():
    helpers = [_helper(1), _helper(2)]
    comp = _competition(
        [_building("A"), _building("B")],
        helpers,
        [_group(1, [Rule.be("building", ["A"])], "p1", "p2", name="Team")],
    )

    result = solve_competition(comp, _solver_config(), fixed_assignments=[_pin(1, "B", "B1"), _pin(2, "A", "A1")])

    (broken,) = result.broken_rules
    assert broken.instance == RuleInstance("forced_friends", (1, "must:building:A"))
    assert broken.amount == 1
    assert broken.line == "Skupinka Team: pravidlo „musí být v budově A“ porušují H1 (B)"
    (live,) = check_roster(comp, result.assignments)
    assert (live.instance, live.amount, live.line) == (broken.instance, broken.amount, broken.line)
    assert live.helper_ids == (1,)
    assert live.cells == (("B", "B1", None),)


def test_a_negated_role_rule_is_worded_with_the_role_and_counts_every_offender():
    helpers = [_helper(1, can_bring_camera=True), _helper(2, can_bring_camera=True)]
    comp = _competition(
        [_building("A")], helpers, [_group(1, [Rule.be("role", ["Fotograf"], must=False)], "p1", "p2", name="Team")]
    )
    pins = [_pin(1, "A", "A1", Role.Fotograf), _pin(2, "A", "A1", Role.Fotograf)]

    result = solve_competition(comp, _solver_config(), fixed_assignments=pins)

    (broken,) = result.broken_rules
    assert broken.amount == 2
    assert broken.line == "Skupinka Team: pravidlo „nesmí mít roli Fotograf“ porušují H1 (Fotograf) a H2 (Fotograf)"


def test_every_rule_of_a_group_is_its_own_broken_rule():
    helpers = [_helper(1), _helper(2)]
    rules = [Rule.share("building"), Rule.be("building", ["A"])]
    comp = _competition([_building("A"), _building("B")], helpers, [_group(1, rules, "p1", "p2")])

    result = solve_competition(comp, _solver_config(), fixed_assignments=[_pin(1, "B", "B1"), _pin(2, "B", "B2")])

    assert [b.instance.entity for b in result.broken_rules] == [(1, "must:building:A")]  # they do share a building
    result = solve_competition(comp, _solver_config(), fixed_assignments=[_pin(1, "A", "A1"), _pin(2, "B", "B1")])
    assert sorted(b.instance.entity for b in result.broken_rules) == [(1, "must:building:A"), (1, "share:building")]


def test_a_be_rule_naming_only_places_the_layout_lacks_is_inert():
    helpers = [_helper(1, **_prefers("A"))]
    comp = _competition(
        [_building("A")], helpers, [_group(1, [Rule.be("building", ["Nikde"]), Rule.be("room", [("A", "Nic")])], "p1")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "A"
    assert forced_friends.group_rules(comp.helpers, comp.forced_groups, [], {"A": ["A1", "A2"]}) == []


def test_a_must_rule_keeps_only_the_values_the_layout_has():
    helpers = [_helper(1, **_prefers("A"))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_group(1, [Rule.be("building", ["B", "Nikde"])], "p1")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "B"


def test_a_be_rule_bends_before_equipment_does():
    # Fixed as Fotograf (1 has a camera); 2 has none, and a rule says 2 must be Fotograf.
    helpers = [_helper(1, can_bring_camera=True), _helper(2)]
    comp = _competition([_building("A")], helpers, [_group(1, [Rule.be("role", ["Fotograf"])], "p2")])

    result = solve_competition(comp, _solver_config())

    assert _by_helper(result)[2].role != Role.Fotograf
    assert [b.family for b in result.broken_rules] == ["forced_friends"]


# -- Organizers as anchors ---------------------------------------------------------


def test_an_organizer_standing_outside_the_allowed_building_breaks_the_rule_the_solver_cannot_fix():
    comp = _competition(
        [_building("A"), _building("B")],
        [_helper(1)],
        [_group(1, [Rule.be("building", ["A"])], "p1", "o1", name="Team")],
        [_organizer(1, "B", "B1")],
    )

    result = solve_competition(comp, _solver_config())

    (broken,) = result.broken_rules
    assert broken.amount == 1  # Helper 1 is placed in A; only the Organizer breaks it
    assert broken.line == "Skupinka Team: pravidlo „musí být v budově A“ porušují Org1 (organizátor) (B)"
    assert _by_helper(result)[1].building == "A"
    (live,) = check_roster(comp, result.assignments)
    assert (live.instance, live.amount, live.line) == (broken.instance, broken.amount, broken.line)
    assert live.organizer_ids == (1,)


def test_role_rules_never_apply_to_an_organizer():
    comp = _competition(
        [_building("A")],
        [_helper(1)],
        [_group(1, [Rule.be("role", ["Fotograf"], must=False)], "o1")],
        [_organizer(1, "A", "A1")],
    )

    # No Helper in the group and the Organizer is no anchor on a role rule: nothing to judge.
    assert forced_friends.group_rules(comp.helpers, comp.forced_groups, comp.organizers) == []
    result = solve_competition(comp, _solver_config())
    assert result.broken_rules == []


def test_a_building_level_organizer_is_judged_by_building_on_room_rules():
    buildings = [_building("A"), _building("B")]
    lead_b = _organizer(1, "B")
    must_a = _group(1, [Rule.be("room", [("A", "A1")])], "o1")
    must_b = _group(2, [Rule.be("room", [("B", "B2")])], "o1")
    never_b = _group(3, [Rule.be("room", [("B", "B1")], must=False)], "o1")

    def broken(group):
        comp = _competition(buildings, [], [group], [lead_b])
        return check_roster(comp, [])

    assert [b.instance.entity for b in broken(must_a)] == [(1, "must:room:A/A1")]  # not even the right building
    assert broken(must_b) == []  # in B: the room itself can't be judged, so it holds
    assert broken(never_b) == []  # never broken by a Building-level Organizer


def test_a_room_level_organizer_is_judged_by_their_room():
    buildings = [_building("A"), _building("B")]
    comp = _competition(
        buildings, [], [_group(1, [Rule.be("room", [("B", "B2")])], "o1")], [_organizer(1, "B", "B1")]
    )

    (broken,) = check_roster(comp, [])

    assert broken.line == "Skupinka G1: pravidlo „musí být v místnosti B2 (B)“ porušují Org1 (organizátor) (B1 (B))"


# -- random agreement between the solver and the checker ---------------------------


def _random_rules(rng):
    rules = []
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(["share", "building", "room", "role"])
        must = rng.random() < 0.6
        if kind == "share":
            rules.append(Rule.share(rng.choice(["building", "room", "role"])))
        elif kind == "building":
            rules.append(Rule.be("building", rng.sample(["B0", "B1", "B2"], rng.randint(1, 2)), must))
        elif kind == "room":
            rules.append(Rule.be("room", [(f"B{rng.randrange(3)}", f"B{rng.randrange(3)}R{rng.randrange(2)}")], must))
        else:
            rules.append(Rule.be("role", rng.sample([r.name for r in Role], rng.randint(1, 2)), must))
    # Only well-formed combinations: a room names a room that exists.
    return [r for r in rules if r.axis != "room" or r.kind == "share" or r.values[0][0] == r.values[0][1][:2]]


def _projection(broken_rules):
    return {b.instance: (b.family, b.amount, b.line) for b in broken_rules}


@pytest.mark.parametrize("seed", range(16))
def test_the_checker_agrees_with_the_solvers_own_bent_rules(seed):
    rng = random.Random(seed)
    buildings = [Building(name=f"B{b}", rooms=[_room(f"B{b}R{r}") for r in range(2)]) for b in range(3)]
    n = rng.randint(3, 7)
    helpers = [_helper(i, building_preferences=frozenset({f"B{rng.randrange(3)}"})) for i in range(1, n + 1)]
    organizers = [_organizer(1, rng.choice([None, "B0", "B1"]), None)]
    members = [f"p{i}" for i in range(1, n + 1)] + ["o1"]
    groups = []
    for gid in range(1, rng.randint(1, 3) + 1):
        rules = _random_rules(rng)
        if rules:
            groups.append(
                _group(gid, list({r.key: r for r in rules}.values()), *rng.sample(members, rng.randint(1, min(4, len(members)))))
            )
    comp = _competition(buildings, helpers, groups, organizers)
    fixed = [_pin(h.id, "B0", "B0R0") for h in helpers if h.id % 3 == 0]

    result = solve_competition(comp, _solver_config(), fixed_assignments=fixed)

    assert _projection(check_roster(comp, result.assignments)) == _projection(result.broken_rules)


# -- through the mutation layer ----------------------------------------------------


def _rules_of(state, name):
    return _group_named(state, name)["rules"]


def test_a_group_takes_a_list_of_rules_and_lists_them_in_words(workspace):
    _season(workspace)
    rules = [Rule.share("room"), Rule.be("building", ["A"]), Rule.be("role", ["Fotograf"], must=False)]

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], rules)

    group = _group_named(state, "Rodina")
    assert group["rules"] == [r.to_dict() for r in rules]
    assert group["rule_texts"] == ["musí sdílet místnost", "musí být v budově A", "nesmí mít roli Fotograf"]
    assert mutations.get_state(workspace)["forced_groups"][0]["rules"] == group["rules"]


def test_rules_given_as_saved_dicts_are_accepted(workspace):
    _season(workspace)

    state = forced_groups.add_group(
        workspace, "Rodina", ["p1"], [{"kind": "be", "must": True, "axis": "room", "values": [["A", "A1"]]}]
    )

    assert _rules_of(state, "Rodina") == [{"kind": "be", "must": True, "axis": "room", "values": [["A", "A1"]]}]


def test_a_repeated_or_contradictory_rule_list_is_refused(workspace):
    _season(workspace)

    with pytest.raises(mutations.RosteringError, match="opakuje"):
        forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], [Rule.share("room"), Rule.share("room")])
    with pytest.raises(mutations.RosteringError, match="si odporují"):
        forced_groups.add_group(
            workspace, "Rodina", ["p1", "p2"], [Rule.be("building", ["A"]), Rule.be("building", ["B"])]
        )
    with pytest.raises(mutations.RosteringError, match="si odporují"):
        forced_groups.add_group(
            workspace, "Rodina", ["p1", "p2"], [Rule.be("building", ["A"]), Rule.be("room", [("B", "B1")])]
        )
    with pytest.raises(mutations.RosteringError, match="alespoň jednu hodnotu"):
        forced_groups.add_group(
            workspace, "Rodina", ["p1", "p2"], [{"kind": "be", "must": True, "axis": "building", "values": []}]
        )
    assert mutations.get_state(workspace)["forced_groups"] == []


def test_a_rule_naming_a_place_the_season_lacks_is_refused_unless_the_group_already_had_it(workspace):
    _season(workspace)

    with pytest.raises(mutations.RosteringError, match="budova v tomto ročníku není: Troja"):
        forced_groups.add_group(workspace, "Rodina", ["p1"], [Rule.be("building", ["Troja"])])
    with pytest.raises(mutations.RosteringError, match="místnost v tomto ročníku není: N4 \\(A\\)"):
        forced_groups.add_group(workspace, "Rodina", ["p1"], [Rule.be("room", [("A", "N4")])])

    state = workspace.load()
    state["forced_groups"].append(
        {
            "id": 1,
            "name": "Stará",
            "rules": [Rule.be("building", ["Troja"]).to_dict()],
            "members": [{"person_id": "p1", "name": "Anna"}],
        }
    )
    state["next_forced_group_id"] = 2
    workspace.save(state)
    # Editing a group that already names a missing place keeps it (and adds a valid one).
    state = forced_groups.update_group(
        workspace, 1, rules=[Rule.be("building", ["Troja", "A"])]
    )
    assert _rules_of(state, "Stará") == [Rule.be("building", ["A", "Troja"]).to_dict()]


def test_a_missing_place_is_flagged_on_the_group(workspace):
    _season(workspace)
    state = workspace.load()
    state["forced_groups"].append(
        {
            "id": 1,
            "name": "Stará",
            "rules": [Rule.be("building", ["Troja", "A"]).to_dict(), Rule.be("room", [("Troja", "N4")]).to_dict()],
            "members": [{"person_id": "p1", "name": "Anna"}],
        }
    )
    workspace.save(state)

    group = _group_named(workspace.load(), "Stará")

    assert group["missing_places"] == [
        "Pravidlo „musí být v budově A nebo Troja“: budova Troja v tomto ročníku není, vynechá se",
        "Pravidlo „musí být v místnosti N4 (Troja)“: místnost N4 (Troja) v tomto ročníku není, neuplatní se",
    ]
    assert group["status"] == forced_groups.ACTIVE


def test_a_group_of_one_active_member_is_in_force_through_its_be_rules_only(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Sdílí", ["p1"], [Rule.share("room")])
    state = forced_groups.add_group(workspace, "Pevná", ["p2"], [Rule.share("room"), Rule.be("building", ["A"])])

    assert _group_named(state, "Sdílí")["status"] == forced_groups.DORMANT
    assert _group_named(state, "Sdílí")["reason"] == "Méně než dva aktivní členové (1 z 1)"
    assert _group_named(state, "Pevná")["status"] == forced_groups.ACTIVE
    assert mutations.grid_forced_groups(state) == {2: ["Pevná (musí sdílet místnost; musí být v budově A)"]}


def test_a_group_with_nobody_active_is_dormant_and_says_why(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Pevná", ["p1"], [Rule.be("building", ["A"])])

    state = mutations.set_cant_attend(workspace, 1, True)

    group = _group_named(state, "Pevná")
    assert group["status"] == forced_groups.DORMANT
    assert group["reason"] == "Žádný aktivní člen (0 z 1): Anna se nemůže zúčastnit"


def test_a_be_rule_is_judged_live_and_named_in_the_groups_violations(workspace):
    _season(workspace)
    state = forced_groups.add_group(workspace, "Pevná", ["p1", "p2"], [Rule.be("building", ["A"])])
    _placed(workspace, ("B", "B1", "Zaloha"), ("A", "A1", "Zaloha"))

    group = _group_named(mutations.get_state(workspace), "Pevná")

    assert group["status"] == forced_groups.VIOLATED
    assert group["violations"] == ["Skupinka Pevná: pravidlo „musí být v budově A“ porušují Anna (B)"]
    assert state["forced_groups"][0]["id"] == group["id"]


def test_editing_the_rules_stales_a_roster_but_a_rename_does_not(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"]), "Rodina")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"), ("A", "A1", "Zaloha"))

    state = forced_groups.update_group(workspace, gid, name="Rodinka")
    assert not mutations.stale_reasons(state)
    state = forced_groups.update_group(workspace, gid, rules=[Rule.share("room")])  # the same rules
    assert not mutations.stale_reasons(state)
    state = forced_groups.update_group(workspace, gid, rules=[Rule.share("room"), Rule.be("building", ["A"])])
    assert mutations.stale_reasons(state)


def test_dissolving_a_group_that_pinned_one_member_stales_the_roster(workspace):
    _season(workspace)
    gid = _group_named(forced_groups.add_group(workspace, "Pevná", ["p1"], [Rule.be("building", ["A"])]), "Pevná")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"))

    state = forced_groups.dissolve_group(workspace, gid)

    assert mutations.stale_reasons(state)


def test_a_solve_through_the_workspace_honours_a_be_rule(workspace):
    _season(workspace)
    state = workspace.load()
    for helper in state["helpers"]:
        helper["building_preferences"] = ["A"]
    workspace.save(state)
    forced_groups.add_group(workspace, "Pevná", ["p1", "p2"], [Rule.be("building", ["B"])])

    assert mutations.solve(workspace)

    placed = {a["helper_id"]: a["building"] for a in mutations.get_state(workspace)["assignments"]}
    assert placed[1] == placed[2] == "B"
    assert mutations.broken_rules(mutations.get_state(workspace)) == []


def test_make_forced_and_unforce_work_on_a_group_whose_axes_were_migrated(workspace):
    _season(workspace)
    mutations.update_helper(workspace, 1, friends=[2])
    state = workspace.load()
    state["forced_groups"].append(
        {
            "id": 1,
            "name": "Anna + Petr",
            "axes": ["building", "room"],
            "members": [{"person_id": "p1", "name": "Anna"}, {"person_id": "p2", "name": "Petr"}],
        }
    )
    state["next_forced_group_id"] = 2
    (workspace.open_season_dir() / "state.json").write_text(json.dumps(state), encoding="utf-8")

    assert forced_groups.friend_requests(workspace.load())[0]["forced"] is True
    with pytest.raises(mutations.RosteringError, match="už existuje"):
        forced_groups.make_forced(workspace, 1, 2)

    state = forced_groups.unforce(workspace, 1, 2)

    assert state["forced_groups"] == []


# -- Organizer warnings ------------------------------------------------------------


def test_organizer_notes_name_the_rules_that_cannot_judge_them(workspace):
    _season(workspace)
    state = mutations.add_organizer(workspace, "Marie")
    marie = state["organizers"][-1]
    state = mutations.assign_organizer(workspace, marie["id"], "VedouciBudovy", "B", None)

    assert forced_groups.organizer_notes(state, [marie["person_id"]], [Rule.share("role")]) == [
        "Role se na Marie neuplatní"
    ]
    assert forced_groups.organizer_notes(state, [marie["person_id"]], [Rule.share("room")]) == [
        "Marie vede celou budovu: místnost se u něj posuzuje jen podle budovy"
    ]
    assert forced_groups.organizer_notes(state, [marie["person_id"], "p1"], [Rule.share("building")]) == []


# -- Tags against the rules --------------------------------------------------------


def _tag(workspace, name, **constraints):
    state = mutations.add_tag(workspace, name, **constraints)
    return next(t["id"] for t in state["tags"] if t["name"] == name)


def test_a_be_rule_no_member_can_meet_for_their_tags_is_refused(workspace):
    _season(workspace)
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_b])

    with pytest.raises(mutations.RosteringError, match="nemůže splnit svá pravidla") as caught:
        forced_groups.add_group(workspace, "Pevná", ["p1", "p2"], [Rule.be("building", ["A"])])

    assert "Anna: jen B" in str(caught.value)
    assert mutations.get_state(workspace)["forced_groups"] == []
    # Someone whose Tags allow it makes no clash, and neither does another rule value.
    forced_groups.add_group(workspace, "Pevná", ["p2"], [Rule.be("building", ["A"])])
    forced_groups.add_group(workspace, "Druhá", ["p1", "p2"], [Rule.be("building", ["A", "B"])])


def test_a_role_rule_against_role_tags_is_refused(workspace):
    _season(workspace)
    no_foto = _tag(workspace, "NoFoto", role_deny=["Fotograf"])
    mutations.set_helper_tags(workspace, 1, [no_foto])

    with pytest.raises(mutations.RosteringError, match="nemůže splnit svá pravidla"):
        forced_groups.add_group(workspace, "Foto", ["p1"], [Rule.be("role", ["Fotograf"])])
    forced_groups.add_group(workspace, "Foto", ["p1"], [Rule.be("role", ["Fotograf"], must=False)])


def test_a_room_rule_is_judged_by_its_building_for_tags(workspace):
    _season(workspace)
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_b])

    with pytest.raises(mutations.RosteringError, match="nemůže splnit svá pravidla"):
        forced_groups.add_group(workspace, "Pevná", ["p1"], [Rule.be("room", [("A", "A1")])])
    forced_groups.add_group(workspace, "Pevná", ["p1"], [Rule.be("room", [("A", "A1")], must=False)])


def test_a_tag_change_that_would_leave_a_member_nothing_the_rules_allow_is_refused(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Pevná", ["p1", "p2"], [Rule.be("building", ["A"])])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])

    with pytest.raises(mutations.RosteringError, match="Pevná"):
        mutations.set_helper_tags(workspace, 1, [only_b])

    assert mutations.get_state(workspace)["helpers"][0].get("tags", []) == []


def test_the_share_message_is_kept_when_the_members_have_nothing_in_common(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    mutations.set_helper_tags(workspace, 2, [only_b])

    with pytest.raises(mutations.RosteringError, match="nemůže sdílet budovu"):
        forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], [Rule.share("building")])


def test_imports_copy_the_rules_whole(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Pevná", ["p1", "p2"], [Rule.share("room"), Rule.be("building", ["A"])])
    source = workspace.open_season()["id"]
    state = workspace.load()
    workspace.create_season("2026-podzim", {**workspace.empty_state(), "helpers": state["helpers"], "config": state["config"]})

    summary = mutations.import_from_season(workspace, source)

    (group,) = mutations.get_state(workspace)["forced_groups"]
    assert group["rules"] == [Rule.share("room").to_dict(), Rule.be("building", ["A"]).to_dict()]
    overview = mutations.import_overview(workspace, source)["sections"][0]["groups"]
    assert overview[0]["rule_texts"] == ["musí sdílet místnost", "musí být v budově A"]
    assert overview[0]["already_present"] is True
    assert summary["sections"][-1]["groups_imported"] == ["Pevná"]
