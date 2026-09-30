"""Tag import: copying an earlier Season's Tag tree into the open Season and
re-applying it to Returning helpers, plus the late "apply their Tags?" step after
an uncertain link is confirmed. Mutation-layer tests against a temp-dir workspace
holding several synthetic stored Seasons (never anything from data/)."""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.streamlit_app import mutations

_NAME_HEADER = "Tvoje jméno a příjmení"
_EMAIL_HEADER = "E-mailová adresa"

ANNA = "anna@example.test"
ANNA_NEW = "anna.new@example.test"
PETR = "petr@example.test"
JANA = "jana@example.test"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "seasons")


def _survey(rows) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 2, 1)] * len(rows),
            _NAME_HEADER: [name for name, _ in rows],
            _EMAIL_HEADER: [email for _, email in rows],
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


def _config(*buildings: str) -> list[dict]:
    return [
        {"name": b, "rooms": [{"name": f"{b}1", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}}
        for b in buildings
    ]


def _season(workspace, label, rows, buildings=("A", "B")):
    """Store a new Season (which stays open) with these ``(name, email)``
    Helpers and Buildings."""
    mutations.new_season(workspace)
    mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label=label)
    return mutations.put_config(workspace, _config(*buildings))


def _ids(workspace) -> dict[str, str]:
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def _open(workspace, label):
    return mutations.open_season(workspace, _ids(workspace)[label])


def _helper(state, name):
    return next(h for h in state["helpers"] if h["name"] == name)


def _tag(state, name):
    return next(t for t in state["tags"] if t["name"] == name)


def _tag_names(state, helper_name) -> list[str]:
    """The direct Tags of a Helper, by name, in the order they carry them."""
    by_id = {t["id"]: t["name"] for t in state["tags"]}
    return [by_id[t] for t in _helper(state, helper_name).get("tags", [])]


def _add_tag(workspace, name, **kwargs) -> int:
    state = mutations.add_tag(workspace, name, **kwargs)
    return _tag(state, name)["id"]


def _give(workspace, helper_name, *tag_ids):
    state = mutations.get_state(workspace)
    for tag_id in tag_ids:
        mutations.add_tag_to_helpers(workspace, tag_id, [_helper(state, helper_name)["id"]])


def _tags_section(summary) -> dict:
    return next(s for s in summary["sections"] if s["key"] == "tags")


def _source_id(workspace, label) -> str:
    return _ids(workspace)[label]


def _standard(workspace):
    """2025-podzim carries a small Tag tree; 2026-jaro (left open) has the same
    people, Anna under a different name but the same e-mail. Returns
    ``(tags in 2025-podzim by name)``."""
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR), ("Jana Dvořáková", JANA)])
    gchd = _add_tag(workspace, "GCHD", colour="#112233", note="school group")
    eight = _add_tag(
        workspace, "8.M", colour="#445566", note="class", parent_id=gchd, building_allow=["A"], role_deny=["Fotograf"]
    )
    vedouci = _add_tag(workspace, "Vedoucí", colour="#778899")
    _give(workspace, "Anna Nováková", eight)
    _give(workspace, "Petr Svoboda", vedouci, gchd)
    _season(workspace, "2026-jaro", [("Anna N.", ANNA), ("Petr Svoboda", PETR), ("Nový Helper", "new@example.test")])
    return {"GCHD": gchd, "8.M": eight, "Vedoucí": vedouci}


# -- the offer -------------------------------------------------------------------


def test_the_default_source_is_the_most_recent_earlier_season_and_any_earlier_one_can_be_picked(workspace):
    _season(workspace, "2024-podzim", [("Anna Nováková", ANNA)])
    _season(workspace, "2025-jaro", [("Anna Nováková", ANNA)])
    _season(workspace, "2027-jaro", [("Anna Nováková", ANNA)])
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)])

    offer = mutations.tag_import_offer(workspace)

    assert [s["label"] for s in offer["sources"]] == ["2025-jaro", "2024-podzim"]  # later Seasons are not offered
    assert offer["default_source_id"] == _source_id(workspace, "2025-jaro")
    assert mutations.default_import_source(workspace)["label"] == "2025-jaro"


