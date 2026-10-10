"""The uncertain-match review list, and undoing / hand-making Person links,
exercised through the mutation layer against a temp-dir workspace with
synthetic surveys and people (no real ``data/`` is ever read or written)."""
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

_NAME_HEADER = "Tvoje jméno a příjmení"
_EMAIL_HEADER = "E-mailová adresa"
_PHONE_HEADER = "Telefonní číslo"

ANNA_OLD = "anna.old@example.test"
ANNA_NEW = "anna.new@example.test"
PETR = "petr.svoboda@example.test"


@pytest.fixture
def seasons_root(tmp_path, monkeypatch):
    return tmp_path / "seasons"


@pytest.fixture
def workspace(seasons_root):
    return Workspace(root=seasons_root)


def _row(name, email=None, phone=None, when=datetime(2026, 2, 1)):
    return {"name": name, "email": email, "phone": phone, "when": when}


def _survey(rows) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "Časová značka": [r["when"] for r in rows],
            _NAME_HEADER: [r["name"] for r in rows],
            _EMAIL_HEADER: [r["email"] for r in rows],
            _PHONE_HEADER: [r["phone"] for r in rows],
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


def _new_season(workspace, label, *rows):
    mutations.new_season(workspace)
    return mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label=label)


def _reupload(workspace, *rows):
    return mutations.upload_responses(workspace, _survey(rows), "s.xlsx")


def _helper(state, name):
    return next(h for h in state["helpers"] if h["name"] == name)


def _person_id_of(workspace, helper_name):
    return _helper(mutations.get_state(workspace), helper_name)["person_id"]


def _season_ids(workspace):
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def _open(workspace, label):
    return mutations.open_season(workspace, _season_ids(workspace)[label])


def _proposals(workspace):
    """The review list as ``{helper name: [candidate person ids]}``."""
    return {
        entry["helper_name"]: [c["person_id"] for c in entry["candidates"]]
        for entry in mutations.get_uncertain_matches(workspace)
    }


def _anna_pair(workspace):
    """2025-podzim has Anna (old e-mail); 2026-jaro has Anna (a new e-mail),
    so the 2026 row is an uncertain match. Returns (2025 person id, 2026 state)."""
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD, "+420 111 000 111"))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_NEW, "+420 222 000 222"))
    return first["helpers"][0]["person_id"], second


# -- the review list ---------------------------------------------------------------


def test_an_identical_name_without_an_email_match_is_proposed_with_the_candidates_details(workspace):
    old_person, state = _anna_pair(workspace)
    helper = state["helpers"][0]

    [entry] = mutations.get_uncertain_matches(workspace)
    assert entry["helper_id"] == helper["id"]
    assert entry["helper_name"] == "Anna Nováková"
    assert entry["helper_email"] == ANNA_NEW
    assert entry["helper_phone"] == "+420 222 000 222"
    [candidate] = entry["candidates"]
    assert candidate["person_id"] == old_person
    assert candidate["name"] == "Anna Nováková"
    assert candidate["season"] == "2025-podzim"
    assert candidate["email"] == ANNA_OLD
    assert candidate["phone"] == "+420 111 000 111"  # shown as a hint only


def test_the_name_is_compared_ignoring_case_diacritics_and_spacing(workspace):
    _new_season(workspace, "2025-podzim", _row("Šárka Nováková ", "sarka.old@example.test"))
    _new_season(workspace, "2026-jaro", _row("sarka novakova", "sarka.new@example.test"))
    assert list(_proposals(workspace)) == ["sarka novakova"]


def test_nothing_is_merged_until_the_candidate_is_confirmed(workspace):
    old_person, state = _anna_pair(workspace)
    assert state["helpers"][0]["person_id"] != old_person
    assert mutations.get_returning_helpers(workspace) == {}
    assert len(mutations.list_persons(workspace)) == 2
    # Looking at the list, or reloading, changes nothing either.
    mutations.get_uncertain_matches(workspace)
    assert Workspace(root=workspace.root).load()["helpers"][0]["person_id"] != old_person


def test_a_different_name_is_never_proposed(workspace):
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2026-jaro", _row("Petra Nováková", "petra@example.test"))
    assert mutations.get_uncertain_matches(workspace) == []


def test_phone_alone_never_proposes_a_candidate(workspace):
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD, "+420 111 000 111"))
    _new_season(workspace, "2026-jaro", _row("Petra Nováková", "petra@example.test", "+420 111 000 111"))
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_helper_already_linked_by_email_gets_no_proposals(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", "some.other.anna@example.test"))
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_OLD))
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_row_without_an_email_is_proposed_against_a_same_name_person(workspace):
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", None))
    assert list(_proposals(workspace)) == ["Anna Nováková"]


