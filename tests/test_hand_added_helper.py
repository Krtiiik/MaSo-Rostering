"""Adding, editing and deleting a Helper by hand (see CONTEXT.md "Hand-added
Helper"). Mutation-layer tests run against a temp-dir workspace seeded with
synthetic Helpers and Seasons (never anything from data/); the solver is also
exercised on plain domain objects."""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.domain import Building, Competition, Helper, Role, RoleCapacity, Room
from rostering.persistence.serialize import helper_from_dict
from rostering.persistence.workspace import Workspace
from rostering.solver.model import SolverConfig, solve_competition
from rostering.streamlit_app import mutations

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


def _helper(helper_id: int, name: str, friends=(), **extra) -> dict:
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": list(friends),
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
        **extra,
    }


def _seed(workspace: Workspace, helpers=None) -> None:
    state = workspace.load()
    state["helpers"] = helpers or [_helper(1, "Anna"), _helper(2, "Petr"), _helper(3, "Jana")]
    workspace.save(state)
    mutations.put_config(workspace, CONFIG)


def _record(state, helper_id):
    return next(h for h in state["helpers"] if h["id"] == helper_id)


def _added(state) -> dict:
    """The Helper the last add appended."""
    return state["helpers"][-1]


def _survey(rows) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 2, 1)] * len(rows),
            "Tvoje jméno a příjmení": [name for name, _ in rows],
            "E-mailová adresa": [email for _, email in rows],
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


# -- adding: required fields and contact ---------------------------------------------


def test_adding_with_only_name_and_contact_gives_the_blank_survey_defaults(workspace):
    _seed(workspace)

    state = mutations.add_helper(workspace, "Eva Nová", "eva@example.test")

    added = _added(state)
    assert added["name"] == "Eva Nová"
    assert added["role_preferences"] == {}  # every Role reads as Nevadí
    assert added["building_preferences"] == []
    assert added["can_bring_notebook"] is False
    assert added["can_bring_camera"] is False
    assert added["friends"] == []
    assert added["unresolved_friend_names"] == []
    assert added["tshirt_size"] == "Unknown"
    assert added.get("cant_attend", False) is False
    assert _added(mutations.get_state(workspace)) == added  # persisted


def test_an_email_shaped_contact_is_stored_normalized_as_the_email(workspace):
    _seed(workspace)

    added = _added(mutations.add_helper(workspace, "Eva", "  Eva.Nova@Example.TEST "))

    assert added["email"] == "eva.nova@example.test"
    assert added["phone"] is None


def test_any_other_contact_is_kept_as_a_display_contact_and_is_no_email(workspace):
    _seed(workspace)

    added = _added(mutations.add_helper(workspace, "Eva", " +420 777 123 456 "))

    assert added["email"] is None
    assert added["phone"] == "+420 777 123 456"


def test_a_blank_name_is_rejected_and_nothing_changes(workspace):
    _seed(workspace)
    before = mutations.get_state(workspace)

    for name in ("", "   "):
        with pytest.raises(mutations.RosteringError, match="name"):
            mutations.add_helper(workspace, name, "eva@example.test")

    assert mutations.get_state(workspace) == before


def test_a_blank_contact_is_rejected(workspace):
    _seed(workspace)
    before = mutations.get_state(workspace)

    with pytest.raises(mutations.RosteringError, match="contact"):
        mutations.add_helper(workspace, "Eva", "  ")

    assert mutations.get_state(workspace) == before


def test_a_name_or_email_colliding_with_a_helper_of_the_season_warns_without_blocking(workspace):
    _seed(workspace, [_helper(1, "Anna Nováková", email="anna@example.test"), _helper(2, "Petr")])

    by_name = mutations.helper_collisions(mutations.get_state(workspace), "  anna  NOVAKOVA", "111 222 333")
    by_email = mutations.helper_collisions(mutations.get_state(workspace), "Somebody Else", "ANNA@example.test")
    clean = mutations.helper_collisions(mutations.get_state(workspace), "Eva", "eva@example.test")

    assert len(by_name) == 1 and "Anna Nováková" in by_name[0]
    assert len(by_email) == 1 and "Anna Nováková" in by_email[0]
    assert clean == []
    # A warning only: adding the same person again still works.
    state = mutations.add_helper(workspace, "Anna Nováková", "anna@example.test")
    assert [h["name"] for h in state["helpers"]].count("Anna Nováková") == 2