def test_there_is_no_offer_source_for_the_first_season(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    assert mutations.import_sources(workspace) == []
    assert mutations.default_import_source(workspace) is None
    assert mutations.tag_import_offer(workspace)["default_source_id"] is None


def test_the_offer_is_section_based_and_starts_with_tags(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    assert [s["key"] for s in mutations.tag_import_offer(workspace)["sections"]] == ["tags", "forced_groups"]


def test_the_banner_shows_while_the_season_has_helpers_and_no_tags_and_an_earlier_season_has_tags(workspace):
    _standard(workspace)
    assert mutations.tag_import_offer(workspace)["banner"] is True

    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    assert mutations.tag_import_offer(workspace)["banner"] is False


def test_the_banner_does_not_wait_for_the_uncertain_match_review(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    _add_tag(workspace, "GCHD")
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA_NEW)])  # an unreviewed uncertain match
    assert mutations.get_uncertain_matches(workspace)

    assert mutations.tag_import_offer(workspace)["banner"] is True


def test_there_is_no_banner_when_no_earlier_season_has_tags_or_the_season_has_no_helpers(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)])
    assert mutations.tag_import_offer(workspace)["banner"] is False

    _open(workspace, "2025-podzim")
    _add_tag(workspace, "GCHD")
    mutations.new_season(workspace)
    assert mutations.tag_import_offer(workspace)["banner"] is False  # nothing open


def test_the_import_is_available_even_without_a_banner(workspace):
    _standard(workspace)
    mutations.add_tag(workspace, "Mine")  # the Season has Tags now: no banner, but importing still works

    assert mutations.tag_import_offer(workspace)["banner"] is False
    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    assert _tags_section(summary)["tags_created"]


# -- copying the tree ------------------------------------------------------------


def test_the_whole_tag_tree_is_copied_with_constraints_colour_note_and_unused_parents(workspace):
    _standard(workspace)

    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    state = mutations.get_state(workspace)
    assert sorted(t["name"] for t in state["tags"]) == ["8.M", "GCHD", "Vedoucí"]
    eight, gchd = _tag(state, "8.M"), _tag(state, "GCHD")
    assert eight["parent_id"] == gchd["id"]  # the parent structure survives, GCHD included though unused by 8.M
    assert (gchd["colour"], gchd["note"]) == ("#112233", "school group")
    assert (eight["colour"], eight["note"]) == ("#445566", "class")
    assert eight["building_allow"] == ["A"]
    assert eight["role_deny"] == ["Fotograf"]
    assert _tag(state, "Vedoucí")["parent_id"] is None


def test_the_copy_is_independent_of_the_source_and_the_source_is_never_modified(workspace):
    ids = _standard(workspace)
    source_file = workspace.root / "2025-podzim" / "state.json"
    before = source_file.read_bytes()

    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    state = mutations.get_state(workspace)
    mutations.update_tag(workspace, _tag(state, "8.M")["id"], name="9.M", note="changed", building_allow=["B"])
    mutations.delete_tag(workspace, _tag(state, "Vedoucí")["id"], confirmed=True)

    assert source_file.read_bytes() == before
    _open(workspace, "2025-podzim")
    source = mutations.get_state(workspace)
    assert (_tag(source, "8.M")["id"], _tag(source, "8.M")["note"], _tag(source, "8.M")["building_allow"]) == (
        ids["8.M"],
        "class",
        ["A"],
    )
    assert "Vedoucí" in [t["name"] for t in source["tags"]]


def test_constraint_entries_naming_a_missing_building_are_dropped_and_the_tag_stays(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)], buildings=("A", "B", "C"))
    _add_tag(workspace, "Wide", building_allow=["A", "C"], building_deny=["B"], role_allow=["Opravovatel"])
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)], buildings=("A",))

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    tag = _tag(mutations.get_state(workspace), "Wide")
    assert tag["building_allow"] == ["A"]
    assert tag["building_deny"] == []
    assert tag["role_allow"] == ["Opravovatel"]  # every Role exists in every Season
    dropped = _tags_section(summary)["dropped_constraint_entries"]
    assert sorted((d["tag"], d["field"], d["entry"]) for d in dropped) == [
        ("Wide", "building_allow", "C"),
        ("Wide", "building_deny", "B"),
    ]


