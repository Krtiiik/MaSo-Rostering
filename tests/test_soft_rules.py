"""Hard and soft Tag / Forced friends rules: a rule is hard unless switched to soft.
A soft rule is a weighted penalty in the ordinary objective (it may be broken for a
better roster), is still reported as a Broken rule (marked soft), keeps its own
identity next to a hard rule on the same value, and never refuses an edit.

Solver tests drive plain domain objects; mutation tests a temp-dir workspace of
synthetic Helpers (never anything from data/).
"""
import json

import pytest

from rostering import forced_friends, tags as tag_tree
from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    Role,
    RoleCapacity,
    Room,
    RuleInstance,
)
from rostering.forced_friends import ForcedGroup, Rule
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, SolverWeights, solve_competition
from rostering.tags import Tag
from rostering.webapp import mutations

from tests import tag_rules
from tests.test_forced_friends import workspace  # noqa: F401
from tests.test_tag_constraints import _seed

# -- the rule model ----------------------------------------------------------------


def test_a_rule_is_hard_unless_it_says_otherwise():
    assert Rule.share("room").hard and Rule.be("building", ["A"]).hard
    assert Rule.from_dict({"kind": "be", "axis": "building", "values": ["A"]}).hard  # saved before the toggle
    assert not Rule.share("room", hard=False).hard
    assert not Rule.be("building", ["A"], hard=False).hard


def test_a_hard_rule_is_saved_as_before_and_a_soft_one_says_so():
    assert Rule.share("room").to_dict() == {"kind": "share", "axis": "room"}
    assert Rule.be("building", ["A"]).to_dict() == {"kind": "be", "must": True, "axis": "building", "values": ["A"]}
    assert Rule.share("room", hard=False).to_dict() == {"kind": "share", "axis": "room", "hard": False}
    assert Rule.be("role", ["Menic"], hard=False).to_dict()["hard"] is False


def test_a_soft_rule_survives_its_saved_form():
    for rule in (Rule.share("role", hard=False), Rule.be("room", [("A", "A1")], must=False, hard=False)):
        assert Rule.from_dict(json.loads(json.dumps(rule.to_dict()))) == rule


def test_hardness_is_not_part_of_a_rules_identity():
    assert Rule.be("building", ["A"]).key == Rule.be("building", ["A"], hard=False).key
    assert Rule.share("room").key == Rule.share("room", hard=False).key
    with pytest.raises(ValueError, match="opakuje"):
        forced_friends.normalize_rules([Rule.share("room"), Rule.share("room", hard=False)])


def test_a_soft_rule_is_worded_as_soft():
    assert Rule.share("room", hard=False).text() == "musí sdílet místnost (měkké)"
    assert Rule.be("building", ["A"], hard=False).text() == "musí být v budově A (měkké)"
    assert Rule.be("building", ["A"]).text() == "musí být v budově A"


def test_only_hard_tag_rules_make_an_allowed_set():
    soft = Tag(id=1, name="T", colour="#3366cc", rules=(Rule.be("building", ["A"], hard=False),))
    hard = Tag(id=2, name="U", colour="#3366cc", rules=(Rule.be("building", ["B"]),))
    universe = ["A", "B", "C"]

    assert tag_tree.allowed_values([soft], [1], "building", universe) == universe  # a soft rule narrows nothing
    assert tag_tree.allowed_values([soft, hard], [1, 2], "building", universe) == ["B"]
    assert [r.tag.id for r in tag_tree.restrictions([soft, hard], [1, 2], "building", universe, hard=None)] == [1, 2]
    assert [r.tag.id for r in tag_tree.restrictions([soft, hard], [1, 2], "building", universe, hard=False)] == [1]


def test_a_soft_rule_does_not_make_a_dead_end_or_a_contradiction():
    soft_a = Tag(id=1, name="A", colour="#3366cc", rules=(Rule.be("building", ["A"], hard=False),))
    soft_b = Tag(id=2, name="B", colour="#3366cc", rules=(Rule.be("building", ["B"], hard=False),))
    assert tag_tree.dead_ends([soft_a, soft_b], {7: [1, 2]}, {"building": ["A", "B"]}) == set()

    layout = {"A": ["A1"], "B": ["B1"]}
    clash = [Rule.be("building", ["A"]), Rule.be("building", ["B"], hard=False)]
    assert forced_friends.contradictions(clash, layout) == []
    assert forced_friends.contradictions([Rule.be("building", ["A"]), Rule.be("building", ["B"])], layout)


