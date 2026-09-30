"""Place new registrants: a solve with every existing Assignment held fixed, so a
late registrant is placed without touching the roster. Exercised through the
mutation layer against a temp-dir workspace with the synthetic surveys of
``test_reupload`` and, for the solver seam, small hand-built competitions (never
``data/``)."""
import pytest

from rostering.domain import Assignment, Building, Competition, Helper, Role, RoleCapacity, Room
from rostering.solver.model import SolverConfig, solve_competition
from rostering.streamlit_app import mutations
from tests.test_reupload import (  # noqa: F401  (the fixtures are used by name)
    ANNA,
    JANA,
    KLARA,
    PETR,
    _named,
    _placement,
    _row,
    _upload,
    workspace,
)

MINIMUM_CONFIG = [
    {
        "name": "Karlov",
        "rooms": [
            {"name": "K1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "K2", "capacities": {"Zaloha": {"minimum": 0}, "Skenovac": {"minimum": 1}}},
        ],
        "capacities": {},
    }
]


def _season(workspace, *cells):
    """A Season of Anna, Petr and Jana placed by hand at ``cells`` (in that order)."""
    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
        label="2026-jaro",
    )
    mutations.put_config(workspace, MINIMUM_CONFIG)
    for helper, (room, role) in zip(state["helpers"], cells):
        mutations.move_helper(workspace, helper["id"], "Karlov", room, role)
    return mutations.get_state(workspace)


def _register_klara(workspace):
    state = _upload(workspace, _row("Klára Malá", KLARA))
    return _named(state, "Klára Malá")["id"]


# -- solver seam ----------------------------------------------------------------------


def _room(name, **minimums):
    caps = {Role.Zaloha: RoleCapacity(minimum=0)}
    caps.update({Role[role]: RoleCapacity(minimum=m) for role, m in minimums.items()})
    return Room(name=name, capacities=caps)


def test_with_everyone_else_fixed_a_newcomer_lands_where_a_minimum_still_needs_people():
    comp = Competition(
        buildings={"B": Building(name="B", rooms=[_room("R1"), _room("R2", Skenovac=2)])},
        helpers=[Helper(id=1, name="A"), Helper(id=2, name="B"), Helper(id=3, name="New")],
    )
    fixed = [
        Assignment(helper_id=1, helper_name="A", building="B", room="R1", role=Role.Zaloha),
        Assignment(helper_id=2, helper_name="B", building="B", room="R2", role=Role.Skenovac),
    ]

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5), fixed_assignments=fixed)

    assert {(a.helper_id, a.room, a.role) for a in result.assignments if a.helper_id != 3} == {
        (1, "R1", Role.Zaloha),
        (2, "R2", Role.Skenovac),
    }
    newcomer = next(a for a in result.assignments if a.helper_id == 3)
    assert (newcomer.room, newcomer.role) == ("R2", Role.Skenovac)
    assert result.broken_rules == []


def test_a_newcomer_is_placed_and_the_rule_reported_when_the_fixed_roster_cannot_satisfy_it():
    comp = Competition(
        buildings={"B": Building(name="B", rooms=[_room("R1", Skenovac=2)])},
        helpers=[Helper(id=1, name="A"), Helper(id=2, name="New")],
    )
    fixed = [Assignment(helper_id=1, helper_name="A", building="B", room="R1", role=Role.Zaloha)]

    result = solve_competition(comp, SolverConfig(time_limit_seconds=5), fixed_assignments=fixed)

    assert {a.helper_id for a in result.assignments} == {1, 2}
    assert len(result.broken_rules) == 1


# -- mutation -------------------------------------------------------------------------


def test_only_the_unassigned_are_placed_and_every_existing_assignment_is_untouched(workspace):
    season = _season(workspace, ("K1", "Kreslic"), ("K1", "Fotograf"), ("K1", "Menic"))
    before = {a["helper_id"]: dict(a) for a in season["assignments"]}
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    assert {a["helper_id"]: a for a in state["assignments"] if a["helper_id"] != klara} == before
    assert _placement(state, klara) is not None
    assert mutations.unplaced_helpers(state) == []


def test_the_newcomer_goes_where_a_minimum_still_needs_someone(workspace):
    _season(workspace, ("K1", "Zaloha"), ("K1", "Zaloha"), ("K1", "Zaloha"))
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    # K2 needs one Skenovač and nobody fixed is there, so the newcomer fills it.
    assert _placement(state, klara) == ("Karlov", "K2", "Skenovac")
    assert mutations.broken_rules(state) == []