def test_a_building_entry_is_matched_the_way_building_preferences_are(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)], buildings=("Karlín", "B"))
    _add_tag(workspace, "K", building_allow=["Karlín"])
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)], buildings=("Karlin", "B"))

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    assert _tags_section(summary)["dropped_constraint_entries"] == []
    assert _tag(mutations.get_state(workspace), "K")["building_allow"] == ["Karlín"]


# -- re-applying the Tags --------------------------------------------------------


def test_direct_tags_are_reapplied_to_confidently_linked_helpers_even_under_another_name(workspace):
    _standard(workspace)

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    state = mutations.get_state(workspace)
    assert _tag_names(state, "Anna N.") == ["8.M"]  # same e-mail, different name
    assert _tag_names(state, "Petr Svoboda") == ["Vedoucí", "GCHD"]
    assert _tag_names(state, "Nový Helper") == []
    assert sorted(_tags_section(summary)["helpers_tagged"]) == ["Anna N.", "Petr Svoboda"]


def test_implied_tags_are_not_copied_onto_helpers(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    state = mutations.get_state(workspace)
    anna = _helper(state, "Anna N.")
    assert [t for t in anna["tags"]] == [_tag(state, "8.M")["id"]]  # GCHD is only computed live
    assert mutations.helper_tags(state, anna["id"])["implied"] == [_tag(state, "GCHD")["id"]]


def test_an_unreviewed_uncertain_match_is_not_tagged_and_is_reported(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR)])
    eight = _add_tag(workspace, "8.M")
    _give(workspace, "Anna Nováková", eight)
    _give(workspace, "Petr Svoboda", eight)
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA_NEW), ("Petr Svoboda", PETR)])

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    state = mutations.get_state(workspace)
    assert _tag_names(state, "Anna Nováková") == []
    assert _tag_names(state, "Petr Svoboda") == ["8.M"]
    assert _tags_section(summary)["awaiting_review"] == ["Anna Nováková"]


def test_an_uncertain_match_whose_person_carried_no_tags_is_not_reported(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR)])
    eight = _add_tag(workspace, "8.M")
    _give(workspace, "Petr Svoboda", eight)
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA_NEW), ("Petr Svoboda", PETR)])

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    assert _tags_section(summary)["awaiting_review"] == []


def test_an_assignment_that_would_strand_a_helper_is_skipped_and_counted(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)], buildings=("A", "B", "C"))
    t1 = _add_tag(workspace, "T1", building_allow=["A", "B"])
    t2 = _add_tag(workspace, "T2", building_allow=["B", "C"])
    _give(workspace, "Anna Nováková", t1, t2)  # fine there: they may still go to B
    # In the new Season B is gone, so T1 allows only A and T2 only C: both together strand Anna.
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)], buildings=("A", "C"))

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    state = mutations.get_state(workspace)
    assert _tag_names(state, "Anna Nováková") == ["T1"]
    (skipped,) = _tags_section(summary)["skipped_assignments"]
    assert (skipped["helper"], skipped["tag"]) == ("Anna Nováková", "T2")
    assert "Building" in skipped["reason"]
    assert mutations.helper_allowed(state, _helper(state, "Anna Nováková")["id"])["buildings"] == ["A"]
    assert _tags_section(summary)["helpers_tagged"] == ["Anna Nováková"]  # still tagged, with T1


def test_the_summary_counts_what_happened(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR), ("Jana Dvořáková", JANA)])
    a = _add_tag(workspace, "A-tag")
    b = _add_tag(workspace, "B-tag", building_allow=["A", "Vanished"])
    _give(workspace, "Anna Nováková", a, b)
    _give(workspace, "Jana Dvořáková", a)
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA), ("Jana Dvořáková", "jana.new@example.test")])

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    assert summary["source"] == {"id": _source_id(workspace, "2025-podzim"), "label": "2025-podzim"}
    section = _tags_section(summary)
    assert sorted(section["tags_created"]) == ["A-tag", "B-tag"]
    assert section["helpers_tagged"] == ["Anna Nováková"]
    assert [d["entry"] for d in section["dropped_constraint_entries"]] == ["Vanished"]
    assert section["skipped_assignments"] == []
    assert section["awaiting_review"] == ["Jana Dvořáková"]
    assert section["lines"]  # the same, phrased for the UI


