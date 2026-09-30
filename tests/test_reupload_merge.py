"""Re-upload merging: a survey row of someone the organizer already added by
hand merges into that Helper (automatically by e-mail, through the review list
by name), and a hand-typed Manual role name is offered a link to a newly
recognized Helper. Exercised through the mutation layer against a temp-dir
workspace with the synthetic surveys of ``test_reupload`` (never ``data/``)."""
import pytest

from rostering.streamlit_app import mutations
from tests.test_reupload import (  # noqa: F401  (the fixtures are used by name)
    ANNA,
    KLARA,
    _named,
    _placement,
    _row,
    _upload,
    season,
    workspace,
)

PHONE = "+420 777 000 111"


def _hand_added_and_placed(workspace, name="Klára Malá", contact=KLARA, **fields):
    """A Helper added by hand, placed, locked, tagged and holding an Organizer role."""
    added = mutations.add_helper(workspace, name, contact, **fields)
    klara = next(h for h in added["helpers"] if h["name"] == name)
    mutations.move_helper(workspace, klara["id"], "Karlov", "K2", "Zaloha")
    mutations.set_lock(workspace, klara["id"], True)
    tags = mutations.add_tag(workspace, "GCHD")
    tag_id = next(t["id"] for t in tags["tags"] if t["name"] == "GCHD")
    mutations.set_helper_tags(workspace, klara["id"], [tag_id])
    manual = mutations.get_state(workspace)["manual_roles"]
    mutations.put_manual_roles(
        workspace,
        {
            **manual,
            "structural": [
                *manual["structural"],
                {"role": "VedouciBudovy", "building": "Karlov", "room": None, "helper_id": klara["id"]},
            ],
        },
    )
    return klara["id"], tag_id


def _assert_kept_everything(state, helper_id, tag_id):
    klara = next(h for h in state["helpers"] if h["id"] == helper_id)
    assert _placement(state, helper_id) == ("Karlov", "K2", "Zaloha")
    assert next(a for a in state["assignments"] if a["helper_id"] == helper_id).get("locked") is True
    assert klara["tags"] == [tag_id]
    assert [e["helper_id"] for e in state["manual_roles"]["structural"]] == [helper_id]
    return klara


def _only_candidate(workspace):
    """The one review-list entry's Helper id and its one candidate."""
    [entry] = mutations.get_uncertain_matches(workspace)
    [candidate] = entry["candidates"]
    return entry["helper_id"], candidate


def _confirm_only_match(workspace):
    helper_id, candidate = _only_candidate(workspace)
    return mutations.link_helper(workspace, helper_id, candidate["person_id"])


# -- a hand-added Helper who later registers ---------------------------------------------------


def test_a_survey_row_with_a_hand_added_helpers_email_merges_into_them_keeping_everything(workspace, season):
    helper_id, tag_id = _hand_added_and_placed(workspace, tshirt_size="L")
    person_id = next(h for h in mutations.get_state(workspace)["helpers"] if h["id"] == helper_id)["person_id"]

    state = _upload(workspace, _row("Klára Malá", KLARA, buildings="Karlov", equipment="Fotoaparát", size="S"))

    assert [h["name"] for h in state["helpers"]].count("Klára Malá") == 1
    klara = _assert_kept_everything(state, helper_id, tag_id)
    assert klara["person_id"] == person_id and klara["hand_added"] is True
    assert klara["building_preferences"] == ["Karlov"]  # left at its default by hand: the survey fills it
    assert klara["can_bring_camera"] is True
    assert klara["tshirt_size"] == "L"  # typed by hand: wins over the survey's S


def test_a_survey_row_with_only_the_same_name_waits_on_the_review_list_and_merges_on_confirm(workspace, season):
    helper_id, tag_id = _hand_added_and_placed(workspace, contact=PHONE, tshirt_size="L")
    ids_before = {h["id"] for h in mutations.get_state(workspace)["helpers"]}

    state = _upload(workspace, _row("Klára Malá", KLARA, buildings="Karlov", equipment="Fotoaparát", size="S"))

    # Nothing is merged before the user confirms.
    assert len(state["helpers"]) == len(ids_before) + 1
    newcomer_id, candidate = _only_candidate(workspace)
    assert newcomer_id not in ids_before
    assert candidate["merges_into"] == helper_id

    state = mutations.link_helper(workspace, newcomer_id, candidate["person_id"])

    assert {h["id"] for h in state["helpers"]} == ids_before  # no duplicate, no new id
    klara = _assert_kept_everything(state, helper_id, tag_id)
    assert klara["email"] == KLARA  # the contact was a phone, so the survey's e-mail fills the default
    assert klara["phone"] == PHONE  # typed by hand
    assert klara["building_preferences"] == ["Karlov"]
    assert klara["can_bring_camera"] is True
    assert klara["tshirt_size"] == "L"
    assert klara["person_id"] == candidate["person_id"]
    assert mutations.get_uncertain_matches(workspace) == []
    assert newcomer_id not in {e["helper_id"] for e in mutations.upload_summary(workspace)["new"]}
    assert mutations.unplaced_reason(state) is None  # the newcomer is gone, so no one is left unplaced


