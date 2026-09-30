"""Forced friends groups report their state: the status badge (active, dormant with
a reason, violated), the violation line that names where the members ended up (the
same words from the solver and the live checker), the grid chip marks, and the one
blocking edit-time check (an empty intersection of the members' effective allowed
sets on a shared axis, re-checked when Tags change).

Mutation-layer tests run against a temp-dir workspace of synthetic Helpers (never
anything from data/); the solver tests drive it on domain objects.
"""
import pytest

from rostering.domain import Assignment, Building, Competition, Helper, Role, RoleCapacity, Room, RuleInstance
from rostering.forced_friends import ForcedGroup
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.streamlit_app import forced_groups, mutations

# The fixtures and builders of the base Forced friends tests.
from tests.test_forced_friends import TWO_BUILDINGS, _group_named, _placed, _record, _season, workspace  # noqa: F401


# -- the violation line, from the solver and the live checker ----------------------


def _helper(hid, name):
    return Helper(id=hid, name=name, person_id=f"p{hid}")


def _building(name, *room_names):
    rooms = [Room(name=r, capacities={Role.Zaloha: RoleCapacity(minimum=0)}) for r in room_names]
    return Building(name=name, rooms=rooms)


def _pin(hid, name, building, room, role=Role.Zaloha):
    return Assignment(helper_id=hid, helper_name=name, building=building, room=room, role=role)


def _solve_pinned(buildings, helpers, group, pins):
    comp = Competition(buildings={b.name: b for b in buildings}, helpers=helpers, forced_groups=[group])
    result = solve_competition(comp, SolverConfig(time_limit_seconds=10), fixed_assignments=pins)
    return comp, result


def test_a_split_room_group_names_its_members_and_the_rooms_they_are_split_across():
    helpers = [_helper(1, "Anna"), _helper(2, "Petr"), _helper(3, "Jana")]
    group = ForcedGroup(id=1, name="Rodina", axes=("building", "room"), person_ids=("p1", "p2", "p3"))
    pins = [_pin(1, "Anna", "A", "N4"), _pin(2, "Petr", "A", "N4"), _pin(3, "Jana", "A", "N6")]

    comp, result = _solve_pinned([_building("A", "N4", "N6")], helpers, group, pins)

    (broken,) = result.broken_rules
    assert broken.line == "Group Rodina [Anna, Petr, Jana] is split across rooms N4 and N6"
    assert check_roster(comp, result.assignments)[0].line == broken.line


def test_the_line_lists_every_place_the_group_is_split_across():
    helpers = [_helper(1, "Anna"), _helper(2, "Petr"), _helper(3, "Jana")]
    group = ForcedGroup(id=1, name="Rodina", axes=("building",), person_ids=("p1", "p2", "p3"))
    pins = [_pin(1, "Anna", "A", "A1"), _pin(2, "Petr", "B", "B1"), _pin(3, "Jana", "C", "C1")]

    _comp, result = _solve_pinned([_building("A", "A1"), _building("B", "B1"), _building("C", "C1")], helpers, group, pins)

    (broken,) = result.broken_rules
    assert broken.line == "Group Rodina [Anna, Petr, Jana] is split across buildings A, B and C"


def test_a_role_group_line_names_the_roles():
    helpers = [_helper(1, "Anna"), _helper(2, "Petr")]
    group = ForcedGroup(id=1, name="Tým", axes=("role",), person_ids=("p1", "p2"))
    pins = [_pin(1, "Anna", "A", "A1", Role.Skenovac), _pin(2, "Petr", "A", "A1", Role.Menic)]

    _comp, result = _solve_pinned([_building("A", "A1")], helpers, group, pins)

    (broken,) = result.broken_rules
    assert broken.line == "Group Tým [Anna, Petr] is split across roles Skenovač and Měnič"


def test_two_rooms_of_one_name_in_different_buildings_are_told_apart():
    helpers = [_helper(1, "Anna"), _helper(2, "Petr")]
    group = ForcedGroup(id=1, name="Rodina", axes=("building", "room"), person_ids=("p1", "p2"))
    pins = [_pin(1, "Anna", "A", "N4"), _pin(2, "Petr", "B", "N4")]

    _comp, result = _solve_pinned([_building("A", "N4"), _building("B", "N4")], helpers, group, pins)

    (broken,) = result.broken_rules
    assert broken.line == "Group Rodina [Anna, Petr] is split across rooms N4 (A) and N4 (B)"


# -- the status badge --------------------------------------------------------------