# -- origin, additive and repeated imports ---------------------------------------


def test_running_the_import_again_creates_nothing_twice(workspace):
    _standard(workspace)
    source = _source_id(workspace, "2025-podzim")
    mutations.import_from_season(workspace, source)
    once = mutations.get_state(workspace)

    summary = mutations.import_from_season(workspace, source)

    twice = mutations.get_state(workspace)
    assert [t["id"] for t in twice["tags"]] == [t["id"] for t in once["tags"]]
    assert _tags_section(summary)["tags_created"] == []
    assert _tags_section(summary)["helpers_tagged"] == []
    assert [h.get("tags") for h in twice["helpers"]] == [h.get("tags") for h in once["helpers"]]


def test_importing_from_another_season_is_additive(workspace):
    _season(workspace, "2025-jaro", [("Anna Nováková", ANNA)])
    _give(workspace, "Anna Nováková", _add_tag(workspace, "Old"))
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR)])
    _give(workspace, "Petr Svoboda", _add_tag(workspace, "Newer"))
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR)])

    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    mutations.import_from_season(workspace, _source_id(workspace, "2025-jaro"))

    state = mutations.get_state(workspace)
    assert sorted(t["name"] for t in state["tags"]) == ["Newer", "Old"]
    assert _tag_names(state, "Anna Nováková") == ["Old"]
    assert _tag_names(state, "Petr Svoboda") == ["Newer"]


def test_an_existing_tag_of_the_same_name_is_reused_and_left_as_it_is(workspace):
    _standard(workspace)
    mine = _add_tag(workspace, "8.M", colour="#abcdef", note="mine")

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    state = mutations.get_state(workspace)
    assert [t["name"] for t in state["tags"]].count("8.M") == 1
    tag = _tag(state, "8.M")
    assert (tag["id"], tag["colour"], tag["note"], tag["building_allow"]) == (mine, "#abcdef", "mine", [])
    assert _tag_names(state, "Anna N.") == ["8.M"]
    assert "8.M" not in _tags_section(summary)["tags_created"]


def test_imported_tags_remember_their_origin_through_a_rename(workspace):
    ids = _standard(workspace)
    source = _source_id(workspace, "2025-podzim")
    mutations.import_from_season(workspace, source)
    state = mutations.get_state(workspace)
    mutations.update_tag(workspace, _tag(state, "8.M")["id"], name="9.M")

    mutations.import_from_season(workspace, source)  # again: origin first, so no stray "8.M"

    state = mutations.get_state(workspace)
    assert sorted(t["name"] for t in state["tags"]) == ["9.M", "GCHD", "Vedoucí"]
    assert _tag(state, "9.M")["origins"] == [{"season_id": source, "tag_id": ids["8.M"]}]
    assert mutations.tag_origin_labels(state, _tag(state, "9.M")["id"]) == ["2025-podzim"]


def test_a_deliberately_deleted_imported_tag_comes_back_on_explicit_reimport_and_is_noted(workspace):
    _standard(workspace)
    source = _source_id(workspace, "2025-podzim")
    mutations.import_from_season(workspace, source)
    state = mutations.get_state(workspace)
    mutations.delete_tag(workspace, _tag(state, "Vedoucí")["id"], confirmed=True)
    assert _tag_names(mutations.get_state(workspace), "Petr Svoboda") == ["GCHD"]

    summary = mutations.import_from_season(workspace, source)

    state = mutations.get_state(workspace)
    section = _tags_section(summary)
    assert section["tags_restored"] == ["Vedoucí"]
    assert section["tags_created"] == []
    assert _tag_names(state, "Petr Svoboda") == ["GCHD", "Vedoucí"]
    assert any("restored" in line.lower() for line in section["lines"])

    # It is an ordinary imported Tag again: the next re-import does not report it.
    again = _tags_section(mutations.import_from_season(workspace, source))
    assert again["tags_restored"] == []
    assert [t["name"] for t in mutations.get_state(workspace)["tags"]].count("Vedoucí") == 1


def test_a_tag_deleted_by_hand_that_was_never_imported_is_simply_created_by_a_later_import(workspace):
    _standard(workspace)
    mine = _add_tag(workspace, "Vedoucí")  # name-matches the source's Tag
    mutations.delete_tag(workspace, mine, confirmed=True)

    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    assert "Vedoucí" in _tags_section(summary)["tags_created"]
    assert _tags_section(summary)["tags_restored"] == []