def test_confirming_a_merge_points_every_reference_to_the_row_at_the_hand_added_helper(workspace, season):
    helper_id, _ = _hand_added_and_placed(workspace, contact=PHONE)
    anna = _named(season, "Anna Nováková")
    state = _upload(workspace, _row("Klára Malá", KLARA, friends="Anna Nováková"), _row("Anna Nováková", ANNA))
    newcomer = next(h for h in state["helpers"] if h["email"] == KLARA)
    mutations.update_helper(workspace, anna["id"], friends=[newcomer["id"]])
    manual = mutations.get_state(workspace)["manual_roles"]
    mutations.put_manual_roles(
        workspace,
        {
            "structural": manual["structural"],
            "overlay": [{"role": "Registrace", "building": "Karlov", "room": None, "helper_id": newcomer["id"]}],
        },
    )

    state = _confirm_only_match(workspace)

    assert _named(state, "Anna Nováková")["friends"] == [helper_id]
    assert [e["helper_id"] for e in state["manual_roles"]["overlay"]] == [helper_id]
    assert _named(state, "Klára Malá")["friends"] == [anna["id"]]


def test_a_merge_adopts_what_the_row_was_given_meanwhile_when_the_hand_added_helper_has_none(workspace, season):
    helper_id = mutations.add_helper(workspace, "Klára Malá", PHONE)["helpers"][-1]["id"]
    state = _upload(workspace, _row("Klára Malá", KLARA))
    newcomer = next(h for h in state["helpers"] if h["email"] == KLARA)
    tags = mutations.add_tag(workspace, "Nová")
    tag_id = next(t["id"] for t in tags["tags"] if t["name"] == "Nová")
    mutations.set_helper_tags(workspace, newcomer["id"], [tag_id])
    mutations.move_helper(workspace, newcomer["id"], "Malá Strana", "M1", "Zaloha")
    mutations.set_lock(workspace, newcomer["id"], True)

    state = _confirm_only_match(workspace)

    klara = next(h for h in state["helpers"] if h["id"] == helper_id)
    assert klara["tags"] == [tag_id]
    assert _placement(state, helper_id) == ("Malá Strana", "M1", "Zaloha")
    assert next(a for a in state["assignments"] if a["helper_id"] == helper_id)["locked"] is True
    assert [a["helper_id"] for a in state["assignments"]].count(helper_id) == 1


def test_a_hand_added_helper_who_already_holds_an_assignment_keeps_it_over_the_rows(workspace, season):
    helper_id, tag_id = _hand_added_and_placed(workspace, contact=PHONE)
    state = _upload(workspace, _row("Klára Malá", KLARA))
    newcomer = next(h for h in state["helpers"] if h["email"] == KLARA)
    mutations.move_helper(workspace, newcomer["id"], "Malá Strana", "M1", "Zaloha")

    state = _confirm_only_match(workspace)

    _assert_kept_everything(state, helper_id, tag_id)
    assert [a["helper_id"] for a in state["assignments"]].count(helper_id) == 1
    assert newcomer["id"] not in {a["helper_id"] for a in state["assignments"]}


def test_declining_a_name_only_match_leaves_both_helpers(workspace, season):
    helper_id, _ = _hand_added_and_placed(workspace, contact=PHONE)
    _upload(workspace, _row("Klára Malá", KLARA))
    newcomer_id, candidate = _only_candidate(workspace)

    state = mutations.reject_person_match(workspace, newcomer_id, candidate["person_id"])

    assert {helper_id, newcomer_id} <= {h["id"] for h in state["helpers"]}
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_merged_helper_is_matched_by_email_on_the_next_upload(workspace, season):
    helper_id, tag_id = _hand_added_and_placed(workspace, contact=PHONE)
    _upload(workspace, _row("Klára Malá", KLARA))
    _confirm_only_match(workspace)

    state = _upload(workspace, _row("Klára Malá", KLARA, buildings="Malá Strana"))

    assert [h["name"] for h in state["helpers"]].count("Klára Malá") == 1
    klara = _assert_kept_everything(state, helper_id, tag_id)
    assert klara["building_preferences"] == ["Malá Strana"]


def test_confirming_a_same_name_match_between_two_survey_helpers_only_links_them(workspace, season):
    petr = _named(season, "Petr Svoboda")
    state = _upload(workspace, _row("Petr Svoboda", "petr.jiny@example.test"))
    newcomer = next(h for h in state["helpers"] if h["email"] == "petr.jiny@example.test")

    _, candidate = _only_candidate(workspace)
    assert candidate["merges_into"] is None
    state = mutations.link_helper(workspace, newcomer["id"], petr["person_id"])

    assert {petr["id"], newcomer["id"]} <= {h["id"] for h in state["helpers"]}  # two Helpers, as before