def test_the_review_list_is_empty_with_no_season_open(workspace):
    _anna_pair(workspace)
    mutations.new_season(workspace)
    assert mutations.get_uncertain_matches(workspace) == []


def test_every_earlier_season_is_looked_at_and_the_most_recent_spelling_is_shown(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", "anna.2024@example.test"))
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", "anna.2025@example.test"))
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", "anna.2026@example.test"))
    [entry] = mutations.get_uncertain_matches(workspace)
    assert [(c["season"], c["email"]) for c in entry["candidates"]] == [
        ("2025-jaro", "anna.2025@example.test"),
        ("2024-jaro", "anna.2024@example.test"),
    ]


def test_a_person_known_by_several_records_is_one_candidate(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_NEW))
    [entry] = mutations.get_uncertain_matches(workspace)
    [candidate] = entry["candidates"]
    assert candidate["season"] == "2025-jaro"


def test_a_persons_earlier_name_also_proposes_it(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2025-jaro", _row("Anna Dvořáková", ANNA_OLD))  # linked by e-mail, name changed
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_NEW))  # the maiden name again
    [entry] = mutations.get_uncertain_matches(workspace)
    [candidate] = entry["candidates"]
    assert (candidate["name"], candidate["season"]) == ("Anna Nováková", "2024-jaro")


def test_two_rows_of_one_export_with_the_same_name_and_different_emails_go_to_the_review_list(workspace):
    state = _new_season(
        workspace,
        "2026-jaro",
        _row("Anna Nováková", "anna1@example.test", "+420 111 111 111"),
        _row("Petr Svoboda", PETR),
        _row("Anna Nováková", "anna2@example.test", "+420 222 222 222"),
    )
    first, _, second = state["helpers"]
    assert first["person_id"] != second["person_id"]

    # One row for the pair, not one per direction.
    [entry] = mutations.get_uncertain_matches(workspace)
    assert entry["helper_id"] == second["id"]
    [candidate] = entry["candidates"]
    assert candidate["person_id"] == first["person_id"]
    assert candidate["season"] == "2026-jaro"
    assert candidate["email"] == "anna1@example.test"
    assert candidate["phone"] == "+420 111 111 111"


def test_several_same_name_candidates_of_one_helper_are_listed_together(workspace):
    _new_season(workspace, "2024-jaro", _row("Jan Novák", "jan.a@example.test"))
    _new_season(workspace, "2025-jaro", _row("Jan Novák", "jan.b@example.test"))
    _new_season(workspace, "2026-jaro", _row("Jan Novák", "jan.c@example.test"), _row("Petr Svoboda", PETR))
    [entry] = mutations.get_uncertain_matches(workspace)
    assert entry["helper_name"] == "Jan Novák"
    assert [(c["season"], c["email"]) for c in entry["candidates"]] == [
        ("2025-jaro", "jan.b@example.test"),
        ("2024-jaro", "jan.a@example.test"),
    ]


# -- Link -----------------------------------------------------------------------------


def test_linking_a_candidate_makes_the_helper_a_returning_helper_of_that_person(workspace):
    old_person, state = _anna_pair(workspace)
    helper = state["helpers"][0]

    after = mutations.link_helper(workspace, helper["id"], old_person)
    assert _helper(after, "Anna Nováková")["person_id"] == old_person
    assert mutations.get_returning_helpers(workspace) == {helper["id"]: ["2025-podzim"]}
    assert mutations.get_uncertain_matches(workspace) == []
    [person] = mutations.list_persons(workspace)
    assert person["emails"] == [ANNA_NEW, ANNA_OLD]  # the person accumulates both


def test_linking_is_persisted(workspace, seasons_root):
    old_person, state = _anna_pair(workspace)
    mutations.link_helper(workspace, state["helpers"][0]["id"], old_person)
    again = Workspace(root=seasons_root)
    assert again.load()["helpers"][0]["person_id"] == old_person
    assert mutations.get_uncertain_matches(again) == []


