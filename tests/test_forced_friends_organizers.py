"""Organizers as Forced friends group members, and "make forced" (see
``CONTEXT.md``: Forced friends group, Organizer).

An Organizer is a member through their Person; a *placed* one anchors the
group's Building and/or Room axes at their placement (a Building-level one
enforces only Building even on a Room group), an unplaced one is dormant, and no
Organizer is ever on the Role axis (they have no solved Role). Solver tests run
on plain domain objects, mutation tests against a temp-dir workspace of
synthetic Helpers (never anything from data/).
"""
import importlib
import random

import pytest

from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    Organizer,
    Role,
    RoleCapacity,
    Room,
    RuleInstance,
)
from rostering.forced_friends import ForcedGroup
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.streamlit_app import forced_groups, mutations

# -- the solver, on domain objects ------------------------------------------------


def _solver_config():
    return SolverConfig(time_limit_seconds=10)


def _room(name):
    return Room(name=name, capacities={Role.Zaloha: RoleCapacity(minimum=0)})


def _building(name, *rooms):
    return Building(name=name, rooms=list(rooms) or [_room(f"{name}-R1")])


def _helper(hid, **extra):
    return Helper(id=hid, name=f"H{hid}", person_id=f"p{hid}", **extra)


def _organizer(oid, building=None, room=None, **extra):
    return Organizer(id=oid, name=f"Org{oid}", person_id=f"o{oid}", building=building, room=room, **extra)


def _group(gid, axes, *members, name=None):
    return ForcedGroup(id=gid, name=name or f"G{gid}", axes=tuple(axes), person_ids=tuple(members))


def _competition(buildings, helpers, organizers, groups):
    return Competition(
        buildings={b.name: b for b in buildings},
        helpers=helpers,
        organizers=organizers,
        forced_groups=list(groups),
    )


def _by_helper(result):
    return {a.helper_id: a for a in result.assignments}


def _pin(hid, building, room, role=Role.Zaloha):
    return Assignment(helper_id=hid, helper_name=f"H{hid}", building=building, room=room, role=role)


def test_a_placed_organizer_anchors_a_building_group_at_their_building():
    # The Helper would rather be in A; the Organizer stands in B, so the group holds them there.
    helpers = [_helper(1, building_preferences=frozenset({"A"}))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_organizer(1, "B")], [_group(1, ["building"], "p1", "o1")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "B"


def test_a_room_level_organizer_anchors_a_room_group_at_their_room():
    helpers = [_helper(1, building_preferences=frozenset({"A"})), _helper(2, building_preferences=frozenset({"A"}))]
    buildings = [_building("A", _room("A1"), _room("A2")), _building("B", _room("B1"), _room("B2"))]
    comp = _competition(
        buildings, helpers, [_organizer(1, "B", "B2")], [_group(1, ["building", "room"], "p1", "p2", "o1")]
    )

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert {(placed[h].building, placed[h].room) for h in (1, 2)} == {("B", "B2")}


def test_a_room_axis_on_a_building_level_organizer_enforces_only_the_building():
    # Marie leads Building B as a whole: the Helpers must be in B and share a Room, but any Room of B.
    helpers = [_helper(1, building_preferences=frozenset({"A"})), _helper(2, building_preferences=frozenset({"A"}))]
    buildings = [_building("A", _room("A1"), _room("A2")), _building("B", _room("B1"), _room("B2"))]
    comp = _competition(
        buildings, helpers, [_organizer(1, "B")], [_group(1, ["building", "room"], "p1", "p2", "o1")]
    )

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].building == placed[2].building == "B"
    assert placed[1].room == placed[2].room


