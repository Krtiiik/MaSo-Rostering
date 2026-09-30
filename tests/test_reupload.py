"""Re-uploading a newer export into the open Season: recognized Helpers refresh
from the latest row, new registrants enter unassigned, and nothing hand-made
moves. Exercised through the mutation layer against a temp-dir workspace seeded
with synthetic surveys (never anything from ``data/``)."""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.streamlit_app import mutations

_NAME = "Tvoje jméno a příjmení"
_EMAIL = "E-mailová adresa"
_FRIENDS = "Chtěl/a bys být v místnosti s někým konkrétním?"
_BUILDING = "Na jakém místě bys chtěl/a pomáhat?"
_EQUIPMENT = "Můžeš něco z níže uvedených přinést na soutěž?"
_SIZE = "Tvoje velikost trička"
_PREF = "Výběr role [{}]"

ANNA = "anna@example.test"
PETR = "petr@example.test"
JANA = "jana@example.test"
KLARA = "klara@example.test"

CONFIG = [
    {
        "name": "Karlov",
        "rooms": [
            {"name": "K1", "capacities": {"Zaloha": {"minimum": 0}}},
            {"name": "K2", "capacities": {"Zaloha": {"minimum": 0}}},
        ],
        "capacities": {},
    },
    {"name": "Malá Strana", "rooms": [{"name": "M1", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}},
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "seasons")


def _row(name, email=None, *, friends=None, buildings=None, equipment=None, size="M", opravovatel=None, when=None):
    return {
        "name": name,
        "email": email,
        "friends": friends,
        "buildings": buildings,
        "equipment": equipment,
        "size": size,
        "opravovatel": opravovatel,
        "when": when or datetime(2026, 2, 1),
    }


def _survey(*rows) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "Časová značka": [r["when"] for r in rows],
            _NAME: [r["name"] for r in rows],
            _EMAIL: [r["email"] for r in rows],
            _FRIENDS: [r["friends"] for r in rows],
            _BUILDING: [r["buildings"] for r in rows],
            _EQUIPMENT: [r["equipment"] for r in rows],
            _SIZE: [r["size"] for r in rows],
            _PREF.format("Opravovatel"): [r["opravovatel"] for r in rows],
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


def _upload(workspace, *rows, label=None):
    return mutations.upload_responses(workspace, _survey(*rows), "s.xlsx", label=label)


def _named(state, name):
    return next(h for h in state["helpers"] if h["name"] == name)


def _placement(state, helper_id):
    found = next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)
    return None if found is None else (found["building"], found["room"], found["role"])


@pytest.fixture
def season(workspace):
    """2026-jaro with Anna, Petr and Jana, all placed by hand, plus a Tag."""
    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Karlov", equipment="Notebook", opravovatel="Ano"),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
        label="2026-jaro",
    )
    mutations.put_config(workspace, CONFIG)
    for helper, cell in zip(state["helpers"], [("Karlov", "K1"), ("Karlov", "K2"), ("Malá Strana", "M1")]):
        mutations.move_helper(workspace, helper["id"], cell[0], cell[1], "Zaloha")
    return mutations.get_state(workspace)


def test_an_identical_email_updates_the_same_helper_keeping_their_id_and_assignment(workspace, season):
    anna = _named(season, "Anna Nováková")

    state = _upload(
        workspace,
        _row("Anna Nováková", " ANNA@example.test", buildings="Malá Strana", equipment="Notebook, Fotoaparát"),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
    )

    assert len(state["helpers"]) == 3
    updated = _named(state, "Anna Nováková")
    assert updated["id"] == anna["id"] and updated["person_id"] == anna["person_id"]
    assert updated["building_preferences"] == ["Malá Strana"]
    assert updated["can_bring_camera"] is True
    assert updated["role_preferences"] == {}  # the latest row left the question blank
    assert _placement(state, anna["id"]) == ("Karlov", "K1", "Zaloha")