def test_link_edits_change_only_the_person_link_never_a_helper_id_or_anything_else(workspace):
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    before = _new_season(
        workspace,
        "2026-jaro",
        _row("Petr Svoboda", PETR),
        _row("Anna Nováková", ANNA_NEW),
        _row("Klára Dvořáková", "klara@example.test"),
    )
    anna = _helper(before, "Anna Nováková")
    [entry] = mutations.get_uncertain_matches(workspace)
    candidate = entry["candidates"][0]["person_id"]
    assert candidate != anna["person_id"]

    after = mutations.link_helper(workspace, anna["id"], candidate)
    assert [h["id"] for h in after["helpers"]] == [h["id"] for h in before["helpers"]]
    assert _helper(after, "Anna Nováková")["person_id"] == candidate
    for old, new in zip(before["helpers"], after["helpers"]):
        if old["id"] == anna["id"]:
            continue
        assert new == old  # every other Helper record is untouched
    anna_after = _helper(after, "Anna Nováková")
    assert {k: v for k, v in anna_after.items() if k not in ("person_id", "link_confirmed")} == {
        k: v for k, v in anna.items() if k not in ("person_id", "link_confirmed")
    }


def test_a_confirmed_link_survives_a_reupload_of_the_same_export(workspace):
    old_person, state = _anna_pair(workspace)
    mutations.link_helper(workspace, state["helpers"][0]["id"], old_person)
    again = _reupload(workspace, _row("Anna Nováková", ANNA_NEW))
    assert again["helpers"][0]["person_id"] == old_person
    assert mutations.get_uncertain_matches(workspace) == []


def test_picking_one_candidate_settles_the_helper_even_after_that_persons_season_is_deleted(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", "anna.2024@example.test"))
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA_OLD))
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_NEW))
    candidates = mutations.get_uncertain_matches(workspace)[0]["candidates"]
    newest = candidates[0]["person_id"]
    helper_id = mutations.get_uncertain_matches(workspace)[0]["helper_id"]
    mutations.link_helper(workspace, helper_id, newest)
    # Picking one settles the Helper: the other same-name candidate goes away.
    assert mutations.get_uncertain_matches(workspace) == []
    mutations.new_season(workspace)
    mutations.delete_season(workspace, _season_ids(workspace)["2025-jaro"])
    _open(workspace, "2026-jaro")
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_confirmed_link_is_independent_of_email_later_matches_use_every_email_of_the_person(workspace):
    old_person, state = _anna_pair(workspace)
    mutations.link_helper(workspace, state["helpers"][0]["id"], old_person)

    via_old = _new_season(workspace, "2026-podzim", _row("Anna N.", ANNA_OLD))
    assert via_old["helpers"][0]["person_id"] == old_person
    via_new = _new_season(workspace, "2027-jaro", _row("Someone Else", ANNA_NEW))
    assert via_new["helpers"][0]["person_id"] == old_person


def test_a_linked_person_is_proposed_again_only_for_a_new_helper_with_a_third_email(workspace):
    old_person, state = _anna_pair(workspace)
    mutations.link_helper(workspace, state["helpers"][0]["id"], old_person)
    _new_season(workspace, "2026-podzim", _row("Anna Nováková", "anna.third@example.test"))
    assert list(_proposals(workspace).values()) == [[old_person]]


def test_linking_to_an_unknown_person_or_helper_is_refused_and_changes_nothing(workspace):
    old_person, state = _anna_pair(workspace)
    helper_id = state["helpers"][0]["id"]
    with pytest.raises(mutations.RosteringError):
        mutations.link_helper(workspace, helper_id, "no-such-person")
    with pytest.raises(mutations.RosteringError):
        mutations.link_helper(workspace, 999, old_person)
    assert mutations.get_state(workspace)["helpers"][0]["person_id"] != old_person
    assert len(mutations.get_uncertain_matches(workspace)) == 1


def test_linking_a_helper_to_the_person_it_already_has_is_refused(workspace):
    old_person, state = _anna_pair(workspace)
    mutations.link_helper(workspace, state["helpers"][0]["id"], old_person)
    with pytest.raises(mutations.RosteringError):
        mutations.link_helper(workspace, state["helpers"][0]["id"], old_person)


# -- Not the same person -----------------------------------------------------------------


def test_a_rejected_pairing_is_not_proposed_again(workspace):
    old_person, state = _anna_pair(workspace)
    helper_id = state["helpers"][0]["id"]
    after = mutations.reject_person_match(workspace, helper_id, old_person)
    assert after["helpers"][0]["person_id"] != old_person
    assert mutations.get_uncertain_matches(workspace) == []
    assert mutations.get_returning_helpers(workspace) == {}
    assert len(mutations.list_persons(workspace)) == 2


