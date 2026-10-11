"""Záloha is preferred for Helpers who registered later: its cost carries a
surcharge from ``SolverWeights.late_zaloha`` that falls linearly from the full
weight (earliest in ``Helper.registration_order``) to nothing (latest). Solver
tests run on plain domain objects; the order's upkeep (ingest, re-upload, hand
added, old Seasons) through the mutation layer against a temp-dir workspace."""
import pytest

from rostering.domain import Building, Competition, Helper, Preference, Role, RoleCapacity, Room
from rostering.persistence.serialize import helper_from_dict, solver_config_from_dict, solver_config_to_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.model import SolverConfig, SolverWeights, solve_competition
from rostering.webapp import mutations
from tests.test_reupload import ANNA, PETR, _named, _row, _upload

# Only Opravovatel is wanted: every other Role is "Ne", so Záloha (4) is the
# cheapest way out of the one Opravovatel place the room has.
ONLY_OPRAVOVATEL = {role: Preference.Ne for role in Role if role not in (Role.Opravovatel, Role.Zaloha)}


def _helper(helper_id, order=None, opravovatel=Preference.Ano, **extra):
    return Helper(
        id=helper_id,
        name=f"H{helper_id}",
        role_preferences={**ONLY_OPRAVOVATEL, Role.Opravovatel: opravovatel},
        registration_order=helper_id if order is None else order,
        **extra,
    )


def _solve(helpers, late_zaloha=2, opravovatel_places=1):
    room = Room(name="R", capacities={Role.Opravovatel: RoleCapacity(minimum=opravovatel_places)})
    comp = Competition(buildings={"B": Building(name="B", rooms=[room])}, helpers=helpers)
    config = SolverConfig(weights=SolverWeights(late_zaloha=late_zaloha), time_limit_seconds=30)
    return solve_competition(comp, config)


def _roles(result):
    return {a.helper_id: a.role for a in result.assignments}


def test_the_later_registrant_takes_zaloha():
    roles = _roles(_solve([_helper(1), _helper(2)]))
    assert roles == {1: Role.Opravovatel, 2: Role.Zaloha}


def test_the_order_decides_not_the_id():
    roles = _roles(_solve([_helper(1, order=2), _helper(2, order=1)]))
    assert roles == {1: Role.Zaloha, 2: Role.Opravovatel}


def test_equal_orders_fall_back_to_the_id():
    roles = _roles(_solve([_helper(1, order=0), _helper(2, order=0)]))
    assert roles == {1: Role.Opravovatel, 2: Role.Zaloha}


def test_the_surcharge_falls_from_the_full_weight_to_nothing():
    # One Ano each (k = 1), so Záloha costs 4 * 2 = 8; the later of two pays no
    # surcharge, the earlier would have paid the whole weight (2).
    assert _solve([_helper(1), _helper(2)]).objective_value == 8
    assert _solve([_helper(1), _helper(2)], late_zaloha=0).objective_value == 8
    earlier_in_zaloha = _solve([_helper(1, opravovatel=Preference.Ne), _helper(2)])
    assert _roles(earlier_in_zaloha)[1] is Role.Zaloha  # a real preference still decides
    assert earlier_in_zaloha.objective_value == 4 + 2  # Záloha 4 plus the full surcharge


def test_a_small_preference_difference_yields_to_the_order_and_a_big_one_does_not():
    # The earlier Helper is Nevadí about Opravovatel (2), the later one Klidně (1).
    # Preference alone puts the later one there (1 + 4 = 5 against 2 + 4 = 6);
    # with the weight on, the earlier one in Záloha would pay 2 more (7), so the
    # order wins (2 + 4 = 6).
    small_gap = [_helper(1, opravovatel=Preference.Nevadi), _helper(2, opravovatel=Preference.Klidne)]
    assert _roles(_solve(small_gap, late_zaloha=2)) == {1: Role.Opravovatel, 2: Role.Zaloha}
    assert _roles(_solve(small_gap, late_zaloha=0)) == {1: Role.Zaloha, 2: Role.Opravovatel}
    # An "Ano" against a Nevadí is worth more than the whole weight.
    big_gap = [_helper(1, opravovatel=Preference.Nevadi), _helper(2, opravovatel=Preference.Ano)]
    assert _roles(_solve(big_gap, late_zaloha=2)) == {1: Role.Zaloha, 2: Role.Opravovatel}


def test_a_helper_who_cannot_attend_is_left_out_of_the_ranking():
    helpers = [_helper(1), _helper(2), _helper(3, cant_attend=True)]
    # Ranked among the two who attend, the later of them still pays nothing.
    assert _solve(helpers).objective_value == 8


def test_neighbouring_ranks_stay_apart_for_a_large_season():
    helpers = [_helper(i) for i in range(1, 201)]
    roles = _roles(_solve(helpers, late_zaloha=1, opravovatel_places=100))
    assert {i for i, role in roles.items() if role is Role.Opravovatel} == set(range(1, 101))


def test_the_weight_is_saved_and_an_older_config_gets_the_default():
    saved = solver_config_to_dict(SolverConfig(weights=SolverWeights(late_zaloha=5)))
    assert saved["weights"]["late_zaloha"] == 5
    assert solver_config_from_dict(saved).weights.late_zaloha == 5
    older = {"weights": {"building_mismatch": 3}}
    assert solver_config_from_dict(older).weights.late_zaloha == SolverWeights().late_zaloha == 2


# -- keeping the order up ----------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    return Workspace(root=tmp_path / "seasons")


def _orders(state):
    return {h["name"]: h["registration_order"] for h in state["helpers"]}


def test_a_record_saved_before_the_order_existed_takes_it_from_the_id():
    record = {"id": 7, "name": "Old", "registration_order": None}
    assert helper_from_dict(record).registration_order == 7
    assert helper_from_dict({"id": 7, "name": "Old"}).registration_order == 7
    assert helper_from_dict({"id": 7, "name": "New", "registration_order": 3}).registration_order == 3


def test_the_first_upload_numbers_the_helpers_in_export_order(workspace):
    state = _upload(workspace, _row("Anna", ANNA), _row("Petr", PETR), label="2026-jaro")
    assert _orders(state) == {"Anna": 1, "Petr": 2}


def test_a_new_registrant_on_re_upload_registers_after_everyone(workspace):
    _upload(workspace, _row("Anna", ANNA), _row("Petr", PETR), label="2026-jaro")
    state = _upload(
        workspace,
        _row("Nova", "nova@example.test"),
        _row("Petr", PETR),
        _row("Nejnovejsi", "nejnovejsi@example.test"),
        _row("Anna", ANNA),
    )
    assert _orders(state) == {"Anna": 1, "Petr": 2, "Nova": 3, "Nejnovejsi": 4}


def test_a_helper_added_by_hand_registers_last(workspace):
    _upload(workspace, _row("Anna", ANNA), _row("Petr", PETR), label="2026-jaro")
    state = mutations.add_helper(workspace, "Ručně", "rucne@example.test")
    assert _named(state, "Ručně")["registration_order"] == 3


def test_a_resubmission_keeps_the_first_submissions_place(workspace):
    from datetime import datetime

    state = _upload(
        workspace,
        _row("Anna", ANNA, when=datetime(2026, 2, 1)),
        _row("Petr", PETR, when=datetime(2026, 2, 2)),
        _row("Anna (oprava)", ANNA.upper(), when=datetime(2026, 2, 3)),
        label="2026-jaro",
    )
    assert _orders(state) == {"Anna (oprava)": 1, "Petr": 2}