def test_a_reupload_touches_nothing_hand_made(workspace, season):
    anna, petr, jana = (_named(season, n) for n in ("Anna Nováková", "Petr Svoboda", "Jana Dvořáková"))
    mutations.set_lock(workspace, anna["id"], True)
    mutations.set_cant_attend(workspace, jana["id"], True, confirmed=True)
    tag = mutations.add_tag(workspace, "GCHD")
    tag_id = next(t["id"] for t in tag["tags"] if t["name"] == "GCHD")
    mutations.set_helper_tags(workspace, petr["id"], [tag_id])
    mutations.put_manual_roles(
        workspace,
        {
            "structural": [{"role": "VedouciBudovy", "building": "Karlov", "room": None, "helper_id": petr["id"]}],
            "overlay": [],
        },
    )
    mutations.set_cell_merges(workspace, "Zaloha", "Karlov", [["K1", "K2"]], True)
    before = mutations.get_state(workspace)

    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Malá Strana"),
        _row("Petr Svoboda", PETR, equipment="Notebook"),
        _row("Jana Dvořáková", JANA, size="XL"),
    )

    assert state["assignments"] == before["assignments"]  # Anna's lock included
    assert state["manual_roles"] == before["manual_roles"]
    assert state["cell_merges"] == before["cell_merges"]
    assert state["tags"] == before["tags"]
    assert _named(state, "Petr Svoboda")["tags"] == [tag_id]
    assert _named(state, "Jana Dvořáková")["cant_attend"] is True
    assert _named(state, "Jana Dvořáková")["tshirt_size"] == "XL"  # survey fields still refresh


def test_new_registrants_get_fresh_ids_and_appear_unassigned(workspace, season):
    ids_before = {h["id"] for h in season["helpers"]}

    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
        _row("Klára Malá", KLARA),
    )

    klara = _named(state, "Klára Malá")
    assert klara["id"] not in ids_before
    assert _placement(state, klara["id"]) is None
    assert {h["id"] for h in state["helpers"]} == ids_before | {klara["id"]}
    assert len(state["assignments"]) == 3


def test_a_deleted_helpers_id_is_not_reused_by_a_new_registrant(workspace, season):
    jana = _named(season, "Jana Dvořáková")
    mutations.delete_helper(workspace, jana["id"], confirmed=True)

    state = _upload(workspace, _row("Anna Nováková", ANNA), _row("Klára Malá", KLARA))

    assert _named(state, "Klára Malá")["id"] > jana["id"]


def test_helpers_missing_from_the_export_are_kept_untouched(workspace, season):
    petr = _named(season, "Petr Svoboda")

    state = _upload(workspace, _row("Anna Nováková", ANNA))

    assert _named(state, "Petr Svoboda") == petr
    assert _placement(state, petr["id"]) == ("Karlov", "K2", "Zaloha")
    assert len(state["helpers"]) == 3


def test_duplicate_rows_in_the_export_collapse_to_the_latest_submission(workspace, season):
    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Malá Strana", when=datetime(2026, 3, 1)),
        _row("Anna N.", ANNA, buildings="Karlov", when=datetime(2026, 3, 5)),
    )

    assert len(state["helpers"]) == 3
    anna = next(h for h in state["helpers"] if h["email"] == ANNA)
    assert anna["name"] == "Anna N." and anna["building_preferences"] == ["Karlov"]


def test_the_same_name_with_a_different_email_is_a_new_helper_on_the_review_list(workspace, season):
    petr = _named(season, "Petr Svoboda")

    state = _upload(workspace, _row("Petr Svoboda", "petr.jiny@example.test"))

    assert len(state["helpers"]) == 4
    newcomer = next(h for h in state["helpers"] if h["email"] == "petr.jiny@example.test")
    assert newcomer["id"] != petr["id"] and newcomer["person_id"] != petr["person_id"]
    assert _placement(state, newcomer["id"]) is None
    [entry] = mutations.get_uncertain_matches(workspace)
    assert entry["helper_id"] == newcomer["id"]
    assert [c["person_id"] for c in entry["candidates"]] == [petr["person_id"]]


# -- friend names ------------------------------------------------------------------


def _with_unresolved_friend(workspace, friend_text="Terka"):
    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, friends=friend_text),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
        label="2026-jaro",
    )
    anna = _named(state, "Anna Nováková")
    petr = _named(state, "Petr Svoboda")
    assert anna["unresolved_friend_names"] == [friend_text]
    return mutations.resolve_friend(workspace, anna["id"], friend_text, "resolve", [petr["id"]])