def test_collisions_ignore_the_helper_being_edited(workspace):
    _seed(workspace, [_helper(1, "Anna", email="anna@example.test"), _helper(2, "Petr")])
    state = mutations.get_state(workspace)

    assert mutations.helper_collisions(state, "Anna", "anna@example.test", exclude_helper_id=1) == []
    assert mutations.helper_collisions(state, "Anna", "anna@example.test", exclude_helper_id=2) != []


# -- adding: optional fields and identity --------------------------------------------


def test_optional_fields_can_be_filled_at_creation(workspace):
    _seed(workspace)

    state = mutations.add_helper(
        workspace,
        "Eva",
        "eva@example.test",
        role_preferences={"Fotograf": "Ano", "Skenovac": "Ne"},
        building_preferences=["C"],
        can_bring_notebook=True,
        can_bring_camera=True,
        friends=[1, 3],
        tshirt_size=" m ",
    )

    added = _added(state)
    assert added["role_preferences"] == {"Fotograf": "Ano", "Skenovac": "Ne"}
    assert added["building_preferences"] == ["C"]
    assert added["can_bring_notebook"] is True and added["can_bring_camera"] is True
    assert added["friends"] == [1, 3]
    assert added["tshirt_size"] == "M"


@pytest.mark.parametrize(
    "bad",
    [
        {"role_preferences": {"Nonsense": "Ano"}},
        {"role_preferences": {"Fotograf": "Maybe"}},
        {"building_preferences": ["Nowhere"]},
        {"friends": [99]},
        {"tshirt_size": "XXXL"},
    ],
)
def test_invalid_optional_fields_are_rejected_and_nothing_changes(workspace, bad):
    _seed(workspace)
    before = mutations.get_state(workspace)

    with pytest.raises(mutations.RosteringError):
        mutations.add_helper(workspace, "Eva", "eva@example.test", **bad)

    assert mutations.get_state(workspace) == before


def test_the_unknown_size_may_be_given_explicitly(workspace):
    _seed(workspace)

    assert _added(mutations.add_helper(workspace, "Eva", "e@x.test", tshirt_size="unknown"))["tshirt_size"] == "Unknown"


def test_a_new_helper_gets_a_fresh_id_and_a_fresh_person_link(workspace):
    _seed(workspace, [_helper(1, "Anna", person_id="p-anna"), _helper(7, "Petr", person_id="p-petr")])

    first = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))
    second = _added(mutations.add_helper(workspace, "Jitka", "jitka@example.test"))

    assert first["id"] not in (1, 7) and second["id"] not in (1, 7, first["id"])
    assert first["person_id"] and second["person_id"]
    assert len({first["person_id"], second["person_id"], "p-anna", "p-petr"}) == 4


def test_a_deleted_helpers_id_is_never_handed_out_again(workspace):
    _seed(workspace)
    first = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))["id"]
    mutations.delete_helper(workspace, first)

    again = _added(mutations.add_helper(workspace, "Jitka", "jitka@example.test"))["id"]

    assert again != first


def test_the_id_of_a_deleted_survey_helper_is_not_reused_either(workspace):
    _seed(workspace)  # ids 1..3
    mutations.delete_helper(workspace, 3)

    assert _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))["id"] > 3


