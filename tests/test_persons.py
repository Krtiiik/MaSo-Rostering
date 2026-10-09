"""E-mail capture and confident Person linking, exercised through the mutation
layer against a temp-dir workspace with synthetic surveys and people (no real
``data/`` is ever read or written)."""
import importlib
import io
import json
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

_NAME_HEADER = "Tvoje jméno a příjmení"
_EMAIL_HEADER = "E-mailová adresa"
_PHONE_HEADER = "Telefonní číslo"


@pytest.fixture
def seasons_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
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
    """Load ``rows`` as a brand-new Season (leaving no Season open first)."""
    mutations.new_season(workspace)
    return mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label=label)


def _person_ids(state):
    return {h["name"]: h["person_id"] for h in state["helpers"]}


ANNA = "anna.novakova@example.test"
PETR = "petr.svoboda@example.test"
KLARA = "klara.dvorakova@example.test"


# -- capture -------------------------------------------------------------------


def test_every_helper_carries_its_normalized_email_and_a_person_id(workspace):
    state = _new_season(
        workspace,
        "2026-jaro",
        _row("Anna Nováková", "  Anna.Novakova@Example.TEST "),
        _row("Petr Svoboda", PETR),
        _row("Klára Dvořáková", None),
    )
    assert [h["email"] for h in state["helpers"]] == [ANNA, PETR, None]
    ids = [h["person_id"] for h in state["helpers"]]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(set(ids)) == 3
    # The per-Season Helper id is a separate handle, still sequential.
    assert [h["id"] for h in state["helpers"]] == [1, 2, 3]


def test_a_person_id_is_kept_when_the_state_is_reloaded_from_disk(workspace, seasons_root):
    state = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    again = Workspace(root=seasons_root)
    assert _person_ids(mutations.get_state(again)) == _person_ids(state)


# -- confident matches ---------------------------------------------------------


def test_the_same_email_in_a_later_season_links_to_the_same_person(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA), _row("Klára Dvořáková", KLARA))
    assert _person_ids(second)["Anna Nováková"] == _person_ids(first)["Anna Nováková"]
    assert _person_ids(second)["Klára Dvořáková"] not in _person_ids(first).values()


def test_email_matching_ignores_case_and_surrounding_whitespace(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", "  ANNA.NOVAKOVA@Example.Test\t"))
    assert _person_ids(second) == _person_ids(first)


def test_the_same_email_links_even_when_the_name_changed(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA))
    second = _new_season(workspace, "2026-jaro", _row("Anna Dvořáková", ANNA))
    assert second["helpers"][0]["person_id"] == first["helpers"][0]["person_id"]
    [person] = mutations.list_persons(workspace)
    assert person["names"] == ["annadvorakova", "annanovakova"]  # both names accumulate, normalized
    assert person["name"] == "Anna Dvořáková"  # shown as in the most recent appearance


def test_the_same_name_with_a_different_email_is_not_linked_automatically(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", "anna.old@example.test"))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", "anna.new@example.test"))
    assert second["helpers"][0]["person_id"] != first["helpers"][0]["person_id"]


def test_a_row_without_an_email_is_never_linked_even_to_the_same_name(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", None), _row("Anna Nováková", None))
    second = _new_season(workspace, "2026-jaro", _row("Anna Nováková", None))
    all_ids = [h["person_id"] for h in first["helpers"]] + [h["person_id"] for h in second["helpers"]]
    assert len(set(all_ids)) == 3


def test_phone_is_never_a_match_key(workspace):
    first = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA, phone="+420 111 222 333"))
    second = _new_season(
        workspace,
        "2026-jaro",
        _row("Anna Nováková", "someone.else@example.test", phone="+420 111 222 333"),
    )
    assert second["helpers"][0]["person_id"] != first["helpers"][0]["person_id"]
    # ...and a changed number does not stop an e-mail match.
    third = _new_season(workspace, "2026-podzim", _row("Anna Nováková", ANNA, phone="+420 999 888 777"))
    assert third["helpers"][0]["person_id"] == first["helpers"][0]["person_id"]


def test_a_returner_who_skipped_a_season_is_still_recognized(workspace):
    first = _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    _new_season(workspace, "2025-podzim", _row("Petr Svoboda", PETR))
    third = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    assert third["helpers"][0]["person_id"] == first["helpers"][0]["person_id"]