def test_fixed_helpers_count_toward_a_minimum_the_newcomer_then_need_not_fill(workspace):
    _season(workspace, ("K2", "Skenovac"), ("K1", "Zaloha"), ("K1", "Zaloha"))
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    assert _placement(state, klara) is not None
    assert mutations.broken_rules(state) == []


def test_a_hand_move_that_breaks_a_rule_is_neither_repaired_nor_disturbed(workspace):
    season = _season(workspace, ("K1", "Zaloha"), ("K1", "Zaloha"), ("K1", "Zaloha"))
    assert [b.family for b in mutations.broken_rules(season)] == ["minimums"]
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    for name in ("Anna Nováková", "Petr Svoboda", "Jana Dvořáková"):
        assert _placement(state, _named(state, name)["id"])[1:] == ("K1", "Zaloha")
    assert _placement(state, klara) is not None


def test_locks_are_neither_created_nor_cleared(workspace):
    season = _season(workspace, ("K1", "Kreslic"), ("K1", "Fotograf"), ("K1", "Menic"))
    anna = _named(season, "Anna Nováková")["id"]
    mutations.set_lock(workspace, anna, True)
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    assert {a["helper_id"] for a in state["assignments"] if a.get("locked")} == {anna}
    assert not next(a for a in state["assignments"] if a["helper_id"] == klara).get("locked")


def test_it_returns_a_roster_with_the_broken_rules_reported_like_any_solve(workspace):
    _season(workspace, ("K1", "Zaloha"), ("K1", "Zaloha"), ("K1", "Zaloha"))
    # K2 needs three Skenovač: no placement of one newcomer can satisfy it.
    k1, k2 = MINIMUM_CONFIG[0]["rooms"]
    mutations.put_config(
        workspace,
        [{**MINIMUM_CONFIG[0], "rooms": [k1, {**k2, "capacities": {"Skenovac": {"minimum": 3}}}]}],
    )
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    assert _placement(state, klara) is not None
    assert [b.family for b in mutations.broken_rules(state)] == ["minimums"]
    assert [b["family"] for b in state["diagnostics"]["broken_rules"]] == ["minimums"]


def test_the_stale_flag_is_left_alone(workspace):
    _season(workspace, ("K1", "Kreslic"), ("K1", "Fotograf"), ("K1", "Menic"))
    mutations.mark_stale(workspace, "something changed")
    _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    assert mutations.stale_reasons(state) == ["something changed"]


def test_a_newcomer_who_cant_attend_is_not_placed(workspace):
    _season(workspace, ("K1", "Kreslic"), ("K1", "Fotograf"), ("K1", "Menic"))
    klara = _register_klara(workspace)
    mutations.set_cant_attend(workspace, klara, True)

    with pytest.raises(mutations.RosteringError, match="nobody to place"):
        mutations.place_new_registrants(workspace)


def test_it_refuses_when_everyone_is_already_placed(workspace):
    _season(workspace, ("K1", "Kreslic"), ("K1", "Fotograf"), ("K1", "Menic"))

    with pytest.raises(mutations.RosteringError, match="nobody to place"):
        mutations.place_new_registrants(workspace)


def test_it_refuses_before_there_is_a_roster(workspace):
    _upload(workspace, _row("Anna Nováková", ANNA), label="2026-jaro")
    mutations.put_config(workspace, MINIMUM_CONFIG)

    with pytest.raises(mutations.RosteringError, match="Solve"):
        mutations.place_new_registrants(workspace)


def test_a_helper_stranded_in_a_removed_room_is_placed_afresh(workspace):
    season = _season(workspace, ("K1", "Kreslic"), ("K2", "Fotograf"), ("K1", "Menic"))
    petr = _named(season, "Petr Svoboda")["id"]
    mutations.put_config(workspace, [{**MINIMUM_CONFIG[0], "rooms": [MINIMUM_CONFIG[0]["rooms"][0]]}])
    klara = _register_klara(workspace)

    state = mutations.place_new_registrants(workspace)

    assert _placement(state, petr)[1] == "K1"
    assert _placement(state, klara) is not None
    assert _placement(state, _named(state, "Anna Nováková")["id"]) == ("Karlov", "K1", "Kreslic")


def test_a_full_solve_still_discards_everything_but_locked_assignments(workspace):
    season = _season(workspace, ("K1", "Kreslic"), ("K1", "Fotograf"), ("K1", "Menic"))
    anna = _named(season, "Anna Nováková")["id"]
    mutations.set_lock(workspace, anna, True)
    _register_klara(workspace)
    mutations.place_new_registrants(workspace)

    state = mutations.solve(workspace)

    assert _placement(state, anna) == ("Karlov", "K1", "Kreslic")
    assert mutations.unplaced_helpers(state) == []
