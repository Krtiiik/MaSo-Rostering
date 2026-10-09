"""Friend preferences toward Organizers, and promoting a Helper to Organizer (see
CONTEXT.md "Friend preference", "Organizer"). A Helper's friend reference is one
unified reference that resolves to a Helper (a plain id) or an Organizer
(``{"organizer_id": n}`` in a saved state, an ``OrganizerRef`` on the domain
objects). Mutation-layer tests run against a temp-dir workspace seeded with
synthetic data (never anything from data/); the solver is exercised on plain
domain objects."""
import importlib
from datetime import datetime

import pandas as pd
import pytest

from rostering.domain import (
    Building,
    Competition,
    Helper,
    Organizer,
    OrganizerRef,
    Role,
    RoleCapacity,
    Room,
)
from rostering.ingest.raw_survey import parse_raw_survey
from rostering.persistence.serialize import helper_from_dict, helper_to_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.model import SolverConfig, solve_competition
from rostering.solver.scoring import FriendScoringConfig, FriendScoringMode, build_organizer_requests
from rostering.webapp import mutations

# -- scoring ------------------------------------------------------------------------


def test_a_request_toward_an_organizer_scores_at_the_friend_weight():
    helpers = [Helper(id=1, name="A", friends=[OrganizerRef(7)]), Helper(id=2, name="B", friends=[2, 1])]
    organizers = [Organizer(id=7, name="Marie")]

    requests = build_organizer_requests(helpers, organizers, FriendScoringConfig(weight=3))

    assert requests == [(1, 7, 3)]


def test_a_request_toward_an_unknown_organizer_is_ignored():
    helpers = [Helper(id=1, name="A", friends=[OrganizerRef(99)])]

    assert build_organizer_requests(helpers, [Organizer(id=7, name="Marie")], FriendScoringConfig()) == []


def test_under_mutual_mode_a_request_toward_an_organizer_never_counts():
    helpers = [Helper(id=1, name="A", friends=[OrganizerRef(7)])]
    organizers = [Organizer(id=7, name="Marie")]

    mutual = FriendScoringConfig(mode=FriendScoringMode.MUTUAL)

    assert build_organizer_requests(helpers, organizers, mutual) == []


# -- serialization --------------------------------------------------------------------


def test_a_friend_reference_round_trips_and_a_helper_reference_stays_a_plain_id():
    helper = Helper(id=1, name="A", friends=[2, OrganizerRef(7)])

    data = helper_to_dict(helper)

    assert data["friends"] == [2, {"organizer_id": 7}]
    assert helper_from_dict(data).friends == [2, OrganizerRef(7)]


# -- the solver ----------------------------------------------------------------------


def _room(name):
    return Room(name=name, capacities={Role.Zaloha: RoleCapacity(0)})


def _two_buildings():
    return {
        "B": Building(name="B", rooms=[_room("R1"), _room("R2")]),
        "C": Building(name="C", rooms=[_room("R3")]),
    }


def _solve(helpers, organizers, config=None, **kwargs):
    comp = Competition(buildings=_two_buildings(), helpers=helpers, organizers=organizers)
    return solve_competition(comp, config or SolverConfig(time_limit_seconds=10), **kwargs)


def _where(result, helper_id):
    a = next(a for a in result.assignments if a.helper_id == helper_id)
    return a.building, a.room


def test_an_organizer_placed_in_a_room_attracts_a_helper_who_named_them():
    helper = Helper(id=1, name="A", friends=[OrganizerRef(1)])

    for room, building in (("R1", "B"), ("R2", "B"), ("R3", "C")):
        result = _solve([helper], [Organizer(id=1, name="Marie", building=building, room=room)])
        assert _where(result, 1) == (building, room)


def test_an_organizer_placed_only_at_building_level_attracts_by_building():
    helper = Helper(id=1, name="A", friends=[OrganizerRef(1)])

    for building in ("B", "C"):
        result = _solve([helper], [Organizer(id=1, name="Marie", building=building)])
        assert _where(result, 1)[0] == building


def test_an_unplaced_organizer_attracts_nobody():
    # The Helper would rather be in B; an unplaced Organizer cannot pull them away.
    helper = Helper(id=1, name="A", building_preferences=frozenset({"B"}), friends=[OrganizerRef(1)])

    result = _solve([helper], [Organizer(id=1, name="Marie")])

    assert _where(result, 1)[0] == "B"