def test_recognition_looks_at_seasons_stored_after_the_open_one_too(workspace):
    later = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    earlier = _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    assert earlier["helpers"][0]["person_id"] == later["helpers"][0]["person_id"]


def test_uploading_into_an_open_season_keeps_a_known_persons_id(workspace):
    first = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    reupload = mutations.upload_responses(
        workspace, _survey([_row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR)]), "s.xlsx"
    )
    assert _person_ids(reupload)["Anna Nováková"] == first["helpers"][0]["person_id"]
    assert len(mutations.list_persons(workspace)) == 2


def _seed_person_link(workspace, season_id, helper_name, person_id):
    """Rewrite one Helper's ``person_id`` in a stored Season, the way a later
    manual link or unlink would (not built yet)."""
    mutations.open_season(workspace, season_id)
    state = workspace.load()
    next(h for h in state["helpers"] if h["name"] == helper_name)["person_id"] = person_id
    workspace.save(state)


def _ids(workspace):
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def test_when_several_persons_recorded_the_email_the_most_recent_appearance_wins(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", ANNA))
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    ids = _ids(workspace)
    _seed_person_link(workspace, ids["2024-jaro"], "Anna Nováková", "person-in-2024")
    _seed_person_link(workspace, ids["2025-jaro"], "Anna Nováková", "person-in-2025")

    latest = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    assert latest["helpers"][0]["person_id"] == "person-in-2025"


def test_a_person_accumulates_every_email_across_seasons(workspace):
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", "anna.old@example.test"))
    _new_season(workspace, "2025-podzim", _row("Anna Nováková", "anna.new@example.test"))
    ids = _ids(workspace)
    # The two records are confirmed as one Person (as a later link would do).
    _seed_person_link(workspace, ids["2025-podzim"], "Anna Nováková", "one-person")
    _seed_person_link(workspace, ids["2025-jaro"], "Anna Nováková", "one-person")

    [person] = mutations.list_persons(workspace)
    assert person["person_id"] == "one-person"
    assert person["emails"] == ["anna.new@example.test", "anna.old@example.test"]
    assert person["seasons"] == ["2025-podzim", "2025-jaro"]

    # A new row matches on either of them, old address included.
    via_old = _new_season(workspace, "2026-jaro", _row("Anna N.", "ANNA.OLD@example.test"))
    assert via_old["helpers"][0]["person_id"] == "one-person"
    via_new = _new_season(workspace, "2026-podzim", _row("Anna N.", "anna.new@example.test"))
    assert via_new["helpers"][0]["person_id"] == "one-person"


# -- duplicate rows inside one export --------------------------------------------


def test_duplicate_rows_with_the_same_email_become_one_helper_with_the_latest_submission(workspace):
    state = _new_season(
        workspace,
        "2026-jaro",
        _row("Anna Nováková", ANNA, when=datetime(2026, 2, 1)),
        _row("Petr Svoboda", PETR, when=datetime(2026, 2, 2)),
        _row("Anna N.", ANNA.upper(), when=datetime(2026, 2, 3)),
    )
    assert [h["name"] for h in state["helpers"]] == ["Petr Svoboda", "Anna N."]
    assert [h["id"] for h in state["helpers"]] == [1, 2]
    assert len(mutations.list_persons(workspace)) == 2
    assert any(ANNA in w for w in state["ingestion_warnings"])


def test_same_name_with_different_emails_inside_one_export_stay_two_helpers(workspace):
    state = _new_season(
        workspace,
        "2026-jaro",
        _row("Anna Nováková", "anna1@example.test"),
        _row("Anna Nováková", "anna2@example.test"),
    )
    assert len(state["helpers"]) == 2
    assert state["helpers"][0]["person_id"] != state["helpers"][1]["person_id"]


# -- Persons exist only through the Seasons that record them ----------------------


def test_person_ids_are_never_reused_even_after_their_season_is_deleted(workspace):
    first = _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    spent = {h["person_id"] for h in first["helpers"]}
    second = _new_season(workspace, "2025-podzim", _row("Petr Svoboda", PETR))
    mutations.delete_season(workspace, _ids(workspace)["2025-jaro"])
    third = _new_season(workspace, "2026-jaro", _row("Klára Dvořáková", KLARA), _row("Anna Nováková", ANNA))
    fresh = {h["person_id"] for h in third["helpers"]}
    assert not (fresh & spent)
    assert not (fresh & {h["person_id"] for h in second["helpers"]})


def test_deleting_a_season_forgets_what_only_it_knew(workspace):
    first = _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR))
    _new_season(workspace, "2025-podzim", _row("Petr Svoboda", PETR))
    mutations.delete_season(workspace, _ids(workspace)["2025-jaro"])

    # Anna was known only from the deleted Season, Petr also from the other one.
    assert [p["name"] for p in mutations.list_persons(workspace)] == ["Petr Svoboda"]
    again = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    assert again["helpers"][0]["person_id"] != _person_ids(first)["Anna Nováková"]