def test_a_building_level_organizer_alone_with_one_helper_still_anchors_the_building_of_a_room_group():
    helpers = [_helper(1, building_preferences=frozenset({"A"}))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_organizer(1, "B")], [_group(1, ["building", "room"], "p1", "o1")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "B"


def test_an_unplaced_organizer_is_dormant_and_the_group_constrains_only_the_active_members():
    helpers = [_helper(1, building_preferences=frozenset({"A"}))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_organizer(1)], [_group(1, ["building"], "p1", "o1")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "A"


def test_an_organizer_who_cant_attend_is_dormant():
    helpers = [_helper(1, building_preferences=frozenset({"A"}))]
    comp = _competition(
        [_building("A"), _building("B")],
        helpers,
        [_organizer(1, "B", cant_attend=True)],
        [_group(1, ["building"], "p1", "o1")],
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "A"


def test_the_role_axis_is_not_applied_to_an_organizer():
    # The two Helpers share a Role and a Room with Marie; Marie has no Role to share.
    helpers = [
        _helper(1, building_preferences=frozenset({"A"})),
        _helper(2, building_preferences=frozenset({"A"})),
    ]
    buildings = [_building("A", _room("A1"), _room("A2")), _building("B", _room("B1"))]
    group = _group(1, ["building", "room", "role"], "p1", "p2", "o1")
    comp = _competition(buildings, helpers, [_organizer(1, "B", "B1")], [group])

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].room == placed[2].room == "B1"
    assert placed[1].role == placed[2].role


def test_a_role_only_group_of_one_helper_and_an_organizer_constrains_nothing():
    helpers = [_helper(1, building_preferences=frozenset({"A"}))]
    comp = _competition(
        [_building("A"), _building("B")], helpers, [_organizer(1, "B")], [_group(1, ["role"], "p1", "o1")]
    )

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert _by_helper(result)[1].building == "A"


def test_a_group_the_organizers_anchor_cannot_hold_bends_and_names_the_organizer():
    helpers = [_helper(1)]
    comp = _competition(
        [_building("A", _room("A1")), _building("B", _room("B1"))],
        helpers,
        [_organizer(1, "B", "B1")],
        [_group(1, ["building", "room"], "p1", "o1", name="Team")],
    )

    result = solve_competition(comp, _solver_config(), fixed_assignments=[_pin(1, "A", "A1")])

    (broken,) = result.broken_rules
    assert broken.instance == RuleInstance("forced_friends", (1, "room"))
    assert broken.amount == 1
    assert broken.line == "Skupinka Team [H1, Org1] je rozdělena mezi místnosti A1 a B1"


def test_two_organizers_who_stand_apart_are_a_broken_group_the_solver_cannot_fix():
    helpers = [_helper(1)]
    comp = _competition(
        [_building("A"), _building("B")],
        helpers,
        [_organizer(1, "A"), _organizer(2, "B")],
        [_group(1, ["building"], "p1", "o1", "o2")],
    )

    result = solve_competition(comp, _solver_config())

    (broken,) = result.broken_rules
    assert broken.instance == RuleInstance("forced_friends", (1, "building"))
    assert broken.amount == 1


def _random_competition(rng):
    buildings = [Building(name=f"B{b}", rooms=[_room(f"B{b}R{r}") for r in range(2)]) for b in range(3)]
    n = rng.randint(2, 6)
    helpers = [_helper(i, building_preferences=frozenset({f"B{rng.randrange(3)}"})) for i in range(1, n + 1)]
    organizers = []
    for oid in range(1, rng.randint(1, 3) + 1):
        building = rng.choice([None, "B0", "B1", "B2"])
        room = f"{building}R{rng.randrange(2)}" if building and rng.random() < 0.5 else None
        organizers.append(_organizer(oid, building, room, cant_attend=rng.random() < 0.15))
    members = [f"p{i}" for i in range(1, n + 1)] + [f"o{o.id}" for o in organizers]
    groups = []
    for gid in range(1, rng.randint(1, 3) + 1):
        axes = rng.choice([["building"], ["building", "room"], ["role"], ["building", "room", "role"]])
        groups.append(_group(gid, axes, *rng.sample(members, rng.randint(2, min(4, len(members))))))
    return _competition(buildings, helpers, organizers, groups)


def _projection(broken_rules):
    return {b.instance: (b.family, b.amount, b.line) for b in broken_rules}


@pytest.mark.parametrize("seed", range(12))
def test_the_checker_agrees_with_the_solvers_own_bent_groups_with_organizers(seed):
    comp = _random_competition(random.Random(seed))
    fixed = [_pin(h.id, "B0", "B0R0") for h in comp.helpers if h.id % 3 == 0]
    fixed += [_pin(h.id, "B1", "B1R1") for h in comp.helpers if h.id % 3 == 1 and h.id % 2 == 0]

    result = solve_competition(comp, _solver_config(), fixed_assignments=fixed)

    ours = {i: v for i, v in _projection(result.broken_rules).items() if i.kind == "forced_friends"}
    theirs = {i: v for i, v in _projection(check_roster(comp, result.assignments)).items() if i.kind == "forced_friends"}
    assert ours == theirs


# -- through the mutation layer: a temp-dir workspace of synthetic data -----------


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


def _season(workspace, names=("Anna", "Petr", "Jana")):
    state = workspace.empty_state()
    state["helpers"] = [_record(i, name) for i, name in enumerate(names, start=1)]
    state["config"] = TWO_BUILDINGS
    workspace.create_season("2026-jaro", state)
    return workspace.load()


def _organizer_named(workspace, name, slot=None, building=None, room=None) -> str:
    """Add an Organizer (optionally holding a slot); returns their person_id."""
    state = mutations.add_organizer(workspace, name)
    record = state["organizers"][-1]
    if slot:
        state = mutations.assign_organizer(workspace, record["id"], slot, building, room)
    return record["person_id"]


def _group_named(state, name):
    return next(g for g in forced_groups.list_groups(state) if g["name"] == name)


def test_an_organizer_can_be_added_to_a_group_and_is_active_when_placed(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciMistnosti", "B", "B2")

    state = forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building", "room"])

    group = _group_named(state, "Tym")
    assert group["status"] == forced_groups.ACTIVE
    org = next(m for m in group["members"] if m["person_id"] == marie)
    assert (org["name"], org["kind"], org["state"]) == ("Marie", "organizer", forced_groups.ACTIVE)


def test_an_unplaced_organizer_member_is_dormant_and_the_group_says_why(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie")

    state = forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building"])

    group = _group_named(state, "Tym")
    assert group["status"] == forced_groups.DORMANT
    assert "Marie je nezařazený organizátor" in group["reason"]
    org = next(m for m in group["members"] if m["person_id"] == marie)
    assert org["state"] == forced_groups.UNPLACED


def test_a_group_wakes_when_its_organizer_is_placed(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie")
    forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building"])
    organizer_id = mutations.get_state(workspace)["organizers"][-1]["id"]

    state = mutations.assign_organizer(workspace, organizer_id, "VedouciBudovy", "B")

    assert _group_named(state, "Tym")["status"] == forced_groups.ACTIVE


def test_an_organizer_who_cant_attend_stays_a_member_but_inactive(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciBudovy", "B")
    forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building"])
    organizer_id = mutations.get_state(workspace)["organizers"][-1]["id"]

    state = mutations.set_organizer_cant_attend(workspace, organizer_id, True, confirmed=True)

    group = _group_named(state, "Tym")
    assert group["status"] == forced_groups.DORMANT
    assert next(m for m in group["members"] if m["person_id"] == marie)["state"] == forced_groups.CANT_ATTEND


def test_an_organizer_is_refused_on_a_group_that_uses_the_role_axis(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciBudovy", "B")

    with pytest.raises(mutations.RosteringError, match="Marie"):
        forced_groups.add_group(workspace, "Tym", ["p1", marie], ["room", "role"])

    assert mutations.get_state(workspace)["forced_groups"] == []


def test_an_organizer_cannot_be_added_to_a_role_group_nor_the_role_axis_ticked_over_one(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciBudovy", "B")
    forced_groups.add_group(workspace, "Rola", ["p1", "p2"], ["role"])
    forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building"])
    state = mutations.get_state(workspace)
    rola, tym = (g["id"] for g in state["forced_groups"])

    with pytest.raises(mutations.RosteringError, match="Marie"):
        forced_groups.update_group(workspace, rola, person_ids=["p1", "p2", marie])
    with pytest.raises(mutations.RosteringError, match="Marie"):
        forced_groups.update_group(workspace, tym, axes=["building", "role"])

    state = mutations.get_state(workspace)
    assert [m["person_id"] for m in state["forced_groups"][0]["members"]] == ["p1", "p2"]
    assert state["forced_groups"][1]["axes"] == ["building"]


def test_a_member_promoted_to_organizer_keeps_membership_with_the_role_axis_not_applied(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2", "p3"], ["room", "role"])

    state = mutations.promote_helper(workspace, 1)

    group = _group_named(state, "Rodina")
    assert [m["person_id"] for m in group["members"]] == ["p1", "p2", "p3"]
    anna = group["members"][0]
    assert (anna["name"], anna["kind"], anna["state"]) == ("Anna", "organizer", forced_groups.UNPLACED)
    assert group["badges"] == ["Role se na Anna neuplatní"]
    # The remaining two Helpers still make the group active.
    assert group["status"] == forced_groups.ACTIVE


def test_the_badge_shows_only_on_groups_that_use_the_role_axis_and_only_for_organizers(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Bez role", ["p1", "p2"], ["room"])
    forced_groups.add_group(workspace, "S rolí", ["p1", "p2", "p3"], ["role"])

    state = mutations.promote_helper(workspace, 1)

    assert _group_named(state, "Bez role")["badges"] == []
    assert _group_named(state, "S rolí")["badges"] == ["Role se na Anna neuplatní"]


def test_editing_a_group_that_carries_the_badge_is_not_refused(workspace):
    _season(workspace)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2", "p3"], ["room", "role"])
    state = mutations.promote_helper(workspace, 1)
    group_id = state["forced_groups"][0]["id"]

    forced_groups.update_group(workspace, group_id, name="Nova")
    state = forced_groups.update_group(workspace, group_id, person_ids=["p1", "p2"])

    assert _group_named(state, "Nova")["badges"] == ["Role se na Anna neuplatní"]


def test_a_promoted_members_placement_anchors_the_group_in_a_solve(workspace):
    state = _season(workspace)
    state["helpers"][1]["building_preferences"] = ["A"]
    workspace.save(state)
    forced_groups.add_group(workspace, "Rodina", ["p1", "p2"], ["building"])
    mutations.promote_helper(workspace, 1)
    organizer_id = mutations.get_state(workspace)["organizers"][0]["id"]
    mutations.assign_organizer(workspace, organizer_id, "VedouciBudovy", "B")

    state = mutations.solve(workspace)

    placed = {a["helper_id"]: a for a in state["assignments"]}
    assert placed[2]["building"] == "B"
    assert mutations.broken_rules(state) == []


def test_dragging_a_helper_away_from_a_group_with_a_placed_organizer_is_an_ordinary_broken_group(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciMistnosti", "B", "B2")
    forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building", "room"])
    before = mutations.move_helper(workspace, 1, "B", "B2", "Zaloha")
    assert mutations.broken_rules(before) == []

    after = mutations.move_helper(workspace, 1, "A", "A1", "Zaloha")

    (broken,) = [b for b in mutations.broken_rules(after) if b.family == "forced_friends"]
    assert broken.line == "Skupinka Tym [Anna, Marie] je rozdělena mezi místnosti A1 a B2"
    assert broken.fix.group_id == 1
    assert mutations.move_toast_lines(before, after) == [broken.line]
    assert (
        next(a for a in after["assignments"] if a["helper_id"] == 1)["room"] == "A1"
    )  # the drag still applies


def test_the_grid_marks_a_helper_bound_to_a_placed_organizer(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciBudovy", "B")
    state = forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building"])

    assert mutations.grid_forced_groups(state) == {1: ["Tym (shodné: budova)"]}


def test_the_people_multiselect_offers_organizers_too(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie")

    state = mutations.get_state(workspace)

    options = {o["person_id"]: o for o in forced_groups.member_options(state)}
    assert options[marie]["name"] == "Marie" and options[marie]["kind"] == "organizer"
    assert options["p1"]["kind"] == "helper"


def test_dissolving_a_group_pulling_a_placed_organizer_and_helper_raises_the_banner(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciBudovy", "B")
    state = forced_groups.add_group(workspace, "Tym", ["p1", marie], ["building"])
    mutations.move_helper(workspace, 1, "B", "B1", "Zaloha")

    state = forced_groups.dissolve_group(workspace, state["forced_groups"][0]["id"])

    assert mutations.stale_reasons(state)


# -- "make forced" -----------------------------------------------------------------


def test_make_forced_creates_a_room_group_of_the_two_people_and_leaves_the_request_untouched(workspace):
    _season(workspace)
    mutations.update_helper(workspace, 1, friends=[2])
    before = mutations.get_state(workspace)["helpers"][0]["friends"]

    state = forced_groups.make_forced(workspace, 1, 2)

    (group,) = state["forced_groups"]
    assert group["name"] == "Anna + Petr"
    assert group["axes"] == ["building", "room"]
    assert [m["person_id"] for m in group["members"]] == ["p1", "p2"]
    assert state["helpers"][0]["friends"] == before == [2]


def test_make_forced_works_for_a_request_toward_an_organizer(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie", "VedouciMistnosti", "B", "B2")
    organizer_id = mutations.get_state(workspace)["organizers"][-1]["id"]
    mutations.update_helper(workspace, 1, friends=[{"organizer_id": organizer_id}])

    state = forced_groups.make_forced(workspace, 1, {"organizer_id": organizer_id})

    (group,) = state["forced_groups"]
    assert group["name"] == "Anna + Marie"
    assert [m["person_id"] for m in group["members"]] == ["p1", marie]


def test_make_forced_needs_a_resolved_request_and_refuses_a_duplicate(workspace):
    _season(workspace)
    mutations.update_helper(workspace, 1, friends=[2])

    with pytest.raises(mutations.RosteringError, match="přání"):
        forced_groups.make_forced(workspace, 1, 3)
    forced_groups.make_forced(workspace, 1, 2)
    with pytest.raises(mutations.RosteringError, match="už existuje"):
        forced_groups.make_forced(workspace, 1, 2)

    assert len(mutations.get_state(workspace)["forced_groups"]) == 1


def test_make_forced_marks_an_existing_roster_stale_like_any_new_group(workspace):
    _season(workspace)
    mutations.update_helper(workspace, 1, friends=[2])
    mutations.solve(workspace)

    state = forced_groups.make_forced(workspace, 1, 2)

    assert mutations.stale_reasons(state)


def test_friend_requests_lists_each_resolved_request_and_whether_it_is_already_forced(workspace):
    _season(workspace)
    marie = _organizer_named(workspace, "Marie")
    organizer_id = mutations.get_state(workspace)["organizers"][-1]["id"]
    mutations.update_helper(workspace, 1, friends=[2, {"organizer_id": organizer_id}])
    state = forced_groups.make_forced(workspace, 1, 2)

    requests = forced_groups.friend_requests(state)

    assert [(r["helper_name"], r["friend_name"], r["forced"]) for r in requests] == [
        ("Anna", "Petr", True),
        ("Anna", "Marie (organizátor)", False),
    ]
    assert marie


# -- the tab, rendered headlessly ------------------------------------------------------


def _forced_tab_app():
    from rostering.streamlit_app.tabs import forced_friends_tab

    forced_friends_tab.render()


@pytest.fixture
def seasons(tmp_path, monkeypatch):
    """A Season of Anna, Petr and Jana (helpers p1..p3) and two Buildings."""
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    workspace = Workspace()
    state = workspace.empty_state()
    state["helpers"] = [_record(i, name) for i, name in enumerate(("Anna", "Petr", "Jana"), start=1)]
    state["config"] = TWO_BUILDINGS
    workspace.create_season("2026-jaro", state)
    return workspace


def test_the_tab_shows_the_role_not_applied_badge_and_an_organizer_as_a_member(seasons):
    from streamlit.testing.v1 import AppTest

    forced_groups.add_group(seasons, "Rodina", ["p1", "p2", "p3"], ["room", "role"])
    mutations.promote_helper(seasons, 1)

    at = AppTest.from_function(_forced_tab_app, default_timeout=30).run()

    assert not at.exception
    assert any("Role se na Anna neuplatní" in m.value for m in at.markdown)
    assert any("Anna (nezařazený organizátor, neaktivní)" in m.value for m in at.markdown)


def _friends_popup_app():
    import streamlit as st

    from rostering.streamlit_app.tabs import person_dialog

    st.fragment(person_dialog._helper_body)(1)


def _multiselect(at, label):
    return next(m for m in at.multiselect if m.label == label)


def test_the_helper_popup_forces_a_friend_by_picking_them_in_the_multiselect(seasons):
    from streamlit.testing.v1 import AppTest

    mutations.update_helper(seasons, 1, friends=[2])

    at = AppTest.from_function(_friends_popup_app, default_timeout=30).run()
    assert not at.exception
    _multiselect(at, "Vynucení kamarádi v místnosti").select("h2").run()

    assert not at.exception
    (group,) = mutations.get_state(seasons)["forced_groups"]
    assert (group["name"], group["axes"]) == ("Anna + Petr", ["building", "room"])
    assert _multiselect(at, "Vynucení kamarádi v místnosti").value == ["h2"]


def test_the_helper_popup_unforces_a_friend_by_unpicking_them(seasons):
    from streamlit.testing.v1 import AppTest

    mutations.update_helper(seasons, 1, friends=[2])
    forced_groups.make_forced(seasons, 1, 2)

    at = AppTest.from_function(_friends_popup_app, default_timeout=30).run()
    assert _multiselect(at, "Vynucení kamarádi v místnosti").value == ["h2"]
    _multiselect(at, "Vynucení kamarádi v místnosti").unselect("h2").run()

    assert not at.exception
    assert mutations.get_state(seasons)["forced_groups"] == []
    assert mutations.get_state(seasons)["helpers"][0]["friends"] == [2]  # the wish stays


def test_the_forced_picker_offers_only_the_helpers_own_friends(seasons):
    from streamlit.testing.v1 import AppTest

    mutations.update_helper(seasons, 1, friends=[2])

    at = AppTest.from_function(_friends_popup_app, default_timeout=30).run()

    assert not at.exception
    assert _multiselect(at, "Vynucení kamarádi v místnosti").options == ["Petr"]


def test_the_friends_tab_holds_the_friends_picker_and_saves_a_pick_at_once(seasons):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_friends_popup_app, default_timeout=30).run()
    friends_label = "Kamarádi (pomocníci nebo organizátoři, se kterými chce sdílet místnost)"
    _multiselect(at, friends_label).select("h3").run()

    assert not at.exception
    assert mutations.get_state(seasons)["helpers"][0]["friends"] == [3]
    assert _multiselect(at, "Vynucení kamarádi v místnosti").options == ["Jana"]


def test_the_forced_friends_tab_no_longer_has_the_make_forced_expander(seasons):
    from streamlit.testing.v1 import AppTest

    mutations.update_helper(seasons, 1, friends=[2])

    at = AppTest.from_function(_forced_tab_app, default_timeout=30).run()

    assert not at.exception
    assert not any(b.label == "Vynutit" for b in at.button)


def test_the_friends_tab_lists_unmatched_names_above_the_matched_friends(seasons):
    from streamlit.testing.v1 import AppTest

    state = mutations.get_state(seasons)
    helper = next(h for h in state["helpers"] if h["id"] == 1)
    helper.update(friends=[2], unresolved_friend_names=["Terka"], friend_name_order=["Terka"])
    seasons.save(state)

    at = AppTest.from_function(_friends_popup_app, default_timeout=30).run()

    assert not at.exception
    headings = [m.value for m in at.markdown if m.value.startswith("**")]
    assert headings == ["**K přiřazení**", "**Přiřazení kamarádi**"]
    assert any(m.label == "Vynucení kamarádi v místnosti" for m in at.multiselect)