# -- after a link is confirmed late ----------------------------------------------


def _late_link_setup(workspace):
    """Anna is an unreviewed uncertain match at import time; returns her
    Helper id and her earlier Person's id."""
    ids = _standard_uncertain(workspace)
    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    state = mutations.get_state(workspace)
    anna = _helper(state, "Anna Nováková")
    (entry,) = mutations.get_uncertain_matches(workspace)
    return anna["id"], entry["candidates"][0]["person_id"], ids


def _standard_uncertain(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA), ("Petr Svoboda", PETR)])
    gchd = _add_tag(workspace, "GCHD")
    eight = _add_tag(workspace, "8.M", parent_id=gchd)
    _give(workspace, "Anna Nováková", eight)
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA_NEW), ("Petr Svoboda", PETR)])
    return {"GCHD": gchd, "8.M": eight}


def test_confirming_an_uncertain_link_after_the_import_offers_to_apply_their_tags(workspace):
    helper_id, person_id, _ = _late_link_setup(workspace)
    assert mutations.late_link_tag_offer(workspace, helper_id) is None  # not linked yet: nothing to apply

    mutations.link_helper(workspace, helper_id, person_id)

    offer = mutations.late_link_tag_offer(workspace, helper_id)
    assert offer["helper_name"] == "Anna Nováková"
    assert [(t["name"], t["source"]) for t in offer["tags"]] == [("8.M", "2025-podzim")]
    assert _tag_names(mutations.get_state(workspace), "Anna Nováková") == []  # only an offer so far

    result = mutations.apply_late_link_tags(workspace, helper_id)

    assert result["applied"] == ["8.M"]
    assert _tag_names(mutations.get_state(workspace), "Anna Nováková") == ["8.M"]
    assert mutations.late_link_tag_offer(workspace, helper_id) is None  # done


def test_the_late_link_offer_resolves_by_origin_first_so_a_renamed_class_is_used(workspace):
    helper_id, person_id, ids = _late_link_setup(workspace)
    state = mutations.get_state(workspace)
    mutations.update_tag(workspace, _tag(state, "8.M")["id"], name="9.M")
    _add_tag(workspace, "Unrelated")
    mutations.link_helper(workspace, helper_id, person_id)

    offer = mutations.late_link_tag_offer(workspace, helper_id)

    assert [t["name"] for t in offer["tags"]] == ["9.M"]
    mutations.apply_late_link_tags(workspace, helper_id)
    state = mutations.get_state(workspace)
    assert _tag_names(state, "Anna Nováková") == ["9.M"]
    assert "8.M" not in [t["name"] for t in state["tags"]]  # no stray tag was created


def test_the_late_link_offer_falls_back_to_the_name_when_no_origin_matches(workspace):
    _standard_uncertain(workspace)
    mutations.add_tag(workspace, "8.M")  # hand-made, no origin: only the name can match
    # The import name-matches the hand-made Tag and records its origin; drop the
    # origins again to prove the name path on its own.
    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    state = mutations.get_state(workspace)
    for tag in state["tags"]:
        tag.pop("origins", None)
    workspace.save(state)
    (entry,) = mutations.get_uncertain_matches(workspace)
    mutations.link_helper(workspace, _helper(state, "Anna Nováková")["id"], entry["candidates"][0]["person_id"])

    offer = mutations.late_link_tag_offer(workspace, _helper(state, "Anna Nováková")["id"])

    assert [t["name"] for t in offer["tags"]] == ["8.M"]


def test_the_late_link_does_not_recreate_a_deliberately_deleted_tag(workspace):
    helper_id, person_id, ids = _late_link_setup(workspace)
    state = mutations.get_state(workspace)
    mutations.delete_tag(workspace, _tag(state, "8.M")["id"], confirmed=True)
    mutations.link_helper(workspace, helper_id, person_id)

    assert mutations.late_link_tag_offer(workspace, helper_id) is None
    state = mutations.get_state(workspace)
    assert "8.M" not in [t["name"] for t in state["tags"]]