def test_start_over_forgets_what_only_the_emptied_state_knew(workspace):
    first = _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    mutations.reset_workspace(workspace)
    assert mutations.list_persons(workspace) == []

    second = _new_season(workspace, "2025-podzim", _row("Anna Nováková", ANNA))
    assert second["helpers"][0]["person_id"] != first["helpers"][0]["person_id"]


def test_a_season_directory_without_a_saved_state_contributes_no_persons(workspace, seasons_root):
    hand_placed = seasons_root / "2024-jaro"
    hand_placed.mkdir(parents=True)
    (hand_placed / "raw-response.xlsx").write_bytes(_survey([_row("Anna Nováková", ANNA)]))
    assert mutations.list_persons(workspace) == []
    state = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    assert [p["seasons"] for p in mutations.list_persons(workspace)] == [["2026-jaro"]]
    assert state["helpers"][0]["person_id"]


def test_restoring_a_version_rolls_back_the_person_links(workspace):
    first = _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    state = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    version = mutations.save_version(workspace, "Linked")
    season_id = mutations.get_open_season(workspace)["id"]

    _seed_person_link(workspace, season_id, "Anna Nováková", "unlinked")
    restored = mutations.restore_version(workspace, version["slug"])
    assert restored["helpers"][0]["person_id"] == first["helpers"][0]["person_id"] == state["helpers"][0]["person_id"]


# -- Returning helpers ---------------------------------------------------------------


def test_returning_helpers_are_those_recognized_from_an_earlier_season(workspace):
    _new_season(workspace, "2024-jaro", _row("Anna Nováková", ANNA))
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR))
    state = _new_season(
        workspace,
        "2026-jaro",
        _row("Anna Nováková", ANNA),
        _row("Petr Svoboda", PETR),
        _row("Klára Dvořáková", KLARA),
    )
    by_name = {h["name"]: h["id"] for h in state["helpers"]}
    assert mutations.get_returning_helpers(workspace) == {
        by_name["Anna Nováková"]: ["2025-jaro", "2024-jaro"],
        by_name["Petr Svoboda"]: ["2025-jaro"],
    }


def test_a_later_season_does_not_make_a_helper_returning(workspace):
    _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA))
    assert mutations.get_returning_helpers(workspace) == {}
    mutations.new_season(workspace)
    assert mutations.get_returning_helpers(workspace) == {}


# -- Seasons saved before Persons existed -------------------------------------------


def test_a_season_saved_before_persons_existed_gets_stable_person_ids_on_load(workspace, seasons_root):
    _new_season(workspace, "2025-jaro", _row("Anna Nováková", ANNA), _row("Petr Svoboda", PETR))
    path = seasons_root / "2025-jaro" / "state.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    for helper in saved["helpers"]:
        helper.pop("person_id")
        helper.pop("email")
    path.write_text(json.dumps(saved), encoding="utf-8")

    state = mutations.open_season(workspace, _ids(workspace)["2025-jaro"])
    ids = _person_ids(state)
    assert len(set(ids.values())) == 2 and all(ids.values())
    assert _person_ids(Workspace(root=seasons_root).load()) == ids  # persisted, not re-drawn each load
    # They know no e-mail, so nothing matches them automatically.
    later = _new_season(workspace, "2026-jaro", _row("Anna Nováková", ANNA))
    assert later["helpers"][0]["person_id"] not in ids.values()