def test_a_rejection_is_remembered_across_a_reupload_of_the_export(workspace):
    old_person, state = _anna_pair(workspace)
    mutations.reject_person_match(workspace, state["helpers"][0]["id"], old_person)
    _reupload(workspace, _row("Anna Nováková", ANNA_NEW), _row("Petr Svoboda", PETR))
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_rejection_is_remembered_when_the_other_season_is_opened(workspace):
    old_person, state = _anna_pair(workspace)
    assert len(mutations.get_uncertain_matches(workspace)) == 1
    mutations.reject_person_match(workspace, state["helpers"][0]["id"], old_person)
    _open(workspace, "2025-podzim")
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_rejection_is_remembered_after_reopening_the_workspace(workspace, seasons_root):
    old_person, state = _anna_pair(workspace)
    mutations.reject_person_match(workspace, state["helpers"][0]["id"], old_person)
    assert mutations.get_uncertain_matches(Workspace(root=seasons_root)) == []


def test_rejecting_one_of_several_candidates_keeps_the_others_listed(workspace):
    _new_season(workspace, "2024-jaro", _row("Jan Novák", "jan.a@example.test"))
    _new_season(workspace, "2025-jaro", _row("Jan Novák", "jan.b@example.test"))
    _new_season(workspace, "2026-jaro", _row("Jan Novák", "jan.c@example.test"))
    [entry] = mutations.get_uncertain_matches(workspace)
    newest, oldest = [c["person_id"] for c in entry["candidates"]]

    mutations.reject_person_match(workspace, entry["helper_id"], newest)
    [entry] = mutations.get_uncertain_matches(workspace)
    assert [c["person_id"] for c in entry["candidates"]] == [oldest]

    mutations.reject_person_match(workspace, entry["helper_id"], oldest)
    assert mutations.get_uncertain_matches(workspace) == []


def test_picking_none_by_rejecting_every_candidate_leaves_the_helper_unlinked(workspace):
    _new_season(workspace, "2025-jaro", _row("Jan Novák", "jan.b@example.test"))
    state = _new_season(workspace, "2026-jaro", _row("Jan Novák", "jan.c@example.test"))
    [entry] = mutations.get_uncertain_matches(workspace)
    for candidate in entry["candidates"]:
        mutations.reject_person_match(workspace, entry["helper_id"], candidate["person_id"])
    assert mutations.get_uncertain_matches(workspace) == []
    assert mutations.get_returning_helpers(workspace) == {}
    assert mutations.get_state(workspace)["helpers"][0]["person_id"] == state["helpers"][0]["person_id"]


def test_a_rejected_pairing_can_still_be_linked_by_hand_later(workspace):
    old_person, state = _anna_pair(workspace)
    helper_id = state["helpers"][0]["id"]
    mutations.reject_person_match(workspace, helper_id, old_person)
    after = mutations.link_helper(workspace, helper_id, old_person)
    assert after["helpers"][0]["person_id"] == old_person


def test_rejecting_an_unknown_person_or_the_helpers_own_person_is_refused(workspace):
    old_person, state = _anna_pair(workspace)
    helper = state["helpers"][0]
    with pytest.raises(mutations.RosteringError):
        mutations.reject_person_match(workspace, helper["id"], "no-such-person")
    with pytest.raises(mutations.RosteringError):
        mutations.reject_person_match(workspace, helper["id"], helper["person_id"])
    with pytest.raises(mutations.RosteringError):
        mutations.reject_person_match(workspace, 999, old_person)


# -- unlink and manual link -----------------------------------------------------------------


def test_an_automatic_link_can_be_undone(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_OLD), _row("Petr Svoboda", PETR))
    anna = _helper(second, "Anna Nováková")
    assert anna["person_id"] == first["helpers"][0]["person_id"]

    after = mutations.unlink_helper(workspace, anna["id"])
    assert _helper(after, "Anna Nováková")["person_id"] != first["helpers"][0]["person_id"]
    assert _helper(after, "Anna Nováková")["id"] == anna["id"]
    assert mutations.get_returning_helpers(workspace) == {}
    # The earlier Season's record keeps its Person, and the unlinked Helper
    # is not proposed straight back to the Person it was just unlinked from.
    assert _open(workspace, "2025-podzim")["helpers"][0]["person_id"] == first["helpers"][0]["person_id"]
    _open(workspace, "2026-jaro")
    assert mutations.get_uncertain_matches(workspace) == []
    assert len(mutations.list_persons(workspace)) == 3  # Anna 2025, the unlinked Anna 2026, Petr


def test_an_unlinked_helper_stays_unlinked_after_a_reupload_with_the_same_email(workspace):
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_OLD))
    unlinked = mutations.unlink_helper(workspace, second["helpers"][0]["id"])["helpers"][0]["person_id"]
    again = _reupload(workspace, _row("Anna Nováková", ANNA_OLD))
    assert again["helpers"][0]["person_id"] == unlinked
    assert mutations.get_uncertain_matches(workspace) == []