def test_an_email_known_from_an_earlier_season_links_to_that_person(workspace):
    mutations.new_season(workspace)
    earlier = mutations.upload_responses(workspace, _survey([("Anna Nováková", "anna@example.test")]), "s.xlsx", "2025-podzim")
    mutations.new_season(workspace)
    mutations.upload_responses(workspace, _survey([("Petr", "petr@example.test")]), "s.xlsx", "2026-jaro")

    added = _added(mutations.add_helper(workspace, "A. Nováková", " Anna@Example.test "))
    stranger = _added(mutations.add_helper(workspace, "Nobody", "nobody@example.test"))

    assert added["person_id"] == earlier["helpers"][0]["person_id"]
    assert stranger["person_id"] not in {added["person_id"], earlier["helpers"][0]["person_id"]}
    assert mutations.get_returning_helpers(workspace) == {added["id"]: ["2025-podzim"]}


def test_a_duplicate_email_within_the_season_does_not_merge_the_two_helpers(workspace):
    mutations.new_season(workspace)
    state = mutations.upload_responses(workspace, _survey([("Anna", "anna@example.test")]), "s.xlsx", "2026-jaro")

    added = _added(mutations.add_helper(workspace, "Anna again", "anna@example.test"))

    assert added["person_id"] != state["helpers"][0]["person_id"]


def test_the_record_remembers_which_fields_were_typed_by_hand(workspace):
    _seed(workspace)

    bare = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))
    rich = _added(
        mutations.add_helper(
            workspace, "Jitka", "+420 111", building_preferences=["B"], can_bring_camera=True, tshirt_size="L"
        )
    )

    assert bare["hand_added"] is True
    assert set(bare["hand_typed"]) == {"name", "email"}
    assert set(rich["hand_typed"]) == {"name", "phone", "building_preferences", "can_bring_camera", "tshirt_size"}
    assert "hand_added" not in _record(mutations.get_state(workspace), 1)  # a survey Helper is not hand-added


# -- a hand-added Helper is an ordinary Helper ----------------------------------------


def test_a_hand_added_helper_is_solved_like_any_helper(workspace):
    _seed(workspace)
    added_id = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))["id"]

    state = mutations.solve(workspace)

    assert sorted(a["helper_id"] for a in state["assignments"]) == sorted([1, 2, 3, added_id])


def test_a_hand_added_helper_takes_part_in_friend_preferences_and_can_attend_flag(workspace):
    _seed(workspace, [_helper(1, "Anna"), _helper(2, "Petr"), _helper(3, "Jana")])
    added_id = _added(mutations.add_helper(workspace, "Eva", "eva@example.test", friends=[1]))["id"]
    mutations.update_helper(workspace, 3, friends=[added_id])  # a survey Helper naming them back

    solved = mutations.solve(workspace)
    rooms = {a["helper_id"]: (a["building"], a["room"]) for a in solved["assignments"]}
    assert rooms[added_id] == rooms[1] == rooms[3]  # both directions score, so all three share a Room

    flagged = mutations.set_cant_attend(workspace, added_id, True, confirmed=True)
    assert _record(flagged, added_id)["cant_attend"] is True
    assert added_id not in [a["helper_id"] for a in mutations.solve(workspace)["assignments"]]


def test_a_hand_added_record_round_trips_through_the_domain_model(workspace):
    _seed(workspace)
    added = _added(
        mutations.add_helper(workspace, "Eva", "eva@example.test", role_preferences={"Fotograf": "Ano"}, tshirt_size="S")
    )

    helper = helper_from_dict(added)

    assert helper.name == "Eva" and helper.email == "eva@example.test" and helper.tshirt_size == "S"
    assert helper.role_preferences == {Role.Fotograf: helper.role_preferences[Role.Fotograf]}


def test_a_helper_with_blank_preferences_gets_no_role_bias():
    config = SolverConfig()
    rooms = {"B": Building("B", [Room("R1", {Role.Zaloha: RoleCapacity(0)})])}
    blank = Helper(id=1, name="Blank")

    result = solve_competition(Competition(rooms, [blank]), config)

    assert result.objective_value == 0
    assert len(result.assignments) == 1


# -- editing --------------------------------------------------------------------------


