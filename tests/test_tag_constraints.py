"""Tag constraints: allow-lists and deny-lists a Tag places on Building and Role,
the allowed sets they give a Helper, the refusal of any edit that would leave a
Helper nowhere to go, and their enforcement by the solver (as the Tag tier of the
relaxation) and by the live Broken-rule checker.

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
from rostering.persistence.workspace import Workspace
from rostering.solver.checker import check_roster
from rostering.solver.model import SolverConfig, solve_competition
from rostering.webapp import mutations
from rostering.tags import Tag

ROLE_NAMES = [role.name for role in Role]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "workspace")


def _config(*buildings):
    return [
        {"name": name, "rooms": [{"name": f"{name}-R1", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}}
        for name in buildings
    ]


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


def _seed(workspace, buildings=("Karlín", "Impakt", "Hostivař"), names=("Anna", "Petr", "Jana")):
    state = workspace.load()
    state["helpers"] = [_helper(i, name) for i, name in enumerate(names, start=1)]
    workspace.save(state)
    mutations.put_config(workspace, _config(*buildings))
    return workspace.load()


def _new_tag(workspace, name, parent_id=None, **kwargs) -> int:
    state = mutations.add_tag(workspace, name, parent_id=parent_id, **kwargs)
    return next(t["id"] for t in state["tags"] if t["name"] == name)


def _allowed(workspace, helper_id):
    return mutations.helper_allowed(mutations.get_state(workspace), helper_id)


# -- entering constraints ------------------------------------------------------


def test_a_tag_can_carry_building_and_role_allow_and_deny_lists(workspace):
    _seed(workspace)

    state = mutations.add_tag(
        workspace,
        "8.M",
        building_allow=["Karlín"],
        building_deny=["Hostivař"],
        role_allow=["Fotograf", "Skenovac"],
        role_deny=["Zaloha"],
    )

    entries = mutations.tag_constraint_entries(state, state["tags"][0]["id"])
    assert [e["name"] for e in entries["building_allow"]] == ["Karlín"]
    assert [e["name"] for e in entries["building_deny"]] == ["Hostivař"]
    assert [e["name"] for e in entries["role_allow"]] == ["Fotograf", "Skenovac"]
    assert [e["name"] for e in entries["role_deny"]] == ["Zaloha"]
    assert mutations.tag_constraint_entries(mutations.get_state(workspace), state["tags"][0]["id"]) == entries


def test_a_tag_without_constraints_has_empty_lists(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "GCHD")

    entries = mutations.tag_constraint_entries(mutations.get_state(workspace), tag_id)

    assert entries == {"building_allow": [], "building_deny": [], "role_allow": [], "role_deny": []}


def test_constraints_are_edited_through_update_tag_and_left_alone_when_not_given(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", building_allow=["Karlín"], role_deny=["Fotograf"])

    state = mutations.update_tag(workspace, tag_id, note="a class", building_deny=["Hostivař"])

    entries = mutations.tag_constraint_entries(state, tag_id)
    assert [e["name"] for e in entries["building_allow"]] == ["Karlín"]  # untouched
    assert [e["name"] for e in entries["building_deny"]] == ["Hostivař"]
    assert [e["name"] for e in entries["role_deny"]] == ["Fotograf"]  # untouched

    cleared = mutations.update_tag(workspace, tag_id, building_allow=[])
    assert mutations.tag_constraint_entries(cleared, tag_id)["building_allow"] == []


def test_a_role_entry_must_name_one_of_the_roles(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError, match="role"):
        mutations.add_tag(workspace, "8.M", role_deny=["Kapitán"])

    assert mutations.get_state(workspace)["tags"] == []


def test_a_role_may_be_named_by_its_display_name(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", role_deny=["Měnič"])

    entries = mutations.tag_constraint_entries(mutations.get_state(workspace), tag_id)

    assert [e["name"] for e in entries["role_deny"]] == ["Menic"]


def test_entries_naming_a_building_no_longer_configured_are_inert_and_flagged(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", building_allow=["Karlín", "Impakt"])
    tag_id_2 = _new_tag(workspace, "GCHD", building_deny=["Hostivař"])
    state = mutations.put_config(workspace, _config("Karlín", "Hostivař"))  # Impakt is gone

    entries = mutations.tag_constraint_entries(state, tag_id)

    assert entries["building_allow"] == [
        {"name": "Karlín", "in_season": True},
        {"name": "Impakt", "in_season": False},
    ]
    mutations.set_helper_tags(workspace, 1, [tag_id])
    # The Karlín entry alone narrows; the inert Impakt one is ignored.
    assert _allowed(workspace, 1)["buildings"] == ["Karlín"]
    assert mutations.tag_constraint_entries(state, tag_id_2)["building_deny"][0]["in_season"] is True


def test_an_allow_list_naming_only_absent_buildings_does_not_narrow_anything(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", building_allow=["Nowhere"])
    mutations.set_helper_tags(workspace, 1, [tag_id])

    assert _allowed(workspace, 1)["buildings"] == ["Karlín", "Impakt", "Hostivař"]


# -- a Helper's allowed sets ----------------------------------------------------


def test_a_helper_with_no_tags_may_go_anywhere(workspace):
    _seed(workspace)

    assert _allowed(workspace, 1) == {"buildings": ["Karlín", "Impakt", "Hostivař"], "roles": ROLE_NAMES}


def test_an_allow_list_restricts_the_helper_to_it(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", building_allow=["Karlín"], role_allow=["Fotograf", "Skenovac"])
    mutations.set_helper_tags(workspace, 1, [tag_id])

    assert _allowed(workspace, 1) == {"buildings": ["Karlín"], "roles": ["Skenovac", "Fotograf"]}
    assert _allowed(workspace, 2)["buildings"] == ["Karlín", "Impakt", "Hostivař"]  # nobody else affected


def test_a_deny_list_removes_from_the_full_set(workspace):
    _seed(workspace)
    tag_id = _new_tag(workspace, "Pros", building_deny=["Hostivař"], role_deny=["Fotograf"])
    mutations.set_helper_tags(workspace, 1, [tag_id])

    allowed = _allowed(workspace, 1)

    assert allowed["buildings"] == ["Karlín", "Impakt"]
    assert "Fotograf" not in allowed["roles"] and len(allowed["roles"]) == 5


def test_allow_lists_of_several_tags_intersect(workspace):
    _seed(workspace)
    a = _new_tag(workspace, "A", building_allow=["Karlín", "Impakt"])
    b = _new_tag(workspace, "B", building_allow=["Impakt", "Hostivař"])
    mutations.set_helper_tags(workspace, 1, [a, b])

    assert _allowed(workspace, 1)["buildings"] == ["Impakt"]


def test_a_tag_with_no_allow_list_does_not_narrow(workspace):
    _seed(workspace)
    narrow = _new_tag(workspace, "Narrow", building_allow=["Karlín"])
    plain = _new_tag(workspace, "Plain", role_deny=["Fotograf"])
    mutations.set_helper_tags(workspace, 1, [narrow, plain])

    assert _allowed(workspace, 1)["buildings"] == ["Karlín"]


def test_a_deny_always_wins_over_any_allow(workspace):
    _seed(workspace)
    allows = _new_tag(workspace, "Allows", building_allow=["Karlín", "Impakt"])
    denies = _new_tag(workspace, "Denies", building_deny=["Karlín"])
    mutations.set_helper_tags(workspace, 1, [allows, denies])

    assert _allowed(workspace, 1)["buildings"] == ["Impakt"]


def test_an_implied_tags_constraints_apply_to_a_helper_who_only_carries_the_child(workspace):
    _seed(workspace)
    parent = _new_tag(workspace, "GCHD", building_allow=["Karlín", "Impakt"])
    child = _new_tag(workspace, "8.M", parent_id=parent, building_deny=["Impakt"])
    mutations.set_helper_tags(workspace, 1, [child])

    assert _allowed(workspace, 1)["buildings"] == ["Karlín"]
    assert _allowed(workspace, 2)["buildings"] == ["Karlín", "Impakt", "Hostivař"]


def test_building_entries_are_matched_the_way_building_preferences_are(workspace):
    # The survey and the configs spell buildings differently ("Malá Strana" /
    # "Mala Strana", "Impakt + Hostivař" / "Hostivař"): they name one Building.
    _seed(workspace, buildings=("Mala Strana", "Troja", "Karlín"))
    tag_id = _new_tag(workspace, "8.M", building_allow=["Malá Strana", "Impakt + Troja"])
    mutations.set_helper_tags(workspace, 1, [tag_id])

    assert _allowed(workspace, 1)["buildings"] == ["Mala Strana", "Troja"]


# -- refusing edits that leave a Helper nowhere to go -----------------------------


def _dead_end_pair(workspace):
    """Two Tags whose Building allow-lists cannot both hold."""
    a = _new_tag(workspace, "A", building_allow=["Karlín"])
    b = _new_tag(workspace, "B", building_allow=["Impakt"])
    return a, b


def test_a_tag_assignment_leaving_no_allowed_building_is_refused_with_the_reason(workspace):
    _seed(workspace)
    a, b = _dead_end_pair(workspace)
    mutations.set_helper_tags(workspace, 1, [a])

    with pytest.raises(mutations.RosteringError) as refused:
        mutations.set_helper_tags(workspace, 1, [a, b])

    text = str(refused.value)
    assert "Anna" in text and "budovu" in text
    assert "Štítek A, povoluje jen budovu Karlín" in text and "Štítek B, povoluje jen budovu Impakt" in text
    assert _direct(workspace, 1) == [a]  # nothing changed


def test_a_deny_that_empties_the_roles_is_refused_too(workspace):
    _seed(workspace)
    everything = _new_tag(workspace, "Nothing", role_deny=ROLE_NAMES)

    with pytest.raises(mutations.RosteringError, match="roli"):
        mutations.set_helper_tags(workspace, 1, [everything])


def test_a_bulk_assignment_is_all_or_nothing(workspace):
    _seed(workspace)
    a, b = _dead_end_pair(workspace)
    mutations.set_helper_tags(workspace, 2, [b])

    with pytest.raises(mutations.RosteringError, match="Petr"):
        mutations.add_tag_to_helpers(workspace, a, [1, 2])

    assert _direct(workspace, 1) == [] and _direct(workspace, 2) == [b]


def test_a_tag_that_carries_no_helper_can_hold_any_constraint(workspace):
    _seed(workspace)

    mutations.add_tag(workspace, "Nothing", role_deny=ROLE_NAMES)  # nobody carries it: nobody is stranded


def test_a_constraint_edit_that_would_strand_a_carrier_is_refused_and_not_saved(workspace):
    _seed(workspace)
    a, b = _dead_end_pair(workspace)
    both = _new_tag(workspace, "Both")
    mutations.set_helper_tags(workspace, 1, [a, both])

    with pytest.raises(mutations.RosteringError, match="Anna"):
        mutations.update_tag(workspace, both, building_allow=["Impakt"])

    entries = mutations.tag_constraint_entries(mutations.get_state(workspace), both)
    assert entries["building_allow"] == []


def test_the_same_check_covers_carriers_by_implication(workspace):
    _seed(workspace)
    parent = _new_tag(workspace, "GCHD")
    child = _new_tag(workspace, "8.M", parent_id=parent, building_allow=["Karlín"])
    mutations.set_helper_tags(workspace, 1, [child])

    with pytest.raises(mutations.RosteringError, match="Anna"):
        mutations.update_tag(workspace, parent, building_deny=["Karlín"])


def test_re_parenting_a_tag_under_a_conflicting_one_is_refused(workspace):
    _seed(workspace)
    a, b = _dead_end_pair(workspace)
    mutations.set_helper_tags(workspace, 1, [b])

    with pytest.raises(mutations.RosteringError, match="Anna"):
        mutations.update_tag(workspace, b, parent_id=a)

    assert next(t for t in mutations.get_state(workspace)["tags"] if t["id"] == b)["parent_id"] is None


def test_a_constraint_edit_that_only_widens_or_keeps_everyone_placeable_is_accepted(workspace):
    _seed(workspace)
    a, _ = _dead_end_pair(workspace)
    mutations.set_helper_tags(workspace, 1, [a])

    mutations.update_tag(workspace, a, building_allow=["Karlín", "Impakt"])

    assert _allowed(workspace, 1)["buildings"] == ["Karlín", "Impakt"]


def test_a_helper_already_stranded_does_not_block_unrelated_edits(workspace):
    _seed(workspace)
    a, b = _dead_end_pair(workspace)
    mutations.set_helper_tags(workspace, 1, [a])
    mutations.set_helper_tags(workspace, 2, [b])
    # The configuration changes under Anna: Karlín is gone, so her allow-list is
    # entirely inert -- then Impakt is denied elsewhere and she has nowhere.
    stranded = _new_tag(workspace, "Nowhere", building_deny=["Karlín", "Impakt", "Hostivař"])
    state = workspace.load()
    next(h for h in state["helpers"] if h["id"] == 1)["tags"].append(stranded)  # legacy, unvalidated
    workspace.save(state)
    assert _allowed(workspace, 1)["buildings"] == []

    mutations.set_helper_tags(workspace, 3, [a])  # someone else, fine
    mutations.set_helper_tags(workspace, 2, [b, _new_tag(workspace, "Plain")])  # unrelated to Anna


def test_deleting_a_tag_never_strands_anyone(workspace):
    _seed(workspace)
    a = _new_tag(workspace, "A", building_allow=["Karlín"])
    mutations.set_helper_tags(workspace, 1, [a])

    mutations.delete_tag(workspace, a, confirmed=True)

    assert _allowed(workspace, 1)["buildings"] == ["Karlín", "Impakt", "Hostivař"]


def test_the_checks_use_the_seasons_configured_buildings(workspace):
    # Karlín is not configured this Season, so an allow-list naming only it is
    # inert and cannot strand anyone.
    _seed(workspace, buildings=("Impakt", "Hostivař"))
    a = _new_tag(workspace, "A", building_allow=["Karlín"])
    b = _new_tag(workspace, "B", building_allow=["Impakt"])

    mutations.set_helper_tags(workspace, 1, [a, b])

    assert _allowed(workspace, 1)["buildings"] == ["Impakt"]


def _direct(workspace, helper_id):
    return mutations.helper_tags(mutations.get_state(workspace), helper_id)["direct"]


# -- the live checker ------------------------------------------------------------


def _assignment(hid, name, building, role="Zaloha"):
    return {"helper_id": hid, "helper_name": name, "building": building, "room": f"{building}-R1", "role": role}


def _seed_roster(workspace):
    """Anna (Tag 8.M: allows only Karlín) sits in Karlín; Petr and Jana are free."""
    _seed(workspace)
    tag_id = _new_tag(workspace, "8.M", building_allow=["Karlín"])
    mutations.set_helper_tags(workspace, 1, [tag_id])
    state = workspace.load()
    state["assignments"] = [
        _assignment(1, "Anna", "Karlín"),
        _assignment(2, "Petr", "Impakt"),
        _assignment(3, "Jana", "Hostivař"),
    ]
    workspace.save(state)
    return tag_id


def _tag_rules(state):
    return [b for b in mutations.broken_rules(state) if b.family == "tag_restrictions"]


def test_a_roster_that_keeps_every_tag_constraint_reports_nothing(workspace):
    _seed_roster(workspace)

    assert _tag_rules(mutations.get_state(workspace)) == []


def test_a_helper_outside_their_allowed_buildings_is_reported_with_the_tag(workspace):
    tag_id = _seed_roster(workspace)

    state = mutations.move_helper(workspace, 1, "Impakt", "Impakt-R1", "Zaloha")

    (broken,) = _tag_rules(state)
    assert broken.line == "Pomocník Anna (Štítek 8.M, povoluje jen budovu Karlín) je zařazen(a) do Impakt"
    assert broken.amount == 1
    assert broken.instance == RuleInstance("tag_building", (1, "Impakt"))
    assert broken.helper_ids == (1,)
    assert broken.cells == (("Impakt", "Impakt-R1", None),)
    assert (broken.fix.tab, broken.fix.tag_id, broken.fix.helper_id) == ("tags", tag_id, 1)


def test_moving_the_helper_back_clears_it_at_once(workspace):
    _seed_roster(workspace)
    mutations.move_helper(workspace, 1, "Impakt", "Impakt-R1", "Zaloha")

    fixed = mutations.move_helper(workspace, 1, "Karlín", "Karlín-R1", "Zaloha")

    assert _tag_rules(fixed) == []


def test_a_denied_role_is_reported(workspace):
    _seed_roster(workspace)
    pros = _new_tag(workspace, "GCHD", role_deny=["Fotograf"])
    mutations.set_helper_tags(workspace, 2, [pros])

    state = mutations.move_helper(workspace, 2, "Impakt", "Impakt-R1", "Fotograf")

    (broken,) = _tag_rules(state)
    assert broken.line == "Pomocník Petr (Štítek GCHD, zakazuje roli Fotograf) je zařazen(a) jako Fotograf"
    assert broken.instance == RuleInstance("tag_role", (2, "Fotograf"))
    assert broken.fix.tag_id == pros


def test_an_inherited_constraint_names_the_tag_that_states_it(workspace):
    _seed_roster(workspace)
    parent = _new_tag(workspace, "GCHD", building_deny=["Hostivař"])
    child = _new_tag(workspace, "9.A", parent_id=parent)
    mutations.set_helper_tags(workspace, 3, [child])

    (broken,) = _tag_rules(mutations.get_state(workspace))

    assert broken.line == "Pomocník Jana (Štítek GCHD, zakazuje budovu Hostivař) je zařazen(a) do Hostivař"
    assert broken.fix.tag_id == parent


def test_a_broken_placement_names_only_the_tags_that_exclude_it(workspace):
    _seed_roster(workspace)
    a = _new_tag(workspace, "A", building_allow=["Impakt", "Hostivař"])
    b = _new_tag(workspace, "B", building_deny=["Hostivař"])
    mutations.set_helper_tags(workspace, 3, [a, b])

    (broken,) = _tag_rules(mutations.get_state(workspace))

    assert broken.line == "Pomocník Jana (Štítek B, zakazuje budovu Hostivař) je zařazen(a) do Hostivař"
    mutations.move_helper(workspace, 3, "Karlín", "Karlín-R1", "Zaloha")
    (broken,) = _tag_rules(mutations.get_state(workspace))
    assert broken.line == "Pomocník Jana (Štítek A, povoluje jen budovy Impakt, Hostivař) je zařazen(a) do Karlín"


def test_a_drop_that_newly_breaks_a_tag_constraint_toasts_the_banner_line_and_still_applies(workspace):
    _seed_roster(workspace)
    before = mutations.get_state(workspace)

    after = mutations.move_helper(workspace, 1, "Hostivař", "Hostivař-R1", "Zaloha")

    moved = next(a for a in after["assignments"] if a["helper_id"] == 1)
    assert moved["building"] == "Hostivař"  # never refused
    assert mutations.move_toast_lines(before, after) == [
        "Pomocník Anna (Štítek 8.M, povoluje jen budovu Karlín) je zařazen(a) do Hostivař"
    ]


def test_a_constraint_already_broken_before_the_drop_does_not_toast_again(workspace):
    _seed_roster(workspace)
    before = mutations.move_helper(workspace, 1, "Hostivař", "Hostivař-R1", "Zaloha")

    after = mutations.move_helper(workspace, 1, "Hostivař", "Hostivař-R1", "Fotograf")

    assert _tag_rules(after) and mutations.move_toast_lines(before, after) == []


def test_tag_restrictions_sort_between_minimums_and_equipment(workspace):
    _seed_roster(workspace)
    state = workspace.load()
    state["config"][0]["rooms"][0]["capacities"]["Skenovac"] = {"minimum": 1}  # Karlín-R1 needs a scanner
    state["helpers"][0]["can_bring_camera"] = False
    workspace.save(state)

    # Anna: no camera, so Fotograf breaks equipment, and Hostivař breaks 8.M.
    state = mutations.move_helper(workspace, 1, "Hostivař", "Hostivař-R1", "Fotograf")

    assert [b.family for b in mutations.broken_rules(state)] == ["minimums", "tag_restrictions", "equipment"]


def test_a_stale_assignment_to_a_removed_building_does_not_crash_the_check(workspace):
    _seed_roster(workspace)
    state = workspace.load()
    state["assignments"][0] = _assignment(1, "Anna", "Gone")

    assert _tag_rules(state) == []


def test_a_helper_who_cant_attend_is_not_judged(workspace):
    _seed_roster(workspace)
    mutations.move_helper(workspace, 1, "Hostivař", "Hostivař-R1", "Zaloha")

    state = mutations.set_cant_attend(workspace, 1, True, confirmed=True)

    assert _tag_rules(state) == []


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


def _competition(buildings, helpers, tags):
    return Competition(buildings={b.name: b for b in buildings}, helpers=helpers, tags=tags)


def _by_helper(result):
    return {a.helper_id: a for a in result.assignments}


def _projection(broken_rules):
    return {b.instance: (b.family, b.amount, b.line) for b in broken_rules}


def test_a_helper_restricted_to_one_building_is_placed_there():
    tags = [Tag(id=1, name="8.M", colour="#3366cc", building_allow=("B",))]
    helpers = [Helper(id=i, name=f"H{i}", tags=[1] if i <= 3 else []) for i in range(1, 7)]
    comp = _competition([_building("A"), _building("B"), _building("C")], helpers, tags)

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert {_by_helper(result)[i].building for i in (1, 2, 3)} == {"B"}


def test_a_denied_role_is_never_given_to_the_helper():
    tags = [Tag(id=1, name="Pros", colour="#3366cc", role_deny=("Fotograf", "Opravovatel"))]
    helpers = [
        Helper(
            id=i,
            name=f"H{i}",
            can_bring_camera=True,
            # They would love to be Fotograf, but the Tag forbids it.
            role_preferences={Role.Fotograf: Preference.Ano},
            tags=[1],
        )
        for i in range(1, 4)
    ]
    comp = _competition([_building("A")], helpers, tags)

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []
    assert all(a.role not in (Role.Fotograf, Role.Opravovatel) for a in result.assignments)


def test_combined_tags_are_respected_including_an_implied_parent():
    tags = [
        Tag(id=1, name="GCHD", colour="#3366cc", building_allow=("A", "B"), role_deny=("Zaloha",)),
        Tag(id=2, name="8.M", colour="#dc3912", parent_id=1, building_deny=("A",)),
        Tag(id=3, name="Ref", colour="#109618", role_allow=("Skenovac", "Menic")),
    ]
    helpers = [Helper(id=1, name="Both", tags=[2, 3]), Helper(id=2, name="Child", tags=[2])]
    helpers += [Helper(id=i, name=f"H{i}") for i in range(3, 8)]
    comp = _competition([_building("A"), _building("B"), _building("C")], helpers, tags)

    result = solve_competition(comp, _solver_config())

    placed = _by_helper(result)
    assert result.broken_rules == []
    assert placed[1].building == "B" and placed[1].role in (Role.Skenovac, Role.Menic)
    assert placed[2].building == "B" and placed[2].role != Role.Zaloha


def test_building_entries_match_config_spellings_like_preferences_do():
    tags = [Tag(id=1, name="T", colour="#3366cc", building_allow=("Impakt + Troja",))]
    helpers = [Helper(id=1, name="H1", tags=[1]), Helper(id=2, name="H2")]
    comp = _competition([_building("Karlín"), _building("Troja")], helpers, tags)

    result = solve_competition(comp, _solver_config())

    assert _by_helper(result)[1].building == "Troja"


def test_an_entry_naming_an_absent_building_or_an_absent_allow_list_is_inert():
    tags = [Tag(id=1, name="T", colour="#3366cc", building_allow=("Nowhere",), building_deny=("Elsewhere",))]
    comp = _competition([_building("A")], [Helper(id=1, name="H1", tags=[1])], tags)

    result = solve_competition(comp, _solver_config())

    assert result.broken_rules == []


def test_a_minimum_bends_before_a_tag_restriction_does():
    # Building B needs a Skenovač, but the only Helper is barred from B.
    tags = [Tag(id=1, name="OnlyA", colour="#3366cc", building_allow=("A",))]
    building_b = _building("B", _room("B-R1", Skenovac=1))
    comp = _competition([_building("A"), building_b], [Helper(id=1, name="H1", tags=[1])], tags)

    result = solve_competition(comp, _solver_config())

    assert _by_helper(result)[1].building == "A"
    assert [b.family for b in result.broken_rules] == ["minimums"]


def test_a_tag_restriction_bends_when_it_is_the_only_thing_that_can():
    # Both Buildings are denied and the Helper is pinned: the Tag rule bends
    # and the roster still comes back.
    tags = [Tag(id=1, name="Nowhere", colour="#3366cc", building_deny=("A", "B"))]
    comp = _competition([_building("A"), _building("B")], [Helper(id=1, name="H1", tags=[1])], tags)

    result = solve_competition(comp, _solver_config())

    assert len(result.assignments) == 1
    assert [b.family for b in result.broken_rules] == ["tag_restrictions"]
    assert result.broken_rules[0].line.startswith("Pomocník H1 (Štítek Nowhere, zakazuje budovy A, B) je zařazen(a) do ")


def test_a_tag_restriction_bends_before_equipment():
    # A no-camera Helper who may only be Fotograf: one of the two must bend,
    # and it is the Tag restriction, never the (stricter) equipment rule.
    tags = [Tag(id=1, name="OnlyPhoto", colour="#3366cc", role_allow=("Fotograf",))]
    comp = _competition([_building("A")], [Helper(id=1, name="H1", can_bring_camera=False, tags=[1])], tags)

    result = solve_competition(comp, _solver_config())

    assert _by_helper(result)[1].role != Role.Fotograf
    assert [b.family for b in result.broken_rules] == ["tag_restrictions"]


def test_a_fixed_assignment_outside_the_allowed_set_stands_and_is_reported():
    tags = [Tag(id=1, name="OnlyA", colour="#3366cc", building_allow=("A",))]
    comp = _competition([_building("A"), _building("B")], [Helper(id=1, name="H1", tags=[1])], tags)
    fixed = Assignment(helper_id=1, helper_name="H1", building="B", room="B-R1", role=Role.Zaloha)

    result = solve_competition(comp, _solver_config(), fixed_assignments=[fixed])

    assert _by_helper(result)[1].building == "B"
    assert [b.instance for b in result.broken_rules] == [RuleInstance("tag_building", (1, "B"))]
    assert result.broken_rules[0].line == "Pomocník H1 (Štítek OnlyA, povoluje jen budovu A) je zařazen(a) do B"


def test_a_helper_who_cant_attend_is_left_out_of_the_tag_rule():
    tags = [Tag(id=1, name="Nowhere", colour="#3366cc", building_deny=("A",))]
    helpers = [Helper(id=1, name="H1", tags=[1], cant_attend=True), Helper(id=2, name="H2")]
    comp = _competition([_building("A")], helpers, tags)

    assert solve_competition(comp, _solver_config()).broken_rules == []


def _random_tagged_competition(rng):
    tags = [
        Tag(id=1, name="T1", colour="#3366cc", building_allow=("B0", "B1")),
        Tag(id=2, name="T2", colour="#dc3912", parent_id=1, building_deny=("B0",), role_deny=("Fotograf",)),
        Tag(id=3, name="T3", colour="#109618", role_allow=("Skenovac", "Menic", "Zaloha")),
        Tag(id=4, name="T4", colour="#ff9900", building_allow=("B2",), role_deny=("Zaloha",)),
    ]
    buildings = []
    for b in range(3):
        rooms = [_room(f"B{b}R{r}", **({"Skenovac": rng.randint(1, 3)} if rng.random() < 0.5 else {})) for r in range(2)]
        buildings.append(Building(name=f"B{b}", rooms=rooms))
    helpers = [
        Helper(
            id=i,
            name=f"H{i}",
            can_bring_camera=rng.random() < 0.4,
            tags=rng.sample([1, 2, 3, 4], rng.randint(0, 2)),
        )
        for i in range(1, rng.randint(4, 10))
    ]
    return _competition(buildings, helpers, tags)


@pytest.mark.parametrize("seed", range(12))
def test_the_checker_agrees_with_the_solvers_own_bent_tag_rules(seed):
    comp = _random_tagged_competition(random.Random(seed))

    result = solve_competition(comp, _solver_config())

    assert _projection(check_roster(comp, result.assignments)) == _projection(result.broken_rules)


# -- through the mutation layer: a full solve --------------------------------------


def test_a_solve_through_the_workspace_honours_the_tags(workspace):
    _seed(workspace, names=("Anna", "Petr", "Jana", "Eva", "Karel", "Lucie"))
    tag_id = _new_tag(workspace, "8.M", building_allow=["Hostivař"], role_deny=["Fotograf"])
    for hid in (1, 2, 3):
        mutations.add_tag_to_helpers(workspace, tag_id, [hid])

    state = mutations.solve(workspace)

    by_helper = {a["helper_id"]: a for a in state["assignments"]}
    assert all(by_helper[i]["building"] == "Hostivař" and by_helper[i]["role"] != "Fotograf" for i in (1, 2, 3))
    assert mutations.broken_rules(state) == []


# -- older saved states and the "Go fix" hand-off --------------------------------


def test_a_tag_saved_before_constraints_existed_has_none(workspace):
    _seed(workspace)
    state = workspace.load()
    state["tags"] = [{"id": 1, "name": "Old", "colour": "#3366cc", "note": "", "parent_id": None}]
    state["next_tag_id"] = 2
    state["helpers"][0]["tags"] = [1]
    workspace.save(state)

    state = mutations.get_state(workspace)

    assert mutations.tag_constraint_entries(state, 1) == {
        "building_allow": [],
        "building_deny": [],
        "role_allow": [],
        "role_deny": [],
    }
    assert mutations.helper_allowed(state, 1)["buildings"] == ["Karlín", "Impakt", "Hostivař"]


def test_a_tag_rule_has_a_go_fix_button_to_the_tags_tab(workspace):
    from rostering.webapp.ui import fix_focus

    _seed_roster(workspace)
    state = mutations.move_helper(workspace, 1, "Impakt", "Impakt-R1", "Zaloha")

    (broken,) = _tag_rules(state)

    assert fix_focus.can_go_fix(broken)
    assert fix_focus.TAB_LABELS[broken.fix.tab] == "2. Štítky"