def test_a_hand_resolved_friend_name_keeps_its_resolution_while_the_same_name_remains(workspace):
    state = _with_unresolved_friend(workspace)
    anna, petr = _named(state, "Anna Nováková"), _named(state, "Petr Svoboda")

    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, friends="Terka", buildings="Karlov"),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
    )

    updated = _named(state, "Anna Nováková")
    assert updated["friends"] == [petr["id"]]
    assert updated["unresolved_friend_names"] == []
    assert updated["friend_name_decisions"] == {"Terka": [petr["id"]]}
    assert updated["id"] == anna["id"]


def test_a_dismissed_friend_name_stays_dismissed_while_the_name_remains(workspace):
    state = _with_unresolved_friend(workspace)
    anna = _named(state, "Anna Nováková")
    mutations.resolve_friend(workspace, anna["id"], "Terka", "dismiss")

    state = _upload(workspace, _row("Anna Nováková", ANNA, friends="Terka"))

    updated = _named(state, "Anna Nováková")
    assert updated["friends"] == [] and updated["unresolved_friend_names"] == []
    assert updated["friend_name_decisions"] == {"Terka": None}


def test_a_changed_or_removed_friend_name_drops_its_resolution(workspace):
    state = _with_unresolved_friend(workspace)

    changed = _upload(workspace, _row("Anna Nováková", ANNA, friends="Verča"))
    anna = _named(changed, "Anna Nováková")
    assert anna["friends"] == []
    assert anna["unresolved_friend_names"] == ["Verča"]  # enters the normal resolution UI
    assert not anna.get("friend_name_decisions")

    removed = _upload(workspace, _row("Anna Nováková", ANNA))
    anna = _named(removed, "Anna Nováková")
    assert anna["friends"] == [] and anna["unresolved_friend_names"] == []


def test_friends_resolved_by_the_survey_point_at_the_real_helper_ids(workspace, season):
    petr = _named(season, "Petr Svoboda")

    state = _upload(
        workspace,
        _row("Klára Malá", KLARA),
        _row("Anna Nováková", ANNA, friends="Petr Svoboda"),
        _row("Petr Svoboda", PETR),
    )

    assert _named(state, "Anna Nováková")["friends"] == [petr["id"]]
    assert _named(state, "Klára Malá")["friends"] == []


# -- changed answers, the summary and the Export gate -------------------------------------


def test_a_placed_helper_whose_answers_changed_materially_keeps_the_assignment_and_is_marked(workspace, season):
    anna = _named(season, "Anna Nováková")

    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Malá Strana", equipment="Notebook", opravovatel="Ne"),
        _row("Petr Svoboda", PETR),
        _row("Jana Dvořáková", JANA),
    )

    assert _placement(state, anna["id"]) == ("Karlov", "K1", "Zaloha")
    assert mutations.answers_changed_since_placed(state) == {anna["id"]: ["Building preference", "Preferences"]}


def test_answers_that_did_not_materially_change_leave_no_marker(workspace, season):
    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Karlov", equipment="Notebook", opravovatel="Ano", size="XL"),
        _row("Petr Svoboda", PETR, opravovatel="Nevadí"),  # a blank answer already counts as Nevadí
        _row("Jana Dvořáková", JANA),
    )

    assert mutations.answers_changed_since_placed(state) == {}


def test_an_unplaced_helper_with_changed_answers_is_updated_without_a_marker(workspace, season):
    mutations.delete_helper(workspace, _named(season, "Jana Dvořáková")["id"], confirmed=True)
    state = _upload(workspace, _row("Klára Malá", KLARA))
    klara = _named(state, "Klára Malá")

    state = _upload(workspace, _row("Klára Malá", KLARA, buildings="Karlov"))

    assert _named(state, "Klára Malá")["building_preferences"] == ["Karlov"]
    assert mutations.answers_changed_since_placed(state) == {}
    assert klara["id"] == _named(state, "Klára Malá")["id"]