def test_every_field_of_a_helper_can_be_edited_at_any_time(workspace):
    _seed(workspace, [_helper(1, "Anna", person_id="p-anna"), _helper(2, "Petr"), _helper(3, "Jana")])
    person_id = "p-anna"
    mutations.solve(workspace)

    state = mutations.update_helper(
        workspace,
        1,
        name="Anna Nová",
        email=" Anna.Nova@Example.test ",
        phone="777 000 111",
        role_preferences={"Opravovatel": "Klidne"},
        building_preferences=["C"],
        can_bring_notebook=False,
        can_bring_camera=False,
        friends=[2],
        tshirt_size="XL",
    )

    edited = _record(state, 1)
    assert edited["name"] == "Anna Nová"
    assert edited["email"] == "anna.nova@example.test"
    assert edited["phone"] == "777 000 111"
    assert edited["role_preferences"] == {"Opravovatel": "Klidne"}
    assert edited["building_preferences"] == ["C"]
    assert edited["can_bring_notebook"] is False and edited["can_bring_camera"] is False
    assert edited["friends"] == [2]
    assert edited["tshirt_size"] == "XL"
    assert edited["id"] == 1 and edited["person_id"] == person_id  # identity is untouched
    assert _record(mutations.get_state(workspace), 1) == edited  # persisted
    assert any(a["helper_id"] == 1 for a in state["assignments"])  # an edit never moves anyone


def test_editing_leaves_omitted_fields_alone_and_can_clear_the_contact(workspace):
    _seed(workspace, [_helper(1, "Anna", email="anna@example.test", phone="123")])

    state = mutations.update_helper(workspace, 1, phone="")

    edited = _record(state, 1)
    assert edited["phone"] is None
    assert edited["email"] == "anna@example.test"
    assert edited["name"] == "Anna"


def test_editing_records_the_changed_fields_as_hand_typed(workspace):
    _seed(workspace)
    added_id = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))["id"]

    state = mutations.update_helper(workspace, added_id, tshirt_size="S", can_bring_camera=True)

    assert set(_record(state, added_id)["hand_typed"]) == {"name", "email", "tshirt_size", "can_bring_camera"}


def test_an_invalid_edit_is_rejected_and_nothing_changes(workspace):
    _seed(workspace)
    before = mutations.get_state(workspace)

    for bad in ({"name": "  "}, {"tshirt_size": "huge"}, {"friends": [1]}, {"building_preferences": ["Nowhere"]}):
        with pytest.raises(mutations.RosteringError):
            mutations.update_helper(workspace, 1, **bad)
    with pytest.raises(mutations.RosteringError):
        mutations.update_helper(workspace, 99, name="Nobody")

    assert mutations.get_state(workspace) == before


def test_an_edit_that_changes_the_email_keeps_the_helpers_person_link(workspace):
    _seed(workspace)
    added = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))

    state = mutations.update_helper(workspace, added["id"], email="new@example.test")

    assert _record(state, added["id"])["person_id"] == added["person_id"]


# -- deleting -------------------------------------------------------------------------


def test_deleting_an_unplaced_helper_applies_at_once_without_staleness(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    added_id = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))["id"]
    roster_before = mutations.get_state(workspace)["assignments"]

    state = mutations.delete_helper(workspace, added_id)

    assert added_id not in [h["id"] for h in state["helpers"]]
    assert state["assignments"] == roster_before
    assert mutations.stale_reasons(state) == []
    assert added_id not in [h["id"] for h in mutations.get_state(workspace)["helpers"]]  # persisted


def test_deleting_a_placed_helper_asks_for_confirmation_and_changes_nothing(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)
    mutations.put_manual_roles(
        workspace,
        {"structural": [{"role": "PravaRuka", "building": "B", "room": None, "helper_id": 1, "helper_name": None}], "overlay": []},
    )
    before = mutations.get_state(workspace)

    with pytest.raises(mutations.ConfirmationRequired) as raised:
        mutations.delete_helper(workspace, 1)

    assert any(line.startswith("Assignment:") and "(locked)" in line for line in raised.value.lines)
    assert any(line.startswith("Manual role:") for line in raised.value.lines)
    assert mutations.get_state(workspace) == before


