"""Tag rules: a Tag's constraints are the same ``be`` rules a Forced friends group
has (see CONTEXT.md "Tag constraint"), including the Room axis the old
allow/deny lists did not have. Covers the shared rule model, the Room axis through
the allowed sets, the dead-end refusal, the solver and the live checker, older
saved Tags, Tag import and the rule editor's draft round trip.

Mutation-layer tests run against a temp-dir workspace with synthetic Helpers
(never anything from data/); the solver tests drive it on domain objects."""

import pytest

from rostering import tags as tag_tree
from rostering.domain import Building, Competition, Helper, Role, RoleCapacity, Room, RuleInstance
from rostering.persistence.workspace import Workspace
from rostering.placement_rules import BE, BUILDING, ROLE, ROOM, SHARE, Rule
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.webapp import mutations
from rostering.webapp.ui.tabs.rule_editor import draft_from_rule, rule_from_draft
from tests import tag_rules
from tests.tag_rules import rule
from tests.test_tag_import import ANNA, _season, _source_id, _tag, _tags_section


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    return Workspace(root=tmp_path / "workspace")


def _layout():
    """Two Buildings with two Rooms each."""
    return [
        {
            "name": name,
            "rooms": [{"name": f"{name}1", "capacities": {"Zaloha": {"minimum": 0}}}, {"name": f"{name}2", "capacities": {}}],
            "capacities": {},
        }
        for name in ("A", "B")
    ]


def _helper(helper_id, name):
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
    }


def _seed(workspace, names=("Anna", "Petr", "Jana")):
    state = workspace.load()
    state["helpers"] = [_helper(i, n) for i, n in enumerate(names, start=1)]
    workspace.save(state)
    mutations.put_config(workspace, _layout())


def _new_tag(workspace, name, **kwargs):
    state = mutations.add_tag(workspace, name, **kwargs)
    return next(t["id"] for t in state["tags"] if t["name"] == name)


# -- the shared rule model --------------------------------------------------------


def test_a_tag_stores_the_same_rule_dicts_a_group_does(workspace):
    _seed(workspace)
    saved = [rule(ROOM, [["A", "A1"]]), rule(ROLE, ["Fotograf"], must=False), rule(BUILDING, ["B"])]

    state = mutations.add_tag(workspace, "8.M", rules=saved)

    assert state["tags"][0]["rules"] == [Rule.from_dict(r).to_dict() for r in saved]
    tag = tag_tree.tag_from_dict(state["tags"][0])
    assert [r.text() for r in tag.rules] == [
        "musí být v místnosti A1 (A)",
        "nesmí mít roli Fotograf",
        "musí být v budově B",
    ]


def test_a_tag_keeps_a_share_rule_and_refuses_a_repeated_rule(workspace):
    _seed(workspace)

    state = mutations.add_tag(workspace, "8.M", rules=[{"kind": SHARE, "axis": ROOM}, rule(BUILDING, ["A"])])
    assert state["tags"][0]["rules"] == [{"kind": SHARE, "axis": ROOM}, rule(BUILDING, ["A"])]
    assert [r.text() for r in tag_tree.tag_from_dict(state["tags"][0]).rules] == [
        "musí sdílet místnost",
        "musí být v budově A",
    ]

    with pytest.raises(mutations.RosteringError, match="opakuje"):
        mutations.add_tag(workspace, "9.M", rules=[{"kind": SHARE, "axis": ROOM}, {"kind": SHARE, "axis": ROOM}])
    with pytest.raises(mutations.RosteringError, match="opakuje"):
        mutations.add_tag(workspace, "9.M", rules=[rule(BUILDING, ["A"]), rule(BUILDING, ["A"])])
    assert [t["name"] for t in mutations.get_state(workspace)["tags"]] == ["8.M"]