def test_the_summary_lists_new_registrants_changed_answers_missing_helpers_and_uncertain_matches(workspace, season):
    anna, jana = _named(season, "Anna Nováková"), _named(season, "Jana Dvořáková")

    _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Malá Strana", equipment="Notebook", opravovatel="Ano"),
        _row("Petr Svoboda", PETR),
        _row("Klára Malá", KLARA),
        _row("Jana Dvořáková", "jana.jina@example.test"),
    )

    summary = mutations.upload_summary(workspace)
    new = {h["name"] for h in summary["new"]}
    assert new == {"Klára Malá", "Jana Dvořáková"}  # the second Jana is a different e-mail: a new registrant
    assert summary["changed"] == [
        {"helper_id": anna["id"], "name": "Anna Nováková", "fields": ["Building preference"]}
    ]
    assert summary["missing"] == [{"helper_id": jana["id"], "name": "Jana Dvořáková"}]
    assert [e["helper_name"] for e in summary["uncertain"]] == ["Jana Dvořáková"]


def test_the_summary_persists_until_dismissed(workspace, season):
    assert mutations.upload_summary(workspace) is None

    _upload(workspace, _row("Klára Malá", KLARA))
    assert mutations.get_state(workspace)["upload_summary"] is not None
    assert [h["name"] for h in mutations.upload_summary(workspace)["new"]] == ["Klára Malá"]

    mutations.dismiss_upload_summary(workspace)

    assert mutations.upload_summary(workspace) is None
    assert not mutations.get_state(workspace).get("upload_summary")


def test_a_second_reupload_before_dismissal_accumulates_new_registrants(workspace, season):
    _upload(workspace, _row("Klára Malá", KLARA))
    _upload(workspace, _row("Klára Malá", KLARA), _row("Eva Nová", "eva@example.test"))

    summary = mutations.upload_summary(workspace)
    assert {h["name"] for h in summary["new"]} == {"Klára Malá", "Eva Nová"}


def test_the_first_upload_of_a_season_builds_no_summary(workspace):
    _upload(workspace, _row("Anna Nováková", ANNA), label="2026-jaro")

    assert mutations.upload_summary(workspace) is None


def test_export_is_blocked_while_a_registrant_is_unassigned_and_lifts_once_they_are_placed(workspace, season):
    assert mutations.export_xlsx_bytes(workspace)[:2] == b"PK"

    state = _upload(workspace, _row("Klára Malá", KLARA))
    klara = _named(state, "Klára Malá")

    assert [h["id"] for h in mutations.unplaced_helpers(state)] == [klara["id"]]
    assert "Klára Malá" in " ".join(mutations.export_blockers(state))
    with pytest.raises(mutations.RosteringError, match="Klára Malá"):
        mutations.export_xlsx_bytes(workspace)

    mutations.move_helper(workspace, klara["id"], "Karlov", "K1", "Zaloha")

    assert mutations.export_xlsx_bytes(workspace)[:2] == b"PK"


def test_a_helper_who_cant_attend_never_blocks_the_export(workspace, season):
    state = _upload(workspace, _row("Klára Malá", KLARA))
    mutations.set_cant_attend(workspace, _named(state, "Klára Malá")["id"], True)

    assert mutations.export_xlsx_bytes(workspace)[:2] == b"PK"


def test_the_export_gate_leaves_the_stale_flag_alone(workspace, season):
    state = _upload(workspace, _row("Klára Malá", KLARA))

    assert mutations.stale_reasons(state) == []


# -- the marker -----------------------------------------------------------------------


def _changed_anna(workspace):
    return _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Malá Strana", equipment="Notebook", opravovatel="Ano"),
    )


def test_dismissing_the_summary_does_not_clear_the_marker(workspace, season):
    anna = _named(season, "Anna Nováková")
    _changed_anna(workspace)

    mutations.dismiss_upload_summary(workspace)

    assert list(mutations.answers_changed_since_placed(mutations.get_state(workspace))) == [anna["id"]]


def test_moving_the_helper_clears_the_marker(workspace, season):
    anna = _named(season, "Anna Nováková")
    _changed_anna(workspace)

    state = mutations.move_helper(workspace, anna["id"], "Malá Strana", "M1", "Zaloha")

    assert mutations.answers_changed_since_placed(state) == {}


def test_locking_the_helper_clears_the_marker(workspace, season):
    anna = _named(season, "Anna Nováková")
    _changed_anna(workspace)

    state = mutations.set_lock(workspace, anna["id"], True)

    assert mutations.answers_changed_since_placed(state) == {}