def test_confirmed_delete_clears_assignment_lock_and_manual_roles_and_stales_the_roster(workspace):
    _seed(workspace)
    mutations.solve(workspace)
    mutations.set_lock(workspace, 1, True)
    mutations.put_manual_roles(
        workspace,
        {
            "structural": [{"role": "PravaRuka", "building": "B", "room": None, "helper_id": 1, "helper_name": None}],
            "overlay": [{"role": "Registrace", "helper_id": 1, "helper_name": None, "building": "B", "room": None}],
        },
    )
    others = [a for a in mutations.get_state(workspace)["assignments"] if a["helper_id"] != 1]

    state = mutations.delete_helper(workspace, 1, confirmed=True)

    assert [h["id"] for h in state["helpers"]] == [2, 3]
    assert state["assignments"] == others
    assert state["manual_roles"] == {"structural": [], "overlay": []}
    assert len(mutations.stale_reasons(state)) == 1 and "Anna" in mutations.stale_reasons(state)[0]


def test_deleting_a_helper_with_only_a_manual_role_entry_also_asks(workspace):
    _seed(workspace)
    mutations.put_manual_roles(
        workspace,
        {"structural": [{"role": "VedouciBudovy", "building": "B", "room": None, "helper_id": 2, "helper_name": None}], "overlay": []},
    )

    with pytest.raises(mutations.ConfirmationRequired):
        mutations.delete_helper(workspace, 2)

    state = mutations.delete_helper(workspace, 2, confirmed=True)
    assert state["manual_roles"]["structural"] == []


def test_deleting_a_helper_removes_them_from_other_helpers_friend_preferences(workspace):
    _seed(
        workspace,
        [
            _helper(1, "Anna", friends=[2, 3], friend_name_decisions={"Peťa": [2], "Jani": [3], "Nikdo": None}),
            _helper(2, "Petr"),
            _helper(3, "Jana"),
        ],
    )

    state = mutations.delete_helper(workspace, 2)

    anna = _record(state, 1)
    assert anna["friends"] == [3]
    # The named friend goes back to unresolved rather than being silently dropped.
    assert anna["unresolved_friend_names"] == ["Peťa"]
    assert "Peťa" not in anna["friend_name_decisions"]
    assert anna["friend_name_decisions"] == {"Jani": [3], "Nikdo": None}


def test_deleting_recomputes_the_friend_pair_diagnostics(workspace):
    _seed(workspace, [_helper(1, "Anna", friends=[2]), _helper(2, "Petr"), _helper(3, "Jana")])
    mutations.solve(workspace)

    state = mutations.delete_helper(workspace, 2, confirmed=True)

    assert state["diagnostics"]["satisfied_friend_pairs"] == []
    assert state["diagnostics"]["unsatisfied_friend_pairs"] == []


def test_deleting_an_unknown_helper_is_rejected(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError):
        mutations.delete_helper(workspace, 99)


def test_a_deleted_helper_no_longer_counts_as_a_person_of_the_season(workspace):
    mutations.new_season(workspace)
    mutations.upload_responses(workspace, _survey([("Anna", "anna@example.test")]), "s.xlsx", "2026-jaro")
    added = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))
    assert added["person_id"] in {p["person_id"] for p in mutations.list_persons(workspace)}

    mutations.delete_helper(workspace, added["id"])

    assert added["person_id"] not in {p["person_id"] for p in mutations.list_persons(workspace)}


def test_setting_the_size_in_the_helper_table_counts_as_typed_for_a_hand_added_helper(workspace):
    _seed(workspace)
    added_id = _added(mutations.add_helper(workspace, "Eva", "eva@example.test"))["id"]

    state = mutations.set_tshirt_size(workspace, added_id, "L")

    assert set(_record(state, added_id)["hand_typed"]) == {"name", "email", "tshirt_size"}
    assert "hand_typed" not in _record(state, 1)  # survey Helpers are left as they were