# -- group rules: hardness per rule and per share axis ------------------------------


def _helper(hid, **extra):
    return Helper(id=hid, name=f"H{hid}", person_id=f"p{hid}", **extra)


def _rules_of(*rules, members=("p1", "p2")):
    group = ForcedGroup(id=1, name="G", rules=tuple(rules), person_ids=members)
    found = forced_friends.group_rules([_helper(1), _helper(2)], [group])
    return [(r.axis, r.hard) for r in found]


def test_a_soft_building_next_to_a_hard_room_adds_nothing():
    assert _rules_of(Rule.share("room"), Rule.share("building", hard=False)) == [("room", True)]


def test_a_soft_room_next_to_a_hard_building_leaves_both_in_force():
    found = _rules_of(Rule.share("building"), Rule.share("room", hard=False))
    assert sorted(found) == [("building", True), ("room", False)]


def test_two_soft_share_rules_are_judged_on_the_room_alone():
    assert _rules_of(Rule.share("building", hard=False), Rule.share("room", hard=False)) == [("room", False)]


def test_a_soft_be_rule_carries_its_hardness_into_the_group_rule():
    assert _rules_of(Rule.be("building", ["A"], hard=False), members=("p1",)) == [("building", False)]


def test_a_soft_rule_does_not_make_a_group_tag_clash():
    group = ForcedGroup(id=1, name="G", rules=(Rule.share("building", hard=False),), person_ids=("p1", "p2"))
    only_a = Tag(id=1, name="A", colour="#3366cc", rules=(Rule.be("building", ["A"]),))
    only_b = Tag(id=2, name="B", colour="#3366cc", rules=(Rule.be("building", ["B"]),))
    helpers = [_helper(1, tags=[1]), _helper(2, tags=[2])]
    universes = {"building": ["A", "B"], "role": [r.name for r in Role]}

    assert forced_friends.tag_clashes([group], helpers, [only_a, only_b], universes) == []
    hard_group = ForcedGroup(id=1, name="G", rules=(Rule.share("building"),), person_ids=("p1", "p2"))
    assert forced_friends.tag_clashes([hard_group], helpers, [only_a, only_b], universes)


# -- the solver and the live checker, on domain objects ----------------------------


def _solver_config(**weights):
    return SolverConfig(weights=SolverWeights(**weights), time_limit_seconds=10)


def _room(name):
    return Room(name=name, capacities={Role.Zaloha: RoleCapacity(minimum=0)})


def _building(name):
    return Building(name=name, rooms=[_room(f"{name}1"), _room(f"{name}2")])


def _prefers(building):
    return {"building_preferences": frozenset({building})}


def _comp(helpers, tags=(), groups=(), buildings=("A", "B")):
    return Competition(
        buildings={name: _building(name) for name in buildings},
        helpers=helpers,
        tags=list(tags),
        forced_groups=list(groups),
    )


def _by_helper(result):
    return {a.helper_id: a for a in result.assignments}


def _tag(*rules):
    return Tag(id=1, name="T", colour="#3366cc", rules=tuple(rules))


def _agreed(comp, result):
    """The live checker names exactly the solver's Broken rules, soft ones included."""
    live = {b.instance: (b.family, b.amount, b.line, b.soft) for b in check_roster(comp, result.assignments)}
    solved = {b.instance: (b.family, b.amount, b.line, b.soft) for b in result.broken_rules}
    assert live == solved


def test_a_hard_tag_rule_beats_a_building_preference():
    comp = _comp([_helper(1, tags=[1], **_prefers("B"))], [_tag(Rule.be("building", ["A"]))])

    result = solve_competition(comp, _solver_config())

    assert _by_helper(result)[1].building == "A" and result.broken_rules == []