def test_a_full_solve_re_places_the_helper_and_clears_the_marker(workspace, season):
    _changed_anna(workspace)

    state = mutations.solve(workspace)

    assert mutations.answers_changed_since_placed(state) == {}


def test_a_marker_is_dropped_once_the_helper_has_no_assignment(workspace, season):
    anna = _named(season, "Anna Nováková")
    _changed_anna(workspace)

    state = mutations.set_cant_attend(workspace, anna["id"], True, confirmed=True)

    assert mutations.answers_changed_since_placed(state) == {}


# -- T-shirt sizes and hand-typed fields --------------------------------------------------


def test_a_hand_set_tshirt_size_survives_while_the_survey_answer_is_unchanged(workspace, season):
    anna = _named(season, "Anna Nováková")
    mutations.set_tshirt_size(workspace, anna["id"], "XL")

    state = _upload(workspace, _row("Anna Nováková", ANNA, buildings="Karlov", equipment="Notebook", opravovatel="Ano"))

    assert _named(state, "Anna Nováková")["tshirt_size"] == "XL"


def test_a_changed_survey_tshirt_answer_replaces_the_hand_set_size(workspace, season):
    anna = _named(season, "Anna Nováková")
    mutations.set_tshirt_size(workspace, anna["id"], "XL")

    state = _upload(workspace, _row("Anna Nováková", ANNA, size="S"))

    assert _named(state, "Anna Nováková")["tshirt_size"] == "S"


def test_an_unedited_size_follows_the_survey(workspace, season):
    state = _upload(workspace, _row("Anna Nováková", ANNA, size="L"))

    assert _named(state, "Anna Nováková")["tshirt_size"] == "L"


def test_a_field_typed_by_hand_wins_over_the_survey_row(workspace, season):
    anna = _named(season, "Anna Nováková")
    mutations.update_helper(workspace, anna["id"], building_preferences=["Malá Strana"])

    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, buildings="Karlov", equipment="Notebook, Fotoaparát", opravovatel="Ano"),
    )

    updated = _named(state, "Anna Nováková")
    assert updated["building_preferences"] == ["Malá Strana"]  # typed by hand
    assert updated["can_bring_camera"] is True  # everything else refreshes
    # ...and only what really changed is flagged: the survey's Building answer is ignored.
    assert mutations.answers_changed_since_placed(state) == {anna["id"]: ["Equipment"]}


def test_a_hand_added_helper_is_kept_and_not_listed_as_missing(workspace, season):
    added = mutations.add_helper(workspace, "Ruční Helper", "+420 777 000 111")
    added_id = added["helpers"][-1]["id"]

    state = _upload(workspace, _row("Anna Nováková", ANNA))

    assert any(h["id"] == added_id for h in state["helpers"])
    assert added_id not in {m["helper_id"] for m in mutations.upload_summary(workspace)["missing"]}


# -- recognition beyond one e-mail ---------------------------------------------------------


def test_a_row_under_an_email_an_earlier_season_knew_updates_the_linked_helper(workspace):
    _upload(workspace, _row("Klára Malá", "klara.stara@example.test"), label="2025-podzim")
    old_person = mutations.list_persons(workspace)[0]["person_id"]
    mutations.new_season(workspace)
    state = _upload(workspace, _row("Klára Nová", KLARA), label="2026-jaro")
    klara = _named(state, "Klára Nová")
    mutations.link_helper(workspace, klara["id"], old_person)

    state = _upload(workspace, _row("Klára Nová", "klara.stara@example.test", buildings="Karlov"))

    assert len(state["helpers"]) == 1
    assert state["helpers"][0]["id"] == klara["id"]
    assert state["helpers"][0]["building_preferences"] == ["Karlov"]


def test_a_reupload_recomputes_the_friend_pair_diagnostics_without_moving_anyone(workspace, season):
    petr = _named(season, "Petr Svoboda")
    anna = _named(season, "Anna Nováková")

    state = _upload(
        workspace,
        _row("Anna Nováková", ANNA, friends="Petr Svoboda", buildings="Karlov", equipment="Notebook", opravovatel="Ano"),
        _row("Petr Svoboda", PETR),
    )

    assert _named(state, "Anna Nováková")["friends"] == [petr["id"]]
    assert state["diagnostics"]["unsatisfied_friend_pairs"] == [[anna["id"], petr["id"]]]