def test_a_group_with_two_active_members_is_active_and_a_group_short_of_them_is_dormant(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    state = forced_groups.add_group(workspace, "Sám", ["p3"], ["building"])

    assert _group_named(state, "Rodina")["status"] == "active"
    dormant = _group_named(state, "Sám")
    assert dormant["status"] == "dormant"
    assert "fewer than two" in dormant["reason"].lower()
    assert dormant["violations"] == []


def test_a_group_the_roster_splits_is_violated_with_its_line_and_active_again_once_fixed(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])
    _placed(workspace, ("A", "A1", "Zaloha"), ("A", "A1", "Skenovac"))
    assert _group_named(mutations.get_state(workspace), "Rodina")["status"] == "active"

    state = mutations.move_helper(workspace, 2, "B", "B1", "Skenovac")

    group = _group_named(state, "Rodina")
    assert group["status"] == "violated"
    assert group["violations"] == ["Group Rodina [Anna, Petr] is split across rooms A1 and B1"]
    assert group["active"] is True  # a violated group is still in force

    state = mutations.move_helper(workspace, 2, "A", "A1", "Skenovac")

    assert _group_named(state, "Rodina")["status"] == "active"


def test_a_group_is_never_violated_before_the_first_roster(workspace):
    _season(workspace)

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])

    assert _group_named(state, "Rodina")["status"] == "active"


def test_a_dormant_group_is_not_violated_even_when_its_placed_members_differ(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    _placed(workspace, ("A", "A1", "Zaloha"), ("B", "B1", "Zaloha"))

    state = mutations.set_cant_attend(workspace, 2, True, confirmed=True)

    assert _group_named(state, "Rodina")["status"] == "dormant"


def test_the_live_checker_reports_a_violated_group_with_go_fix_to_its_editor_and_a_drop_toasts(workspace):
    _season(workspace)
    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])
    gid = _group_named(state, "Rodina")["id"]
    _placed(workspace, ("A", "A1", "Zaloha"), ("A", "A1", "Skenovac"))
    before = mutations.get_state(workspace)

    after = mutations.move_helper(workspace, 2, "B", "B2", "Skenovac")

    (broken,) = mutations.broken_rules(after)
    assert broken.line == "Group Rodina [Anna, Petr] is split across rooms A1 and B2"
    assert broken.fix.tab == "forced_friends" and broken.fix.group_id == gid
    assert mutations.move_toast_lines(before, after) == [broken.line]
    assert {a["helper_id"]: a["building"] for a in after["assignments"]} == {1: "A", 2: "B"}  # still applied


# -- the grid's chip marks ---------------------------------------------------------