def test_a_share_rule_restricts_nobody_on_their_own(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", rules=[{"kind": SHARE, "axis": BUILDING}])
    mutations.set_helper_tags(workspace, 1, [tag_id])

    allowed = mutations.helper_allowed(mutations.get_state(workspace), 1)

    assert allowed["buildings"] == ["A", "B"]
    assert len(allowed["rooms"]) == 4


def test_update_tag_replaces_the_whole_rule_list_and_leaves_it_when_not_given(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", rules=[rule(BUILDING, ["A"])])

    kept = mutations.update_tag(workspace, tag_id, note="a class")
    assert [r["values"] for r in kept["tags"][0]["rules"]] == [["A"]]

    replaced = mutations.update_tag(workspace, tag_id, rules=[rule(ROLE, ["Zaloha"], must=False)])
    assert [r["axis"] for r in replaced["tags"][0]["rules"]] == [ROLE]
    assert mutations.update_tag(workspace, tag_id, rules=[])["tags"][0]["rules"] == []


# -- older saved Tags --------------------------------------------------------------


def test_a_tag_saved_with_the_four_lists_loads_as_rules_and_is_rewritten(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    state = workspace.load()
    state["tags"] = [
        {
            "id": 1,
            "name": "Old",
            "colour": "#3366cc",
            "note": "",
            "parent_id": None,
            "building_allow": ["A"],
            "building_deny": ["B"],
            "role_allow": [],
            "role_deny": ["Fotograf"],
        }
    ]
    state["next_tag_id"] = 2
    state["helpers"][0]["tags"] = [1]
    workspace.save(state)

    loaded = workspace.load()

    assert "building_allow" not in loaded["tags"][0]
    assert sorted((r["axis"], r["must"], tuple(r["values"])) for r in loaded["tags"][0]["rules"]) == [
        (BUILDING, False, ("B",)),
        (BUILDING, True, ("A",)),
        (ROLE, False, ("Fotograf",)),
    ]
    assert mutations.helper_allowed(mutations.get_state(workspace), 1)["buildings"] == ["A"]


def test_the_legacy_shape_is_also_read_without_a_migration():
    record = {"id": 1, "name": "T", "building_deny": ["A"], "role_allow": ["Skenovac", "Nothing"]}

    tag = tag_tree.tag_from_dict(record)

    assert [(r.axis, r.must, r.values) for r in tag.rules] == [(BUILDING, False, ("A",)), (ROLE, True, ("Skenovac",))]


# -- the Room axis ------------------------------------------------------------------


def test_a_room_rule_narrows_the_allowed_rooms_inside_the_allowed_buildings(workspace):
    _seed(workspace)
    only = _new_tag(workspace, "Only A1/B1", rules=[rule(ROOM, [["A", "A1"], ["B", "B1"]])])
    no_b = _new_tag(workspace, "No B", rules=[rule(BUILDING, ["B"], must=False)])
    mutations.set_helper_tags(workspace, 1, [only])
    mutations.set_helper_tags(workspace, 2, [only, no_b])
    state = mutations.get_state(workspace)

    assert mutations.helper_allowed(state, 1)["rooms"] == [("A", "A1"), ("B", "B1")]
    assert mutations.helper_allowed(state, 2)["rooms"] == [("A", "A1")]
    assert len(mutations.helper_allowed(state, 3)["rooms"]) == 4  # no Tags: anywhere


def test_a_room_rule_naming_a_room_the_season_lacks_is_inert(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "Ghost", rules=[rule(ROOM, [["A", "Nowhere"]])])
    mutations.set_helper_tags(workspace, 1, [tag_id])

    assert len(mutations.helper_allowed(mutations.get_state(workspace), 1)["rooms"]) == 4


def test_a_tag_that_would_leave_no_allowed_room_is_refused(workspace):
    _seed(workspace)
    only_a = _new_tag(workspace, "Only A", rules=[rule(BUILDING, ["A"])])
    only_b1 = _new_tag(workspace, "Only B1", rules=[rule(ROOM, [["B", "B1"]])])
    mutations.set_helper_tags(workspace, 1, [only_a])

    with pytest.raises(mutations.RosteringError, match="Anna.*žádnou povolenou"):
        mutations.set_helper_tags(workspace, 1, [only_a, only_b1])
    assert mutations.get_state(workspace)["helpers"][0]["tags"] == [only_a]


def test_a_room_rule_edit_that_would_strand_a_carrier_is_refused(workspace):
    _seed(workspace)
    only_a = _new_tag(workspace, "Only A", rules=[rule(BUILDING, ["A"])])
    carrier = _new_tag(workspace, "Carrier")
    mutations.set_helper_tags(workspace, 1, [only_a, carrier])

    with pytest.raises(mutations.RosteringError, match="místnost"):
        mutations.update_tag(workspace, carrier, rules=[rule(ROOM, [["B", "B2"]])])

    assert mutations.get_state(workspace)["tags"][1]["rules"] == []


def test_a_child_tag_inherits_the_rooms_its_parent_allows(workspace):
    _seed(workspace)
    parent = _new_tag(workspace, "GCHD", rules=[rule(ROOM, [["A", "A1"], ["A", "A2"]])])
    child = _new_tag(workspace, "8.M", parent_id=parent, rules=[rule(ROOM, [["A", "A2"]], must=False)])
    mutations.set_helper_tags(workspace, 1, [child])

    assert mutations.helper_allowed(mutations.get_state(workspace), 1)["rooms"] == [("A", "A1")]


# -- the solver and the live checker ------------------------------------------------


def _competition(helpers_tags, rules):
    room = lambda n: Room(name=n, capacities={Role.Zaloha: RoleCapacity(minimum=0)})
    buildings = [Building(name=b, rooms=[room(f"{b}1"), room(f"{b}2")]) for b in ("A", "B")]
    helpers = [Helper(id=i, name=f"H{i}", tags=tags) for i, tags in enumerate(helpers_tags, start=1)]
    return Competition(
        buildings={b.name: b for b in buildings},
        helpers=helpers,
        tags=[tag_tree.Tag(id=1, name="Pinned", colour="#3366cc", rules=tuple(Rule.from_dict(r) for r in rules))],
    )


def test_the_solver_keeps_a_room_ruled_helper_in_the_allowed_room():
    comp = _competition([[1], [], [], []], [rule(ROOM, [["B", "B2"]])])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=10))

    placed = {a.helper_id: a for a in result.assignments}
    assert (placed[1].building, placed[1].room) == ("B", "B2")
    assert result.broken_rules == []


def test_a_forbidden_room_is_a_broken_rule_the_checker_and_solver_word_alike():
    from rostering.domain import Assignment

    comp = _competition([[1]], [rule(ROOM, [["A", "A1"]], must=False)])
    fixed = Assignment(helper_id=1, helper_name="H1", building="A", room="A1", role=Role.Zaloha)

    result = solve_competition(comp, SolverConfig(time_limit_seconds=10), fixed_assignments=[fixed])
    live = check_roster(comp, result.assignments)

    assert [b.instance for b in live] == [RuleInstance("tag_room", (1, "A", "A1"))]
    assert live[0].line == "Pomocník H1 (Štítek Pinned, nesmí být v místnosti A1 (A)) je zařazen(a) do místnosti A1 (A)"
    assert [(b.instance, b.amount, b.line) for b in result.broken_rules] == [(live[0].instance, 1, live[0].line)]
    assert live[0].cells == (("A", "A1", None),)


# -- a Tag's share rules: its carriers act as a Forced friends group ---------------------


def _share_competition(helpers_tags, axis=ROOM, extra_tags=()):
    comp = _competition(helpers_tags, [{"kind": SHARE, "axis": axis}])
    for helper in comp.helpers:
        helper.person_id = f"p{helper.id}"
    comp.tags.extend(extra_tags)
    return comp


def test_the_solver_keeps_the_carriers_of_a_share_rule_in_one_room():
    comp = _share_competition([[1], [1], [1], []])

    result = solve_competition(comp, SolverConfig(time_limit_seconds=10))

    placed = {a.helper_id: (a.building, a.room) for a in result.assignments}
    assert len({placed[1], placed[2], placed[3]}) == 1
    assert result.broken_rules == []
    assert check_roster(comp, result.assignments) == []


def test_a_split_share_rule_is_a_broken_rule_worded_for_the_tag():
    from rostering.domain import Assignment

    comp = _share_competition([[1], [1], []])
    fixed = [
        Assignment(helper_id=1, helper_name="H1", building="A", room="A1", role=Role.Zaloha),
        Assignment(helper_id=2, helper_name="H2", building="B", room="B1", role=Role.Zaloha),
        Assignment(helper_id=3, helper_name="H3", building="A", room="A2", role=Role.Zaloha),
    ]

    result = solve_competition(comp, SolverConfig(time_limit_seconds=10), fixed_assignments=fixed)
    live = check_roster(comp, fixed)

    assert [b.instance for b in live] == [RuleInstance("forced_friends", (-1, "share:room"))]
    assert live[0].line == "Štítek Pinned [H1, H2] je rozdělen mezi místnosti A1 a B1"
    assert live[0].amount == 1
    assert live[0].helper_ids == (1, 2) or live[0].helper_ids == (2, 1)
    assert live[0].fix.tab == "tags" and live[0].fix.tag_id == 1
    assert [(b.instance, b.amount, b.line) for b in result.broken_rules] == [(live[0].instance, 1, live[0].line)]


def test_a_carrier_through_a_child_tag_is_held_to_the_parents_share_rule():
    child = tag_tree.Tag(id=2, name="Child", colour="#dc3912", parent_id=1)
    comp = _share_competition([[1], [2], []], axis=BUILDING, extra_tags=[child])

    groups = comp.rule_groups()

    assert [(g.tag_id, g.person_ids) for g in groups] == [(1, ("p1", "p2"))]


def test_a_share_rule_nobody_carries_makes_no_group():
    assert _share_competition([[], []]).rule_groups() == []


# -- Tag import ----------------------------------------------------------------------


def test_tag_import_keeps_a_share_rule(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)], buildings=("A", "B"))
    mutations.add_tag(workspace, "Together", rules=[{"kind": SHARE, "axis": ROOM}])
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)], buildings=("A", "B"))

    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    assert _tag(mutations.get_state(workspace), "Together")["rules"] == [{"kind": SHARE, "axis": ROOM}]