def test_a_soft_tag_rule_gives_way_to_a_stronger_preference_and_is_reported_as_soft():
    comp = _comp([_helper(1, tags=[1], **_prefers("B"))], [_tag(Rule.be("building", ["A"], hard=False))])

    result = solve_competition(comp, _solver_config())  # a mismatch costs 3, the soft rule 2

    assert _by_helper(result)[1].building == "B"
    (broken,) = result.broken_rules
    assert broken.soft and broken.instance == RuleInstance("tag_building_soft", (1, "B"))
    assert broken.family == "tag_restrictions" and "(měkké)" in broken.line
    _agreed(comp, result)


def test_a_heavier_soft_weight_makes_the_solver_keep_the_soft_tag_rule():
    comp = _comp([_helper(1, tags=[1], **_prefers("B"))], [_tag(Rule.be("building", ["A"], hard=False))])

    result = solve_competition(comp, _solver_config(soft_rule=10))

    assert _by_helper(result)[1].building == "A" and result.broken_rules == []


def test_a_soft_rule_is_kept_when_nothing_else_asks_otherwise():
    comp = _comp([_helper(1, tags=[1], can_bring_camera=True)], [_tag(Rule.be("role", ["Fotograf"], hard=False))])

    result = solve_competition(comp, _solver_config())

    assert _by_helper(result)[1].role == Role.Fotograf and result.broken_rules == []


def test_a_hard_rule_wins_over_a_soft_one_that_contradicts_it():
    rules = [Rule.be("building", ["A"], must=False), Rule.be("building", ["A"], hard=False)]
    # Same key: build the soft rule on another tag so both stand.
    hard_tag = Tag(id=1, name="H", colour="#3366cc", rules=(rules[0],))
    soft_tag = Tag(id=2, name="S", colour="#3366cc", rules=(rules[1],))
    comp = _comp([_helper(1, tags=[1, 2], **_prefers("A"))], [hard_tag, soft_tag])

    result = solve_competition(comp, _solver_config(soft_rule=1000))

    assert _by_helper(result)[1].building == "B"  # the hard "not A" held, the soft "must A" gave way
    assert [b.soft for b in result.broken_rules] == [True]
    _agreed(comp, result)


def test_one_value_blocked_by_a_hard_and_a_soft_rule_is_two_broken_rules():
    hard_tag = Tag(id=1, name="H", colour="#3366cc", rules=(Rule.be("building", ["B"], must=False),))
    soft_tag = Tag(id=2, name="S", colour="#3366cc", rules=(Rule.be("building", ["A"], hard=False),))
    comp = _comp([_helper(1, tags=[1, 2])], [hard_tag, soft_tag])
    pinned = Assignment(helper_id=1, helper_name="H1", building="B", room="B1", role=Role.Zaloha)

    result = solve_competition(comp, _solver_config(), fixed_assignments=[pinned])

    assert {(b.instance.kind, b.soft) for b in result.broken_rules} == {("tag_building", False), ("tag_building_soft", True)}
    _agreed(comp, result)


def _split_pair():
    return [_helper(1, **_prefers("A")), _helper(2, **_prefers("B"))]


def test_a_hard_share_rule_keeps_the_group_together():
    group = ForcedGroup(id=1, name="G", rules=(Rule.share("building"),), person_ids=("p1", "p2"))

    result = solve_competition(_comp(_split_pair(), groups=[group]), _solver_config())

    assert len({a.building for a in result.assignments}) == 1 and result.broken_rules == []


def test_a_soft_share_rule_lets_the_group_split_for_their_preferences():
    group = ForcedGroup(id=1, name="G", rules=(Rule.share("building", hard=False),), person_ids=("p1", "p2"))
    comp = _comp(_split_pair(), groups=[group])

    result = solve_competition(comp, _solver_config())  # splitting costs 2, a mismatch 3

    assert {a.building for a in result.assignments} == {"A", "B"}
    (broken,) = result.broken_rules
    assert broken.soft and broken.amount == 1 and broken.family == "forced_friends"
    _agreed(comp, result)

    kept = solve_competition(comp, _solver_config(soft_rule=10))
    assert len({a.building for a in kept.assignments}) == 1 and kept.broken_rules == []