def test_the_grid_marks_the_members_of_a_group_in_force_with_the_groups_that_bind_them(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building", "room"])
    state = forced_groups.add_group(workspace, "Tým", ["p2", "p3"], ["role"])

    marks = mutations.grid_forced_groups(state)

    assert marks == {
        1: ["Rodina (same Building, Room)"],
        2: ["Rodina (same Building, Room)", "Tým (same Role)"],
        3: ["Tým (same Role)"],
    }


def test_the_grid_does_not_mark_a_dormant_group_nor_a_member_who_cant_attend(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2", "p3"], ["building"])
    forced_groups.add_group(workspace, "Sám", ["p4"], ["building"])

    state = mutations.set_cant_attend(workspace, 3, True)

    assert mutations.grid_forced_groups(state) == {
        1: ["Rodina (same Building)"],
        2: ["Rodina (same Building)"],
    }


# -- the edit-time Tag check -------------------------------------------------------


def _tag(workspace, name, **constraints):
    return mutations.add_tag(workspace, name, **constraints)["tags"][-1]["id"]


def test_creating_a_group_is_refused_when_its_members_allowed_buildings_do_not_intersect(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    mutations.set_helper_tags(workspace, 2, [only_b])

    with pytest.raises(mutations.RosteringError) as refused:
        forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    message = str(refused.value)
    assert "Rodina" in message and "Building" in message and "Anna" in message and "Petr" in message
    assert forced_groups.list_groups(mutations.get_state(workspace)) == []


def test_a_room_group_is_checked_on_its_implied_building_axis(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    mutations.set_helper_tags(workspace, 2, [only_b])

    with pytest.raises(mutations.RosteringError, match="Building"):
        forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])


def test_creating_a_group_is_refused_on_the_role_axis_too(workspace):
    _season(workspace)
    scans = _tag(workspace, "Scans", role_allow=["Skenovac"])
    draws = _tag(workspace, "Draws", role_allow=["Kreslic"])
    mutations.set_helper_tags(workspace, 1, [scans])
    mutations.set_helper_tags(workspace, 2, [draws])

    with pytest.raises(mutations.RosteringError, match="Role"):
        forced_groups.add_group(workspace, "Tým", ["p1", "p2"], ["role"])


def test_only_the_axes_the_group_shares_are_checked(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    mutations.set_helper_tags(workspace, 2, [only_b])

    state = forced_groups.add_group(workspace, "Tým", ["p1", "p2"], ["role"])  # they may share a Role

    assert [g["name"] for g in forced_groups.list_groups(state)] == ["Tým"]


def test_allowed_sets_that_overlap_are_accepted_and_a_deny_list_counts(workspace):
    _season(workspace)
    not_a = _tag(workspace, "NotA", building_deny=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [not_a])
    mutations.set_helper_tags(workspace, 2, [only_b])

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])  # both may be in B

    assert len(forced_groups.list_groups(state)) == 1

    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    mutations.set_helper_tags(workspace, 3, [only_a])
    with pytest.raises(mutations.RosteringError):  # NotA (no A) and OnlyA (only A) share nothing
        forced_groups.add_group(workspace, "Other", ["p1", "p3"], ["building"])


def test_a_member_who_cant_attend_or_is_not_registered_is_left_out_of_the_check(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    mutations.set_helper_tags(workspace, 2, [only_b])
    mutations.set_helper_tags(workspace, 3, [only_a])
    mutations.set_cant_attend(workspace, 2, True)

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2", "p3"], ["building"])

    assert _group_named(state, "Rodina")["status"] == "active"  # only Anna and Jana take part


def test_editing_a_groups_people_or_axes_is_refused_on_an_empty_intersection_but_a_rename_is_not(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    mutations.set_helper_tags(workspace, 2, [only_b])
    gid = _group_named(forced_groups.add_group(workspace, "Tým", ["p1", "p2"], ["role"]), "Tým")["id"]

    with pytest.raises(mutations.RosteringError, match="Building"):
        forced_groups.update_group(workspace, gid, axes=["building"])
    state = mutations.get_state(workspace)
    assert _group_named(state, "Tým")["axes"] == ["role"]  # nothing changed

    state = forced_groups.update_group(workspace, gid, name="Tým B")
    assert _group_named(state, "Tým B")["axes"] == ["role"]

    forced_groups.update_group(workspace, gid, person_ids=["p1", "p3"], axes=["building"])  # Jana is unrestricted
    with pytest.raises(mutations.RosteringError, match="Petr"):
        forced_groups.update_group(workspace, gid, person_ids=["p1", "p2"])


def test_a_group_already_at_odds_can_still_be_renamed(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    gid = _group_named(forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"]), "Rodina")["id"]
    state = workspace.load()
    state["helpers"][0]["tags"] = [only_a]  # e.g. after a Tag import that skipped the check
    state["helpers"][1]["tags"] = [only_b]
    workspace.save(state)

    state = forced_groups.update_group(workspace, gid, name="Rodinka")

    assert _group_named(state, "Rodinka")["axes"] == ["building"]


def test_a_tag_change_that_would_empty_a_groups_intersection_is_refused(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    with pytest.raises(mutations.RosteringError, match="Rodina"):
        mutations.set_helper_tags(workspace, 2, [only_b])
    with pytest.raises(mutations.RosteringError, match="Rodina"):
        mutations.add_tag_to_helpers(workspace, only_b, [2])
    assert mutations.get_state(workspace)["helpers"][1].get("tags", []) == []  # nothing was saved

    # Editing a Tag's constraints is re-checked as well.
    loose = _tag(workspace, "Loose", building_allow=["A", "B"])
    mutations.set_helper_tags(workspace, 2, [loose])
    with pytest.raises(mutations.RosteringError, match="Rodina"):
        mutations.update_tag(workspace, loose, building_allow=["B"])


def test_a_tag_change_outside_the_groups_axes_or_members_is_not_blocked(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    only_b = _tag(workspace, "OnlyB", building_allow=["B"])
    mutations.set_helper_tags(workspace, 1, [only_a])
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    mutations.set_helper_tags(workspace, 3, [only_b])  # Jana is in no group

    assert mutations.get_state(workspace)["helpers"][2]["tags"] == [only_b]


def test_a_groups_own_conflict_is_not_reported_twice_when_it_is_a_members_dead_end(workspace):
    _season(workspace)
    only_a = _tag(workspace, "OnlyA", building_allow=["A"])
    not_a = _tag(workspace, "NotA", building_deny=["A"])
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])

    with pytest.raises(mutations.RosteringError) as refused:
        mutations.set_helper_tags(workspace, 1, [only_a, not_a])  # Anna herself has nowhere to go

    assert "Rodina" not in str(refused.value)
    assert "Anna" in str(refused.value)


def test_capacity_and_fixed_assignment_clashes_do_not_block_a_group(workspace):
    _season(workspace)
    state = workspace.load()
    state["config"] = [
        {**TWO_BUILDINGS[0], "capacities": {"Skenovac": {"minimum": 9}}},  # more than there are Helpers
        TWO_BUILDINGS[1],
    ]
    workspace.save(state)
    _placed(workspace, ("A", "A1", "Zaloha"), ("B", "B1", "Zaloha"))
    mutations.set_lock(workspace, 1, True)
    mutations.set_lock(workspace, 2, True)  # a locked pair already apart

    state = forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["room"])

    group = _group_named(state, "Rodina")
    assert group["status"] == "violated"
    assert mutations.solve(workspace)  # a solve still returns a roster, with the group as a Broken rule
    assert any(b.instance == RuleInstance("forced_friends", (group["id"], "room")) for b in mutations.broken_rules(mutations.get_state(workspace)))