# -- a typed Manual role name offered a link ------------------------------------------------


def _type_role(workspace, name, *, group="structural", role="VedouciBudovy", building="Karlov", room=None):
    manual = mutations.get_state(workspace)["manual_roles"]
    entry = {"role": role, "building": building, "room": room, "helper_id": None, "helper_name": name}
    return mutations.put_manual_roles(workspace, {**manual, group: [*manual[group], entry]})


def test_a_typed_role_name_is_offered_a_link_to_a_newly_recognized_helper_of_that_name(workspace, season):
    _type_role(workspace, "Klára Malá")
    assert mutations.get_typed_role_link_offers(workspace) == []  # nobody of that name is registered yet

    _upload(workspace, _row("Klára Malá", KLARA))

    [offer] = mutations.get_typed_role_link_offers(workspace)
    assert offer["name"] == "Klára Malá"
    assert [c["email"] for c in offer["candidates"]] == [KLARA]
    assert len(offer["slots"]) == 1


def test_a_typed_name_matches_ignoring_case_and_diacritics_and_only_by_name(workspace, season):
    _type_role(workspace, "klara mala")
    _upload(workspace, _row("Klára Malá", KLARA), _row("Klára Malá Druhá", "k2@example.test"))

    [offer] = mutations.get_typed_role_link_offers(workspace)
    assert [c["email"] for c in offer["candidates"]] == [KLARA]


def test_a_helper_who_cant_attend_is_not_offered(workspace, season):
    _type_role(workspace, "Klára Malá")
    state = _upload(workspace, _row("Klára Malá", KLARA))
    mutations.set_cant_attend(workspace, _named(state, "Klára Malá")["id"], True)

    assert mutations.get_typed_role_link_offers(workspace) == []


def test_confirming_the_link_turns_the_typed_text_into_a_helper_reference(workspace, season):
    _type_role(workspace, "Klára Malá")
    _type_role(workspace, "Klára Malá", group="overlay", role="Registrace", building="Malá Strana")
    state = _upload(workspace, _row("Klára Malá", KLARA))
    klara = _named(state, "Klára Malá")
    [offer] = mutations.get_typed_role_link_offers(workspace)

    state = mutations.link_typed_role_name(workspace, offer["name"], klara["id"])

    [structural] = state["manual_roles"]["structural"]
    [overlay] = state["manual_roles"]["overlay"]
    assert (structural["helper_id"], structural["helper_name"]) == (klara["id"], None)
    assert (overlay["helper_id"], overlay["helper_name"]) == (klara["id"], None)
    assert mutations.get_typed_role_link_offers(workspace) == []


def test_linking_a_typed_name_to_a_helper_already_in_that_slot_drops_the_duplicate(workspace, season):
    state = _upload(workspace, _row("Klára Malá", KLARA))
    klara = _named(state, "Klára Malá")
    _type_role(workspace, "Klára Malá", role="Registrace", group="overlay", building="Karlov")
    manual = mutations.get_state(workspace)["manual_roles"]
    holder = {"role": "Registrace", "building": "Karlov", "room": None, "helper_id": klara["id"], "helper_name": None}
    mutations.put_manual_roles(workspace, {**manual, "overlay": [*manual["overlay"], holder]})

    state = mutations.link_typed_role_name(workspace, "Klára Malá", klara["id"])

    assert [e["helper_id"] for e in state["manual_roles"]["overlay"]] == [klara["id"]]


def test_declining_the_link_leaves_the_text_and_is_not_offered_again(workspace, season):
    _type_role(workspace, "Klára Malá")
    state = _upload(workspace, _row("Klára Malá", KLARA))
    klara = _named(state, "Klára Malá")

    state = mutations.decline_typed_role_link(workspace, "Klára Malá", klara["id"])

    [entry] = state["manual_roles"]["structural"]
    assert (entry["helper_id"], entry["helper_name"]) == (None, "Klára Malá")
    assert mutations.get_typed_role_link_offers(workspace) == []
    _upload(workspace, _row("Klára Malá", KLARA, buildings="Karlov"))  # even after another upload
    assert mutations.get_typed_role_link_offers(workspace) == []


def test_a_link_is_refused_for_a_name_that_does_not_match(workspace, season):
    _type_role(workspace, "Klára Malá")
    state = _upload(workspace, _row("Jiná Osoba", "jina@example.test"))

    with pytest.raises(mutations.RosteringError):
        mutations.link_typed_role_name(workspace, "Klára Malá", _named(state, "Jiná Osoba")["id"])