def test_a_request_toward_an_organizer_outweighs_a_building_preference_like_a_helper_request_does():
    # Weights: an unsatisfied friend request (5) outweighs one Building mismatch (3).
    helper = Helper(id=1, name="A", building_preferences=frozenset({"B"}), friends=[OrganizerRef(1)])

    result = _solve([helper], [Organizer(id=1, name="Marie", building="C", room="R3")])

    assert _where(result, 1) == ("C", "R3")


def test_under_mutual_mode_an_organizer_attracts_nobody():
    helper = Helper(id=1, name="A", building_preferences=frozenset({"B"}), friends=[OrganizerRef(1)])
    config = SolverConfig(time_limit_seconds=10, friend_scoring=FriendScoringConfig(mode=FriendScoringMode.MUTUAL))

    result = _solve([helper], [Organizer(id=1, name="Marie", building="C", room="R3")], config)

    assert _where(result, 1)[0] == "B"


def test_a_room_placed_organizer_is_not_matched_by_the_same_room_name_in_another_building():
    buildings = {
        "B": Building(name="B", rooms=[_room("R1")]),
        "C": Building(name="C", rooms=[_room("R1")]),
    }
    helper = Helper(id=1, name="A", building_preferences=frozenset({"B"}), friends=[OrganizerRef(1)])
    comp = Competition(
        buildings=buildings, helpers=[helper], organizers=[Organizer(id=1, name="Marie", building="C", room="R1")]
    )

    result = solve_competition(comp, SolverConfig(time_limit_seconds=10))

    assert _where(result, 1) == ("C", "R1")


def test_a_request_toward_an_organizer_weighs_the_same_as_one_toward_a_helper():
    from rostering.domain import Assignment

    pinned = lambda hid, room: Assignment(hid, "x", "B", room, Role.Zaloha)  # noqa: E731

    # Helper 1 pinned to R2 names Organizer 1 placed in R1 (unsatisfied) ...
    with_organizer = _solve(
        [Helper(id=1, name="A", friends=[OrganizerRef(1)])],
        [Organizer(id=1, name="Marie", building="B", room="R1")],
        fixed_assignments=[pinned(1, "R2")],
    )
    without_organizer = _solve(
        [Helper(id=1, name="A")], [Organizer(id=1, name="Marie", building="B", room="R1")],
        fixed_assignments=[pinned(1, "R2")],
    )
    # ... versus naming a Helper pinned to R1 (unsatisfied).
    with_helper = _solve(
        [Helper(id=1, name="A", friends=[2]), Helper(id=2, name="M")], [],
        fixed_assignments=[pinned(1, "R2"), pinned(2, "R1")],
    )
    without_helper = _solve(
        [Helper(id=1, name="A"), Helper(id=2, name="M")], [],
        fixed_assignments=[pinned(1, "R2"), pinned(2, "R1")],
    )

    organizer_cost = with_organizer.objective_value - without_organizer.objective_value
    helper_cost = with_helper.objective_value - without_helper.objective_value
    assert organizer_cost == helper_cost > 0


def test_an_organizer_never_moves_when_helpers_are_solved():
    organizer = Organizer(id=1, name="Marie", building="C", room="R3")
    helpers = [Helper(id=i, name=f"H{i}", friends=[OrganizerRef(1)]) for i in (1, 2, 3)]

    _solve(helpers, [organizer])

    assert (organizer.building, organizer.room) == ("C", "R3")


# -- ingestion --------------------------------------------------------------------------

_NAME_HEADER = "Tvoje jméno a příjmení"
_EMAIL_HEADER = "E-mailová adresa"
_FRIENDS_HEADER = "Chtěl/a bys být v místnosti s někým konkrétním?"


def _survey_file(tmp_path, rows):
    """A survey export; ``rows`` are (name, e-mail, friends answer)."""
    path = tmp_path / "survey.xlsx"
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 2, 1)] * len(rows),
            _NAME_HEADER: [r[0] for r in rows],
            _EMAIL_HEADER: [r[1] for r in rows],
            _FRIENDS_HEADER: [r[2] for r in rows],
        }
    ).to_excel(path, index=False)
    return path