def test_a_link_to_a_season_that_was_never_imported_offers_nothing(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    _give(workspace, "Anna Nováková", _add_tag(workspace, "8.M"))
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA_NEW)])
    (entry,) = mutations.get_uncertain_matches(workspace)
    helper_id = entry["helper_id"]

    mutations.link_helper(workspace, helper_id, entry["candidates"][0]["person_id"])

    assert mutations.late_link_tag_offer(workspace, helper_id) is None


def test_a_late_tag_that_would_strand_the_helper_is_skipped(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    only_a = _add_tag(workspace, "OnlyA", building_allow=["A"])
    _give(workspace, "Anna Nováková", only_a)
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA_NEW)])
    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    state = mutations.get_state(workspace)
    only_b = _add_tag(workspace, "OnlyB", building_allow=["B"])
    helper_id = _helper(state, "Anna Nováková")["id"]
    mutations.add_tag_to_helpers(workspace, only_b, [helper_id])  # they now carry OnlyB by hand
    (entry,) = mutations.get_uncertain_matches(workspace)
    mutations.link_helper(workspace, helper_id, entry["candidates"][0]["person_id"])

    result = mutations.apply_late_link_tags(workspace, helper_id)

    assert result["applied"] == []
    assert [s["tag"] for s in result["skipped"]] == ["OnlyA"]
    assert _tag_names(mutations.get_state(workspace), "Anna Nováková") == ["OnlyB"]


# -- the extension point ---------------------------------------------------------


def test_further_sections_plug_into_the_same_offer_and_import(workspace, monkeypatch):
    _standard(workspace)
    monkeypatch.setattr(mutations, "_IMPORT_SECTIONS", list(mutations._IMPORT_SECTIONS))
    seen = []

    def run(context):
        seen.append((context.source["label"], context.season["label"], len(context.source_state["helpers"])))
        return {"copied": 2, "lines": ["Copied 2 things"]}

    mutations.register_import_section(mutations.ImportSection("things", "Other things", run))

    assert [s["key"] for s in mutations.tag_import_offer(workspace)["sections"]] == ["tags", "forced_groups", "things"]
    summary = mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    assert [s["key"] for s in summary["sections"]] == ["tags", "forced_groups", "things"]
    assert summary["sections"][2]["copied"] == 2
    assert summary["sections"][2]["title"] == "Other things"
    assert seen == [("2025-podzim", "2026-jaro", 3)]
    assert _tag_names(mutations.get_state(workspace), "Anna N.") == ["8.M"]  # the Tags section still ran


def test_a_section_key_can_only_be_registered_once(workspace):
    with pytest.raises(ValueError):
        mutations.register_import_section(mutations.ImportSection("tags", "Again", lambda context: {}))


# -- refusals --------------------------------------------------------------------


def test_the_import_needs_an_open_season_and_an_earlier_stored_source(workspace):
    _season(workspace, "2025-podzim", [("Anna Nováková", ANNA)])
    _season(workspace, "2026-jaro", [("Anna Nováková", ANNA)])
    before = mutations.get_state(workspace)

    for bad in (_source_id(workspace, "2026-jaro"), "no-such-season"):  # itself, unknown
        with pytest.raises(mutations.RosteringError):
            mutations.import_from_season(workspace, bad)
    _open(workspace, "2025-podzim")
    with pytest.raises(mutations.RosteringError):  # a later Season is not a source
        mutations.import_from_season(workspace, _source_id(workspace, "2026-jaro"))
    mutations.new_season(workspace)
    with pytest.raises(mutations.RosteringError):
        mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))

    _open(workspace, "2026-jaro")
    assert mutations.get_state(workspace) == before


def test_tag_imports_are_part_of_versions_and_cleared_by_start_over(workspace):
    _standard(workspace)
    mutations.save_version(workspace, "before import")
    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    assert mutations.get_state(workspace)["tags"]

    slug = mutations.list_versions(workspace)[0]["slug"]
    restored = mutations.restore_version(workspace, slug)
    assert restored["tags"] == []
    assert restored["tag_imports"] == {}

    mutations.import_from_season(workspace, _source_id(workspace, "2025-podzim"))
    blank = mutations.reset_workspace(workspace)
    assert blank["tags"] == [] and blank["tag_imports"] == {}
