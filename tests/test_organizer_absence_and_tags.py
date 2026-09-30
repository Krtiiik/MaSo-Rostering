"""Organizers behave like Helpers for Can't attend and Tags (see CONTEXT.md
"Organizer", "Can't attend", "Tag constraint"): the same flag with the same
confirmation and cascade (placement and slot entries cleared, roster stale),
silent friend scoring, direct/implied Tags and the Building constraints, checked
live against their placement and never blocking a hand placement. Mutation-layer
tests run against a temp-dir workspace seeded with synthetic Helpers and
Organizers (never anything from data/); the solver, the checker and the export are
driven on plain domain objects."""
import importlib

import pytest

from rostering.domain import (
    Building,
    Competition,
    Helper,
    ManualRoles,
    Organizer,
    OrganizerRef,
    Role,
    RoleCapacity,
    Room,
    RuleInstance,
    SolveResult,
    StructuralAssignment,
    StructuralRole,
)
from rostering.export.people import counted_people
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.streamlit_app import mutations
from rostering.tags import Tag

CONFIG = [
    {
        "name": "Karlín",
        "rooms": [
            {"name": "K1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "K2", "capacities": {"Zaloha": {"minimum": 0}}},
        ],
        "capacities": {},
    },
    {"name": "Impakt", "rooms": [{"name": "I1", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}},
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "seasons")


def _helper(helper_id: int, name: str, **extra) -> dict:
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
        **extra,
    }


def _seed(workspace: Workspace) -> None:
    state = workspace.load()
    state["helpers"] = [_helper(1, "Anna"), _helper(2, "Petr")]
    workspace.save(state)
    mutations.put_config(workspace, CONFIG)


def _create(workspace, name) -> int:
    return mutations.add_organizer(workspace, name)["organizers"][-1]["id"]


def _org(state, organizer_id) -> dict:
    return next(o for o in state["organizers"] if o["id"] == organizer_id)


def _new_tag(workspace, name, parent_id=None, **kwargs) -> int:
    state = mutations.add_tag(workspace, name, parent_id=parent_id, **kwargs)
    return next(t["id"] for t in state["tags"] if t["name"] == name)


def _solved_state(workspace):
    """A Season with a solved roster (Anna and Petr placed), so the stale flag and
    the Broken-rule check have a roster to speak about."""
    _seed(workspace)
    return mutations.solve(workspace)


# -- Can't attend --------------------------------------------------------------------


def test_flagging_an_organizer_without_a_slot_needs_no_confirmation(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")

    state = mutations.set_organizer_cant_attend(workspace, boss, True)

    assert _org(state, boss)["cant_attend"] is True
    assert mutations.stale_reasons(state) == []


def test_flagging_a_slot_holder_asks_first_and_changes_nothing_until_confirmed(workspace):
    _solved_state(workspace)
    boss = _create(workspace, "Boss")
    mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")
    before = mutations.get_state(workspace)

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.set_organizer_cant_attend(workspace, boss, True)

    assert any("Vedoucí budovy" in line for line in excinfo.value.lines)
    assert mutations.get_state(workspace) == before
    assert not _org(before, boss).get("cant_attend")


def test_confirming_clears_the_placement_and_slot_entries_and_stales_the_roster(workspace):
    _solved_state(workspace)
    boss = _create(workspace, "Boss")
    deputy = _create(workspace, "Deputy")
    mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")
    mutations.assign_organizer(workspace, boss, "TechnickaPodpora", "Karlín")
    mutations.assign_organizer(workspace, deputy, "VedouciBudovy", "Impakt")

    state = mutations.set_organizer_cant_attend(workspace, boss, True, confirmed=True)

    assert [e["organizer_id"] for e in state["manual_roles"]["structural"]] == [deputy]
    assert (_org(state, boss)["building"], _org(state, boss)["room"]) == (None, None)
    assert _org(state, deputy)["building"] == "Impakt"
    assert any("Boss" in reason for reason in mutations.stale_reasons(state))
    # Nobody's solved Assignment is touched.
    assert len(state["assignments"]) == 2


def test_unflagging_only_clears_the_flag(workspace):
    _solved_state(workspace)
    boss = _create(workspace, "Boss")
    mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")
    mutations.set_organizer_cant_attend(workspace, boss, True, confirmed=True)
    mutations.solve(workspace)  # clears the stale flag

    state = mutations.set_organizer_cant_attend(workspace, boss, False)

    assert not _org(state, boss).get("cant_attend")
    assert state["manual_roles"]["structural"] == []
    assert mutations.stale_reasons(state) == []


def test_an_organizer_who_cant_attend_cannot_be_put_in_a_slot(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    mutations.set_organizer_cant_attend(workspace, boss, True)

    with pytest.raises(mutations.RosteringError, match="Can't attend"):
        mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")
    # Nor by typing their name into a slot cell.
    with pytest.raises(mutations.RosteringError, match="Can't attend"):
        mutations.set_slot_holders(workspace, "VedouciBudovy", "Karlín", None, ["Boss"])

    assert mutations.get_state(workspace)["manual_roles"]["structural"] == []


def test_the_flag_is_saved_with_the_organizer_and_versions_roll_it_back(workspace):
    _seed(workspace)
    workspace.create_season("2026-jaro")  # Versions belong to an open Season
    boss = _create(workspace, "Boss")
    saved =mutations.save_version(workspace, "before")
    mutations.set_organizer_cant_attend(workspace, boss, True)

    state = mutations.restore_version(workspace, saved["slug"])

    assert not _org(state, boss).get("cant_attend")


def test_promoting_a_helper_who_cant_attend_gives_an_organizer_who_attends(workspace):
    """Conservative reading: promotion is a deliberate act, so the flag is not
    inherited (the Organizer can be flagged afterwards)."""
    _seed(workspace)
    mutations.set_cant_attend(workspace, 1, True)

    state = mutations.promote_helper(workspace, 1)

    assert not state["organizers"][-1].get("cant_attend")


def _two_room_competition(organizers, helpers):
    building = Building(
        name="B",
        rooms=[
            Room("R1", {Role.Zaloha: RoleCapacity(0)}),
            Room("R2", {Role.Zaloha: RoleCapacity(0)}),
        ],
    )
    return Competition(buildings={"B": building}, helpers=helpers, organizers=organizers)


def test_a_friend_request_naming_a_cant_attend_organizer_stops_scoring_silently():
    """Toward an attending but unplaced Organizer the request can never be met
    and costs; toward a Can't attend one it is not scored at all."""
    request = [OrganizerRef(7)]
    unplaced = Organizer(id=7, name="Boss")
    absent = Organizer(id=7, name="Boss", cant_attend=True)
    asker = lambda: [Helper(id=1, name="Anna", friends=list(request))]  # noqa: E731

    costly = solve_competition(_two_room_competition([unplaced], asker()), SolverConfig())
    free = solve_competition(_two_room_competition([absent], asker()), SolverConfig())
    baseline = solve_competition(_two_room_competition([], [Helper(id=1, name="Anna")]), SolverConfig())

    assert costly.objective_value > baseline.objective_value
    assert free.objective_value == baseline.objective_value
    assert free.broken_rules == []


def test_an_absent_organizer_does_not_attract_a_helper_to_their_room():
    absent = Organizer(id=7, name="Boss", building="B", room="R2", cant_attend=True)
    comp = _two_room_competition([absent], [Helper(id=1, name="Anna", friends=[OrganizerRef(7)])])
    baseline = _two_room_competition([], [Helper(id=1, name="Anna")])

    assert solve_competition(comp, SolverConfig()).objective_value == solve_competition(baseline, SolverConfig()).objective_value


def test_an_absent_organizer_is_left_out_of_the_counts_and_the_check():
    comp = _two_room_competition(
        [Organizer(id=7, name="Boss", building="B", room=None, cant_attend=True, tags=[1])],
        [Helper(id=1, name="Anna")],
    )
    comp.tags = [Tag(id=1, name="T", colour="#000000", note="", parent_id=None, building_deny=("B",))]
    manual = ManualRoles(structural=[StructuralAssignment(StructuralRole.VedouciBudovy, "B", organizer_id=7)])

    assert check_roster(comp, []) == []
    counted = counted_people(comp, SolveResult([], "OPTIMAL", 0.0), manual)
    assert [p.name for p in counted] == []


# -- Tags on Organizers --------------------------------------------------------------


def test_an_organizer_carries_direct_tags_and_the_ones_they_imply(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    gchd = _new_tag(workspace, "GCHD")
    eightm = _new_tag(workspace, "8.M", parent_id=gchd)

    state = mutations.set_organizer_tags(workspace, boss, [eightm])

    assert _org(state, boss)["tags"] == [eightm]
    assert mutations.organizer_tags(state, boss) == {
        "direct": [eightm],
        "implied": [gchd],
        "effective": [eightm, gchd],
    }


def test_an_unknown_tag_is_refused_for_an_organizer(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")

    with pytest.raises(mutations.RosteringError, match="No such tag"):
        mutations.set_organizer_tags(workspace, boss, [99])


def test_a_tag_can_be_taken_off_an_organizer(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    lab = _new_tag(workspace, "Lab")
    mutations.set_organizer_tags(workspace, boss, [lab])

    state = mutations.remove_tag_from_organizer(workspace, lab, boss)

    assert mutations.organizer_tags(state, boss)["direct"] == []


def test_the_tags_tab_lists_organizer_carriers_and_counts(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    gchd = _new_tag(workspace, "GCHD")
    eightm = _new_tag(workspace, "8.M", parent_id=gchd)
    mutations.set_organizer_tags(workspace, boss, [eightm])
    state = mutations.set_helper_tags(workspace, 1, [gchd])

    assert mutations.tag_organizer_carriers(state, gchd) == [{"organizer_id": boss, "name": "Boss", "via": eightm}]
    assert mutations.tag_organizer_carriers(state, eightm) == [{"organizer_id": boss, "name": "Boss", "via": None}]
    assert mutations.tag_organizer_counts(state) == {gchd: 1, eightm: 1}
    assert mutations.tag_helper_counts(state) == {gchd: 1, eightm: 0}


def test_a_tag_can_be_bulk_applied_to_helpers_and_organizers_together(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    lab = _new_tag(workspace, "Lab")

    state = mutations.add_tag_to_helpers(workspace, lab, [1], organizer_ids=[boss])

    assert mutations.helper_tags(state, 1)["direct"] == [lab]
    assert mutations.organizer_tags(state, boss)["direct"] == [lab]


def test_deleting_a_tag_asks_first_when_an_organizer_carries_it_then_strips_it(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    lab = _new_tag(workspace, "Lab")
    mutations.set_organizer_tags(workspace, boss, [lab])
    state = mutations.get_state(workspace)

    assert mutations.tag_delete_impact(state, lab)["organizers"] == ["Boss"]
    with pytest.raises(mutations.ConfirmationRequired):
        mutations.delete_tag(workspace, lab)
    state = mutations.delete_tag(workspace, lab, confirmed=True)

    assert not _org(state, boss).get("tags")


def test_the_grid_shows_organizer_pills_and_the_filter_dims_them(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    other = _create(workspace, "Other")
    gchd = _new_tag(workspace, "GCHD", colour="#3366cc")
    eightm = _new_tag(workspace, "8.M", parent_id=gchd, colour="#dc3912")
    mutations.set_organizer_tags(workspace, boss, [eightm])
    state = mutations.get_state(workspace)

    pills = mutations.organizer_tag_pills(state)
    assert pills[boss] == {
        "direct": [{"name": "8.M", "colour": "#dc3912"}],
        "implied": [{"name": "GCHD", "colour": "#3366cc"}],
    }
    assert pills[other] == {"direct": [], "implied": []}
    assert mutations.dimmed_organizer_ids(state, [gchd], "all") == [other]
    assert mutations.dimmed_organizer_ids(state, [], "all") == []


# -- Tag constraints on an Organizer's placement ---------------------------------------


def test_an_organizers_allowed_buildings_follow_their_tags_and_the_role_axis_does_not_apply(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    karlin_only = _new_tag(workspace, "Karlín-only", building_allow=["Karlín"])
    mutations.set_organizer_tags(workspace, boss, [karlin_only])

    assert mutations.organizer_allowed(mutations.get_state(workspace), boss) == {"buildings": ["Karlín"]}


def test_a_tag_that_leaves_an_organizer_no_allowed_building_is_refused(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    no_karlin = _new_tag(workspace, "No Karlín", building_deny=["Karlín"])
    no_impakt = _new_tag(workspace, "No Impakt", building_deny=["Impakt"])
    mutations.set_organizer_tags(workspace, boss, [no_karlin])

    with pytest.raises(mutations.RosteringError, match="Boss"):
        mutations.set_organizer_tags(workspace, boss, [no_karlin, no_impakt])
    # Editing a Tag is refused the same way once an Organizer carries it.
    with pytest.raises(mutations.RosteringError, match="Boss"):
        mutations.update_tag(workspace, no_karlin, building_deny=["Karlín", "Impakt"])
    assert mutations.organizer_tags(mutations.get_state(workspace), boss)["direct"] == [no_karlin]


def test_a_role_constraint_never_strands_an_organizer(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    no_roles = _new_tag(workspace, "No roles", role_deny=[role.name for role in Role])

    state = mutations.set_organizer_tags(workspace, boss, [no_roles])

    assert mutations.organizer_tags(state, boss)["direct"] == [no_roles]


def test_a_leader_placed_in_a_forbidden_building_is_a_broken_rule_never_a_refusal(workspace):
    _solved_state(workspace)
    boss = _create(workspace, "Boss")
    karlin_only = _new_tag(workspace, "Karlín-only", building_allow=["Karlín"])
    mutations.set_organizer_tags(workspace, boss, [karlin_only])

    # The hand placement goes through.
    state = mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Impakt")

    broken = [b for b in mutations.broken_rules(state) if b.organizer_ids]
    assert len(broken) == 1
    rule = broken[0]
    assert rule.family == "tag_restrictions"
    assert rule.instance == RuleInstance("tag_building", ("organizer", boss, "Impakt"))
    assert rule.organizer_ids == (boss,)
    assert "Boss" in rule.line and "Impakt" in rule.line
    assert rule.fix.tab == "tags" and rule.fix.organizer_id == boss and rule.fix.tag_id == karlin_only

    # Moving them into an allowed Building clears it at once.
    fixed = mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")
    assert [b for b in mutations.broken_rules(fixed) if b.organizer_ids] == []


def test_a_room_level_placement_marks_that_room_and_the_grid_marks_name_the_organizer(workspace):
    _solved_state(workspace)
    boss = _create(workspace, "Boss")
    karlin_only = _new_tag(workspace, "Karlín-only", building_allow=["Karlín"])
    mutations.set_organizer_tags(workspace, boss, [karlin_only])
    state = mutations.assign_organizer(workspace, boss, "PravaRuka", "Impakt", "I1")

    marks = mutations.broken_rule_marks(mutations.broken_rules(state))

    assert [m["organizer_id"] for m in marks["organizers"]] == [boss]
    assert {"building": "Impakt", "room": "I1", "role": None} == {
        k: v for k, v in marks["cells"][0].items() if k != "line"
    }


def test_an_organizer_tag_rule_is_judged_even_before_the_first_solve(workspace):
    _seed(workspace)
    boss = _create(workspace, "Boss")
    karlin_only = _new_tag(workspace, "Karlín-only", building_allow=["Karlín"])
    mutations.set_organizer_tags(workspace, boss, [karlin_only])
    state = mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Impakt")

    # Only the Organizer's rule: an empty roster is not one that breaks minimums.
    assert [b.organizer_ids for b in mutations.broken_rules(state)] == [(boss,)]


def test_an_unplaced_organizer_or_an_untagged_one_breaks_nothing(workspace):
    _solved_state(workspace)
    boss = _create(workspace, "Boss")
    other = _create(workspace, "Other")
    karlin_only = _new_tag(workspace, "Karlín-only", building_allow=["Karlín"])
    mutations.set_organizer_tags(workspace, boss, [karlin_only])
    state = mutations.assign_organizer(workspace, other, "VedouciBudovy", "Impakt")

    assert [b for b in mutations.broken_rules(state) if b.organizer_ids] == []


def test_the_live_checker_judges_an_organizer_on_domain_objects():
    comp = _two_room_competition(
        [Organizer(id=3, name="Boss", building="B", room="R2", tags=[1])], [Helper(id=1, name="Anna")]
    )
    comp.tags = [Tag(id=1, name="Nowhere", colour="#000000", note="", parent_id=None, building_deny=("B",))]

    broken = check_roster(comp, [])

    assert [(b.family, b.organizer_ids, b.cells) for b in broken] == [("tag_restrictions", (3,), (("B", "R2", None),))]


def test_the_solver_leaves_a_forbidden_organizer_where_they_are():
    """An Organizer is a fixed anchor: the solver neither moves nor reports them."""
    comp = _two_room_competition(
        [Organizer(id=3, name="Boss", building="B", room="R2", tags=[1])], [Helper(id=1, name="Anna")]
    )
    comp.tags = [Tag(id=1, name="Nowhere", colour="#000000", note="", parent_id=None, building_deny=("B",))]

    result = solve_competition(comp, SolverConfig())

    assert [b for b in result.broken_rules if "Boss" in b.line] == []
    assert (comp.organizers[0].building, comp.organizers[0].room) == ("B", "R2")