def test_unlinking_a_helper_that_is_not_linked_is_refused(workspace):
    _, state = _anna_pair(workspace)
    with pytest.raises(mutations.RosteringError):
        mutations.unlink_helper(workspace, state["helpers"][0]["id"])
    with pytest.raises(mutations.RosteringError):
        mutations.unlink_helper(workspace, 999)


def test_a_confirmed_link_can_be_unlinked_and_is_then_not_proposed_again(workspace):
    old_person, state = _anna_pair(workspace)
    helper_id = state["helpers"][0]["id"]
    mutations.link_helper(workspace, helper_id, old_person)
    after = mutations.unlink_helper(workspace, helper_id)
    assert after["helpers"][0]["person_id"] != old_person
    assert mutations.get_returning_helpers(workspace) == {}
    assert mutations.get_uncertain_matches(workspace) == []


def test_a_helper_can_be_linked_by_hand_to_any_past_person_whatever_the_name(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD), _row("Petr Svoboda", PETR))
    petr_person = _helper(first, "Petr Svoboda")["person_id"]
    second = _new_season(workspace, "2026-jaro", _row("Peter Svoboda", "peter@example.test"))
    assert mutations.get_uncertain_matches(workspace) == []  # no fuzzy or nickname matching

    helper = second["helpers"][0]
    after = mutations.link_helper(workspace, helper["id"], petr_person)
    assert after["helpers"][0]["id"] == helper["id"]
    assert after["helpers"][0]["person_id"] == petr_person
    assert mutations.get_returning_helpers(workspace) == {helper["id"]: ["2025-podzim"]}
    [person] = [p for p in mutations.list_persons(workspace) if p["person_id"] == petr_person]
    assert person["emails"] == ["peter@example.test", PETR]
    assert person["name"] == "Peter Svoboda"


def test_relinking_moves_only_that_helper_and_leaves_the_earlier_seasons_alone(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD), _row("Petr Svoboda", PETR))
    anna_person = _helper(first, "Anna Nováková")["person_id"]
    petr_person = _helper(first, "Petr Svoboda")["person_id"]
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA_OLD))

    after = mutations.link_helper(workspace, second["helpers"][0]["id"], petr_person)
    assert after["helpers"][0]["person_id"] == petr_person
    assert _open(workspace, "2025-podzim")["helpers"][0]["person_id"] == anna_person


def test_get_person_links_describes_a_linked_helpers_other_records(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA_OLD))
    second = _new_season(workspace, "2026-jaro", _row("Anna N.", ANNA_OLD), _row("Petr Svoboda", PETR))
    links = mutations.get_person_links(workspace)
    anna, petr = second["helpers"]
    assert list(links) == [anna["id"]]
    assert links[anna["id"]]["person_id"] == first["helpers"][0]["person_id"]
    assert links[anna["id"]]["records"] == [
        {"season": "2025-podzim", "name": "Anna Nováková", "email": ANNA_OLD, "phone": None}
    ]
    assert petr["id"] not in links


# -- Versions and forgetting ----------------------------------------------------------------


def test_restoring_a_version_rolls_back_links_and_rejections(workspace):
    old_person, state = _anna_pair(workspace)
    helper_id = state["helpers"][0]["id"]
    version = mutations.save_version(workspace, "Before review")

    mutations.link_helper(workspace, helper_id, old_person)
    assert mutations.get_uncertain_matches(workspace) == []
    restored = mutations.restore_version(workspace, version["slug"])
    assert restored["helpers"][0]["person_id"] != old_person
    assert len(mutations.get_uncertain_matches(workspace)) == 1

    mutations.reject_person_match(workspace, helper_id, old_person)
    assert mutations.get_uncertain_matches(workspace) == []
    mutations.restore_version(workspace, version["slug"])
    assert len(mutations.get_uncertain_matches(workspace)) == 1


def test_a_version_taken_after_linking_restores_the_link(workspace):
    old_person, state = _anna_pair(workspace)
    helper_id = state["helpers"][0]["id"]
    mutations.link_helper(workspace, helper_id, old_person)
    version = mutations.save_version(workspace, "Linked")
    mutations.unlink_helper(workspace, helper_id)
    restored = mutations.restore_version(workspace, version["slug"])
    assert restored["helpers"][0]["person_id"] == old_person
    assert mutations.get_uncertain_matches(workspace) == []


def test_start_over_forgets_the_proposals(workspace):
    _anna_pair(workspace)
    mutations.reset_workspace(workspace)
    assert mutations.get_uncertain_matches(workspace) == []