def test_ingestion_resolves_a_friend_name_to_an_organizer(tmp_path):
    path = _survey_file(
        tmp_path,
        [("Anna Nováková", "anna@example.test", "Marie Vedoucí"), ("Petr Svoboda", "petr@example.test", None)],
    )

    result = parse_raw_survey(path, organizers=[Organizer(id=4, name="Marie Vedoucí")])

    assert result.helpers[0].friends == [OrganizerRef(4)]
    assert result.helpers[0].unresolved_friend_names == []


def test_ingestion_matches_organizer_names_with_the_same_normalized_fuzzy_matching(tmp_path):
    path = _survey_file(
        tmp_path,
        [
            ("Anna", "anna@example.test", "marie vedouci"),  # case and diacritics
            ("Petr", "petr@example.test", "Jaroslva Karlik"),  # typo, fuzzy
            ("Jana", "jana@example.test", "Verča"),  # first name, unambiguous among Organizers
        ],
    )
    organizers = [
        Organizer(id=4, name="Marie Vedoucí"),
        Organizer(id=5, name="Jaroslav Karlík"),
        Organizer(id=6, name="Verča Nová"),
    ]

    result = parse_raw_survey(path, organizers=organizers)

    assert [h.friends for h in result.helpers] == [[OrganizerRef(4)], [OrganizerRef(5)], [OrganizerRef(6)]]


def test_ingestion_still_surfaces_a_name_that_matches_nobody_as_unresolved(tmp_path):
    path = _survey_file(tmp_path, [("Anna", "anna@example.test", "Marie Vedoucí, Nikdo Neznámý")])

    result = parse_raw_survey(path, organizers=[Organizer(id=4, name="Marie Vedoucí")])

    assert result.helpers[0].friends == [OrganizerRef(4)]
    assert result.helpers[0].unresolved_friend_names == ["Nikdo Neznámý"]


def test_a_name_both_a_helper_and_an_organizer_carry_resolves_to_the_helper(tmp_path):
    path = _survey_file(
        tmp_path, [("Anna", "anna@example.test", "Petr Svoboda"), ("Petr Svoboda", "petr@example.test", None)]
    )

    result = parse_raw_survey(path, organizers=[Organizer(id=4, name="Petr Svoboda")])

    assert result.helpers[0].friends == [2]


# -- the mutation layer ---------------------------------------------------------------------