def test_a_soft_be_rule_of_a_group_is_a_penalty_per_member_and_worded_soft():
    rule = Rule.be("building", ["A"], hard=False)
    group = ForcedGroup(id=1, name="G", rules=(rule,), person_ids=("p1", "p2"))
    comp = _comp([_helper(1, **_prefers("B")), _helper(2, **_prefers("B"))], groups=[group])

    result = solve_competition(comp, _solver_config())

    (broken,) = result.broken_rules
    assert broken.soft and broken.amount == 2 and "musí být v budově A (měkké)" in broken.line
    _agreed(comp, result)


def test_a_zero_soft_weight_ignores_the_rule_but_still_reports_it():
    comp = _comp([_helper(1, tags=[1], **_prefers("B"))], [_tag(Rule.be("building", ["A"], hard=False))])

    result = solve_competition(comp, _solver_config(soft_rule=0))

    assert _by_helper(result)[1].building == "B" and [b.soft for b in result.broken_rules] == [True]


def test_a_hard_rule_still_dominates_the_soft_weight():
    # A hard share rule against a soft one that pulls elsewhere: the hard one holds.
    group = ForcedGroup(id=1, name="G", rules=(Rule.share("building"),), person_ids=("p1", "p2"))
    soft = Tag(id=1, name="S", colour="#3366cc", rules=(Rule.be("building", ["A"], hard=False),))
    helpers = [_helper(1, tags=[1], **_prefers("B")), _helper(2, **_prefers("B"))]

    result = solve_competition(_comp(helpers, [soft], [group]), _solver_config(soft_rule=1000))

    assert not any(not b.soft for b in result.broken_rules)
    assert len({a.building for a in result.assignments}) == 1


# -- through the mutation layer ------------------------------------------------------


def _soft(rule):
    return {**rule, "hard": False}


def test_a_soft_tag_rule_is_saved_and_never_refuses_an_edit(workspace):
    _seed(workspace)
    a = tag_rules.add_tag(workspace, "A", rules=[_soft(tag_rules.rule("building", ["Karlín"]))])["tags"][0]["id"]
    state = tag_rules.add_tag(workspace, "B", rules=[tag_rules.rule("building", ["Impakt"])])
    b = next(t["id"] for t in state["tags"] if t["name"] == "B")
    saved = next(t for t in state["tags"] if t["id"] == a)
    assert saved["rules"][0]["hard"] is False

    mutations.set_helper_tags(workspace, 1, [b])
    mutations.set_helper_tags(workspace, 1, [a, b])  # a hard pair would strand Anna; a soft one does not

    allowed = mutations.helper_allowed(mutations.get_state(workspace), 1)
    assert allowed["buildings"] == ["Impakt"]


def test_a_hard_tag_rule_saved_the_old_way_stays_hard(workspace):
    _seed(workspace)
    state = tag_rules.add_tag(workspace, "A", building_allow=["Karlín"])

    assert "hard" not in state["tags"][0]["rules"][0]
    assert tag_tree.tag_from_dict(state["tags"][0]).rules[0].hard


def test_a_hand_move_that_breaks_a_soft_tag_rule_is_reported_as_soft_and_still_toasts(workspace):
    _seed(workspace)
    tag_id = next(
        t["id"]
        for t in tag_rules.add_tag(workspace, "8.M", rules=[_soft(tag_rules.rule("building", ["Karlín"]))])["tags"]
    )
    mutations.set_helper_tags(workspace, 1, [tag_id])
    state = workspace.load()
    state["assignments"] = [
        {"helper_id": i, "helper_name": n, "building": "Karlín", "room": "Karlín-R1", "role": "Zaloha"}
        for i, n in ((1, "Anna"), (2, "Petr"), (3, "Jana"))
    ]
    workspace.save(state)
    before = mutations.get_state(workspace)

    after = mutations.move_helper(workspace, 1, "Impakt", "Impakt-R1", "Zaloha")

    (broken,) = [b for b in mutations.broken_rules(after) if b.family == "tag_restrictions"]
    assert broken.soft and broken.line == "Pomocník Anna (Štítek 8.M, musí být v budově Karlín (měkké)) je zařazen(a) do Impakt"
    assert mutations.move_toast_lines(before, after) == [broken.line]