def test_tag_import_copies_room_rules_and_drops_rooms_the_season_lacks(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)], buildings=("A", "B"))
    mutations.add_tag(
        workspace,
        "Wide",
        rules=[rule(ROOM, [["A", "A1"], ["B", "B1"]]), rule(ROLE, ["Zaloha"], must=False)],
    )
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)], buildings=("A",))  # Building B is gone

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    copied = _tag(mutations.get_state(workspace), "Wide")
    assert [(r["axis"], r["values"]) for r in copied["rules"]] == [(ROOM, [["A", "A1"]]), (ROLE, ["Zaloha"])]
    dropped = _tags_section(summary)["dropped_constraint_entries"]
    assert [(d["tag"], d["entry"]) for d in dropped] == [("Wide", "B1 (B)")]


# -- the rule editor's rows ----------------------------------------------------------


@pytest.mark.parametrize(
    "saved",
    [
        {"kind": SHARE, "axis": ROOM},
        {"kind": BE, "must": True, "axis": BUILDING, "values": ["A", "B"]},
        {"kind": BE, "must": False, "axis": ROOM, "values": [["A", "A1"], ["B", "B2"]]},
        {"kind": BE, "must": False, "axis": ROLE, "values": ["Fotograf"]},
    ],
)
def test_a_rule_survives_the_editor_round_trip(saved):
    assert rule_from_draft(draft_from_rule(saved)) == saved