CONFIG = [
    {
        "name": "B",
        "rooms": [
            {"name": "R1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "R2", "capacities": {"Zaloha": {"minimum": 0}}},
        ],
        "capacities": {},
    },
    {"name": "C", "rooms": [{"name": "R3", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}},
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
        "can_bring_notebook": False,
        "can_bring_camera": False,
        "unresolved_friend_names": [],
        "person_id": f"person-{helper_id}",
        **extra,
    }


def _seed(workspace: Workspace, *helpers: dict) -> None:
    state = workspace.load()
    state["helpers"] = list(helpers)
    workspace.save(state)
    mutations.put_config(workspace, CONFIG)


def _create(workspace, name, email=None) -> int:
    return mutations.add_organizer(workspace, name, email)["organizers"][-1]["id"]


def _helper_in(state, helper_id) -> dict:
    return next(h for h in state["helpers"] if h["id"] == helper_id)


def _placed(state, helper_id):
    a = next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)
    return (a["building"], a["room"]) if a else None


def test_a_helper_can_be_given_an_organizer_as_a_friend_and_the_solve_pulls_them_in(workspace):
    _seed(workspace, _helper(1, "Anna", building_preferences=["B"]))
    marie = _create(workspace, "Marie")
    mutations.assign_organizer(workspace, marie, "VedouciMistnosti", "C", "R3")

    state = mutations.update_helper(workspace, 1, friends=[{"organizer_id": marie}])
    assert _helper_in(state, 1)["friends"] == [{"organizer_id": marie}]

    state = mutations.solve(workspace)

    assert _placed(state, 1) == ("C", "R3")
    # The Organizer is where they were put, and is no solved Helper.
    assert (state["organizers"][0]["building"], state["organizers"][0]["room"]) == ("C", "R3")
    assert [a["helper_id"] for a in state["assignments"]] == [1]


def test_a_building_level_organizer_pulls_by_building_and_an_unplaced_one_pulls_nobody(workspace):
    _seed(workspace, _helper(1, "Anna", building_preferences=["B"]))
    marie = _create(workspace, "Marie")
    mutations.update_helper(workspace, 1, friends=[{"organizer_id": marie}])

    unplaced = mutations.solve(workspace)
    mutations.assign_organizer(workspace, marie, "VedouciBudovy", "C")
    at_building = mutations.solve(workspace)

    assert _placed(unplaced, 1)[0] == "B"
    assert _placed(at_building, 1)[0] == "C"


def test_a_friend_list_naming_an_unknown_organizer_is_refused(workspace):
    _seed(workspace, _helper(1, "Anna"))

    with pytest.raises(mutations.RosteringError):
        mutations.update_helper(workspace, 1, friends=[{"organizer_id": 42}])
    with pytest.raises(mutations.RosteringError):
        mutations.add_helper(workspace, "Nová", "nova@example.test", friends=[{"organizer_id": 42}])


def test_a_hand_added_helper_can_name_an_organizer(workspace):
    _seed(workspace, _helper(1, "Anna"))
    marie = _create(workspace, "Marie")

    state = mutations.add_helper(workspace, "Nová", "nova@example.test", friends=[1, {"organizer_id": marie}])

    assert state["helpers"][-1]["friends"] == [1, {"organizer_id": marie}]


def test_an_unresolved_friend_name_can_be_resolved_to_an_organizer(workspace):
    _seed(workspace, _helper(1, "Anna", unresolved_friend_names=["Marie"]), _helper(2, "Petr"))
    marie = _create(workspace, "Marie Vedoucí")

    state = mutations.resolve_friend(workspace, 1, "Marie", "resolve", [2], resolved_organizer_ids=[marie])

    helper = _helper_in(state, 1)
    assert helper["friends"] == [2, {"organizer_id": marie}]
    assert helper["unresolved_friend_names"] == []
    assert helper["friend_name_decisions"] == {"Marie": [2, {"organizer_id": marie}]}

    # Changing the decision takes the Organizer back out.
    state = mutations.resolve_friend(workspace, 1, "Marie", "resolve", [2])
    assert _helper_in(state, 1)["friends"] == [2]


def test_deleting_an_organizer_takes_them_out_of_friend_preferences(workspace):
    _seed(workspace, _helper(1, "Anna", unresolved_friend_names=["Marie"]))
    marie = _create(workspace, "Marie")
    mutations.resolve_friend(workspace, 1, "Marie", "resolve", [], resolved_organizer_ids=[marie])
    assert _helper_in(workspace.load(), 1)["friends"] == [{"organizer_id": marie}]

    state = mutations.delete_organizer(workspace, marie)

    helper = _helper_in(state, 1)
    assert helper["friends"] == []
    assert helper["unresolved_friend_names"] == ["Marie"]  # not silently dropped


def test_a_reupload_resolves_friend_names_against_the_seasons_organizers(workspace, tmp_path):
    mutations.new_season(workspace)
    path = _survey_file(tmp_path, [("Anna Nováková", "anna@example.test", "Marie Vedoucí")])
    mutations.upload_responses(workspace, path.read_bytes(), "s.xlsx", label="2026-jaro")
    marie = _create(workspace, "Marie Vedoucí")

    state = mutations.upload_responses(workspace, path.read_bytes(), "s.xlsx")

    assert state["helpers"][0]["friends"] == [{"organizer_id": marie}]
    assert state["helpers"][0]["unresolved_friend_names"] == []


def test_adding_an_organizer_resolves_the_friend_names_waiting_for_them(workspace):
    _seed(
        workspace,
        _helper(1, "Anna", unresolved_friend_names=["Marie Vedoucí", "Kdo ví"], friend_name_order=["Marie Vedoucí", "Kdo ví"]),
        _helper(2, "Petr"),
    )

    state = mutations.add_organizer(workspace, "Marie Vedoucí")

    marie = {"organizer_id": state["organizers"][-1]["id"]}
    anna = _helper_in(state, 1)
    assert anna["friends"] == [marie]
    assert anna["unresolved_friend_names"] == ["Kdo ví"]  # still surfaced, not dropped
    assert anna["friend_name_decisions"] == {"Marie Vedoucí": [marie]}
    assert "friend_name_decisions" not in _helper_in(state, 2)


def test_the_retry_uses_the_surveys_fuzzy_and_first_name_rules(workspace):
    _seed(workspace, _helper(1, "Anna", unresolved_friend_names=["Marja Vedouci", "Bohuslav"]))

    state = mutations.add_organizer(workspace, "Marie Vedoucí")
    assert _helper_in(state, 1)["unresolved_friend_names"] == ["Bohuslav"]

    state = mutations.add_organizer(workspace, "Bohuslav Dvořák")
    assert _helper_in(state, 1)["unresolved_friend_names"] == []
    assert len(_helper_in(state, 1)["friends"]) == 2


def test_the_retry_leaves_a_name_that_is_still_ambiguous_alone(workspace):
    _seed(workspace, _helper(1, "Anna", unresolved_friend_names=["Marie"]), _helper(2, "Marie Nová"))

    state = mutations.add_organizer(workspace, "Marie Vedoucí")

    assert _helper_in(state, 1)["unresolved_friend_names"] == ["Marie"]
    assert _helper_in(state, 1)["friends"] == []


def test_the_retry_never_makes_a_helper_their_own_friend(workspace):
    _seed(workspace, _helper(1, "Anna Nová", unresolved_friend_names=["Anna Nová"]))

    state = mutations.add_organizer(workspace, "Jiný Člověk")

    assert _helper_in(state, 1)["friends"] == []
    assert _helper_in(state, 1)["unresolved_friend_names"] == ["Anna Nová"]


def test_a_name_resolved_by_the_retry_returns_to_unresolved_when_the_organizer_is_deleted(workspace):
    _seed(workspace, _helper(1, "Anna", unresolved_friend_names=["Marie Vedoucí"]))
    marie = _create(workspace, "Marie Vedoucí")

    state = mutations.delete_organizer(workspace, marie)

    assert _helper_in(state, 1)["friends"] == []
    assert _helper_in(state, 1)["unresolved_friend_names"] == ["Marie Vedoucí"]


def test_the_retry_refreshes_the_friend_pairs_of_a_solved_roster(workspace):
    _seed(workspace, _helper(1, "Anna", unresolved_friend_names=["Marie Vedoucí"]))
    mutations.solve(workspace)

    state = mutations.add_organizer(workspace, "Marie Vedoucí")

    assert _helper_in(state, 1)["friends"] == [{"organizer_id": state["organizers"][-1]["id"]}]
    assert state["diagnostics"]["unsatisfied_friend_pairs"] == []  # an unplaced Organizer is no pair


def test_importing_the_organizers_sheet_resolves_waiting_friend_names(workspace, tmp_path):
    from tests.test_organizer_import import _sheet

    mutations.new_season(workspace)
    path = _survey_file(tmp_path, [("Anna Nováková", "anna@example.test", "Jan Novák")])
    state = mutations.upload_responses(workspace, path.read_bytes(), "s.xlsx", label="2026-jaro")
    assert state["helpers"][0]["unresolved_friend_names"] == ["Jan Novák"]

    state = mutations.import_organizers(workspace, _sheet({"name": "Jan Novák"}), "organizers.xlsx")

    assert state["helpers"][0]["friends"] == [{"organizer_id": state["organizers"][0]["id"]}]
    assert state["helpers"][0]["unresolved_friend_names"] == []


# -- promotion ------------------------------------------------------------------------------


def _solved_with_locked_helper(workspace):
    _seed(workspace, _helper(1, "Anna", email="anna@example.test"), _helper(2, "Petr"), _helper(3, "Jana"))
    mutations.solve(workspace)
    return mutations.set_lock(workspace, 1, True)


def test_promoting_a_helper_creates_an_organizer_keeping_person_name_email_and_tags(workspace):
    _seed(workspace, _helper(1, "Anna", email="anna@example.test"), _helper(2, "Petr"))
    tag = mutations.add_tag(workspace, "8.M")["tags"][-1]["id"]
    mutations.set_helper_tags(workspace, 1, [tag])

    state = mutations.promote_helper(workspace, 1)

    [organizer] = state["organizers"]
    assert (organizer["name"], organizer["email"], organizer["person_id"]) == (
        "Anna",
        "anna@example.test",
        "person-1",
    )
    assert organizer["tags"] == [tag]
    assert (organizer["building"], organizer["room"]) == (None, None)  # placed only by a slot


def test_promotion_removes_the_helper_from_the_pool_and_the_solve(workspace):
    _seed(workspace, _helper(1, "Anna"), _helper(2, "Petr"))

    state = mutations.promote_helper(workspace, 1)
    solved = mutations.solve(workspace)

    assert [h["id"] for h in state["helpers"]] == [2]
    assert [a["helper_id"] for a in solved["assignments"]] == [2]


def test_promotion_keeps_link_decisions_on_the_person(workspace):
    _seed(workspace, _helper(1, "Anna", link_confirmed=True, rejected_person_ids=["other"]))

    state = mutations.promote_helper(workspace, 1)

    assert state["organizers"][0]["link_confirmed"] is True
    assert state["organizers"][0]["rejected_person_ids"] == ["other"]


def test_promoting_a_placed_helper_asks_first_then_clears_assignment_and_lock(workspace):
    state = _solved_with_locked_helper(workspace)
    assert _placed(state, 1) is not None

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.promote_helper(workspace, 1)
    assert any("(uzamčeno)" in line for line in excinfo.value.lines)
    assert [h["id"] for h in workspace.load()["helpers"]] == [1, 2, 3]  # nothing changed

    state = mutations.promote_helper(workspace, 1, confirmed=True)

    assert _placed(state, 1) is None
    assert sorted(a["helper_id"] for a in state["assignments"]) == [2, 3]
    assert not any(a.get("locked") for a in state["assignments"] if a["helper_id"] == 1)
    assert mutations.stale_reasons(state)  # the roster no longer matches the Helpers


def test_promotion_clears_manual_role_entries_that_held_the_helper(workspace):
    _seed(workspace, _helper(1, "Anna"), _helper(2, "Petr"))
    mutations.solve(workspace)
    mutations.put_manual_roles(
        workspace,
        {
            "structural": [
                {"role": "VedouciBudovy", "building": "B", "room": None, "helper_id": 1, "helper_name": None}
            ],
            "overlay": [
                {"role": "Registrace", "building": "B", "room": None, "helper_id": 1, "helper_name": None},
                {"role": "Registrace", "building": "B", "room": None, "helper_id": 2, "helper_name": None},
            ],
        },
    )

    with pytest.raises(mutations.ConfirmationRequired):
        mutations.promote_helper(workspace, 1)
    state = mutations.promote_helper(workspace, 1, confirmed=True)

    assert state["manual_roles"]["structural"] == []
    assert [e["helper_id"] for e in state["manual_roles"]["overlay"]] == [2]


def test_promotion_repoints_other_helpers_friend_references_to_the_organizer(workspace):
    _seed(
        workspace,
        _helper(1, "Anna"),
        _helper(2, "Petr", friends=[1, 3], friend_name_decisions={"Ája": [1], "Jana": [3], "Nikdo": None}),
        _helper(3, "Jana", friends=[1]),
    )

    state = mutations.promote_helper(workspace, 1)

    organizer_id = state["organizers"][0]["id"]
    ref = {"organizer_id": organizer_id}
    assert _helper_in(state, 2)["friends"] == [ref, 3]
    assert _helper_in(state, 2)["friend_name_decisions"] == {"Ája": [ref], "Jana": [3], "Nikdo": None}
    assert _helper_in(state, 3)["friends"] == [ref]


def test_promotion_bumps_the_helper_id_high_water_mark_like_a_delete(workspace):
    _seed(workspace, _helper(1, "Anna"))

    state = mutations.promote_helper(workspace, 1)

    assert state["next_helper_id"] >= 2
    assert mutations.add_helper(workspace, "Nová", "n@example.test")["helpers"][-1]["id"] >= 2


def test_promoted_organizer_can_take_a_leadership_slot_and_be_named_by_others(workspace):
    _seed(workspace, _helper(1, "Anna"), _helper(2, "Petr", friends=[1], building_preferences=["B"]))
    state = mutations.promote_helper(workspace, 1)
    organizer_id = state["organizers"][0]["id"]

    mutations.assign_organizer(workspace, organizer_id, "VedouciMistnosti", "C", "R3")
    state = mutations.solve(workspace)

    assert _placed(state, 2) == ("C", "R3")


def test_promoting_an_unknown_helper_is_an_error(workspace):
    _seed(workspace, _helper(1, "Anna"))

    with pytest.raises(mutations.RosteringError):
        mutations.promote_helper(workspace, 99)


def test_promotion_is_part_of_versions(workspace, tmp_path):
    mutations.new_season(workspace)
    path = _survey_file(tmp_path, [("Anna", "anna@example.test", None), ("Petr", "petr@example.test", None)])
    mutations.upload_responses(workspace, path.read_bytes(), "s.xlsx", label="2026-jaro")
    saved = mutations.save_version(workspace, "before")
    mutations.promote_helper(workspace, 1)

    state = mutations.restore_version(workspace, saved["slug"])

    assert [h["name"] for h in state["helpers"]] == ["Anna", "Petr"]
    assert state["organizers"] == []


# -- demotion (Převést na pomocníka) ---------------------------------------------------------


def _organizer_state(workspace, *helpers, name="Marie", email="marie@example.test"):
    _seed(workspace, *helpers)
    return _create(workspace, name, email)


def test_demoting_an_organizer_creates_a_helper_keeping_person_name_contact_and_tags(workspace):
    marie = _organizer_state(workspace, _helper(2, "Petr"))
    tag = mutations.add_tag(workspace, "8.M")["tags"][-1]["id"]
    mutations.set_organizer_tags(workspace, marie, [tag])
    mutations.update_organizer(workspace, marie, phone="777 111 222", tshirt_size="M")
    person_id = workspace.load()["organizers"][0]["person_id"]

    state = mutations.demote_organizer(workspace, marie)

    assert state["organizers"] == []
    helper = state["helpers"][-1]
    assert (helper["name"], helper["email"], helper["phone"], helper["tshirt_size"]) == (
        "Marie",
        "marie@example.test",
        "777 111 222",
        "M",
    )
    assert helper["person_id"] == person_id
    assert helper["tags"] == [tag]
    assert helper["hand_added"] is True
    assert {"name", "email", "phone", "tshirt_size"} <= set(helper["hand_typed"])
    assert helper["id"] not in (2,)
    assert not state["assignments"]


def test_demotion_keeps_link_decisions_and_the_absence_flag(workspace):
    marie = _organizer_state(workspace)
    state = workspace.load()
    record = state["organizers"][0]
    record.update(link_confirmed=True, rejected_person_ids=["other"], cant_attend=True)
    workspace.save(state)

    helper = mutations.demote_organizer(workspace, marie)["helpers"][-1]

    assert helper["link_confirmed"] is True
    assert helper["rejected_person_ids"] == ["other"]
    assert helper["cant_attend"] is True


def test_demotion_puts_the_helper_in_the_solver_pool(workspace):
    marie = _organizer_state(workspace, _helper(2, "Petr"))

    mutations.demote_organizer(workspace, marie)
    solved = mutations.solve(workspace)

    assert sorted(a["helper_name"] for a in solved["assignments"]) == ["Marie", "Petr"]


def test_demoting_an_organizer_with_a_slot_asks_first_then_empties_it_and_stales_the_roster(workspace):
    marie = _organizer_state(workspace, _helper(2, "Petr"))
    mutations.assign_organizer(workspace, marie, "VedouciBudovy", "B", None)

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.demote_organizer(workspace, marie)
    assert any("Vedoucí budovy" in line for line in excinfo.value.lines)
    assert [o["id"] for o in workspace.load()["organizers"]] == [marie]  # nothing changed

    state = mutations.demote_organizer(workspace, marie, confirmed=True)

    assert state["manual_roles"]["structural"] == []
    assert mutations.stale_reasons(state)


def test_demoting_an_unplaced_organizer_needs_no_confirmation_and_keeps_the_roster_current(workspace):
    marie = _organizer_state(workspace, _helper(2, "Petr"))
    mutations.solve(workspace)

    state = mutations.demote_organizer(workspace, marie)

    assert not mutations.stale_reasons(state)
    # The newcomer has no Assignment, so the export waits until they are placed.
    assert mutations.unplaced_reason(state)
    assert _placed(mutations.place_new_registrants(workspace), state["helpers"][-1]["id"]) is not None


def test_demotion_repoints_friend_references_to_the_new_helper(workspace):
    marie = _organizer_state(workspace)
    ref = {"organizer_id": marie}
    state = workspace.load()
    state["helpers"] = [
        _helper(2, "Petr", friends=[ref, 3], friend_name_decisions={"Maruška": [ref], "Jana": [3], "Nikdo": None}),
        _helper(3, "Jana", friends=[ref]),
    ]
    workspace.save(state)

    state = mutations.demote_organizer(workspace, marie)

    new_id = state["helpers"][-1]["id"]
    assert _helper_in(state, 2)["friends"] == [new_id, 3]
    assert _helper_in(state, 2)["friend_name_decisions"] == {"Maruška": [new_id], "Jana": [3], "Nikdo": None}
    assert _helper_in(state, 3)["friends"] == [new_id]


def test_demotion_bumps_the_organizer_id_high_water_mark(workspace):
    marie = _organizer_state(workspace)

    state = mutations.demote_organizer(workspace, marie)

    assert state["next_organizer_id"] > marie
    assert mutations.add_organizer(workspace, "Nová")["organizers"][-1]["id"] > marie


def test_a_tag_that_would_strand_the_new_helper_is_named_in_the_confirmation_and_not_carried(workspace):
    marie = _organizer_state(workspace)
    must = lambda role: [{"kind": "be", "must": True, "axis": "role", "values": [role]}]  # noqa: E731
    first = mutations.add_tag(workspace, "Jen oprava", rules=must("Opravovatel"))["tags"][-1]["id"]
    second = mutations.add_tag(workspace, "Jen foto", rules=must("Fotograf"))["tags"][-1]["id"]
    mutations.set_organizer_tags(workspace, marie, [first, second])  # an Organizer is judged on Buildings only

    with pytest.raises(mutations.ConfirmationRequired) as excinfo:
        mutations.demote_organizer(workspace, marie)
    assert any("Jen foto" in line for line in excinfo.value.lines)

    state = mutations.demote_organizer(workspace, marie, confirmed=True)

    assert state["helpers"][-1]["tags"] == [first]
    assert not mutations.stale_reasons(state)  # no slot was emptied


def test_a_person_who_is_already_a_helper_cannot_be_demoted_into_a_second_record(workspace):
    marie = _organizer_state(workspace, _helper(2, "Marie"))
    state = workspace.load()
    state["helpers"][0]["person_id"] = state["organizers"][0]["person_id"]
    workspace.save(state)

    with pytest.raises(mutations.RosteringError):
        mutations.demote_organizer(workspace, marie)
    assert len(workspace.load()["organizers"]) == 1


def test_demoting_an_unknown_organizer_is_an_error(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError):
        mutations.demote_organizer(workspace, 99)


def test_a_promoted_helper_can_be_demoted_back_and_keeps_their_person(workspace):
    _seed(workspace, _helper(1, "Anna", email="anna@example.test"), _helper(2, "Petr", friends=[1]))
    organizer = mutations.promote_helper(workspace, 1)["organizers"][0]

    state = mutations.demote_organizer(workspace, organizer["id"])

    back = state["helpers"][-1]
    assert (back["name"], back["person_id"], back["email"]) == ("Anna", organizer["person_id"], "anna@example.test")
    assert _helper_in(state, 2)["friends"] == [back["id"]]


def test_demotion_is_part_of_versions(workspace, tmp_path):
    mutations.new_season(workspace)
    path = _survey_file(tmp_path, [("Petr", "petr@example.test", None)])
    mutations.upload_responses(workspace, path.read_bytes(), "s.xlsx", label="2026-jaro")
    marie = _create(workspace, "Marie")
    saved = mutations.save_version(workspace, "before")
    mutations.demote_organizer(workspace, marie)

    state = mutations.restore_version(workspace, saved["slug"])

    assert [o["name"] for o in state["organizers"]] == ["Marie"]
    assert [h["name"] for h in state["helpers"]] == ["Petr"]
