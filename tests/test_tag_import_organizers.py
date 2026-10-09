"""Tag import for Organizers (see CONTEXT.md "Tag import", "Organizer"): the source
Season's directly carried Tags are re-applied to every confidently linked Person
of the open Season whether they are a Helper or an Organizer there (and were one
or the other in the source, so a promoted Helper is tagged from their Helper
Tags), the skip-if-it-would-strand rule is Building-axis only for an Organizer,
and the late-confirmed link offers the Tags too. Mutation-layer tests against a
temp-dir workspace with synthetic Seasons (never anything from data/)."""
import pytest

from rostering.domain import Role
from rostering.webapp import mutations
from tests import tag_rules
from tests.test_tag_import import (  # noqa: F401  (workspace is a fixture)
    ANNA,
    ANNA_NEW,
    PETR,
    _add_tag,
    _give,
    _helper,
    _open,
    _season,
    _source_id,
    _tag,
    _tags_section,
    workspace,
)


def _organizer(state, name):
    return next(o for o in state["organizers"] if o["name"] == name)


def _org_tag_names(state, name) -> list[str]:
    """The direct Tags of an Organizer, by name, in the order they carry them."""
    by_id = {t["id"]: t["name"] for t in state["tags"]}
    return [by_id[t] for t in _organizer(state, name).get("tags", [])]


def _add_organizer(workspace, name, email=None) -> int:
    return mutations.add_organizer(workspace, name, email)["organizers"][-1]["id"]


def _give_organizer(workspace, name, *tag_ids):
    state = mutations.get_state(workspace)
    for tag_id in tag_ids:
        mutations.add_tag_to_helpers(workspace, tag_id, [], organizer_ids=[_organizer(state, name)["id"]])


def _standard(workspace):
    """2025-podzim: Organizer Anna carries 8.M (under GCHD) and Petr (a Helper)
    carries Vedoucí. 2026-jaro (left open): Organizer "Anna N." with Anna's
    e-mail, Petr an Organizer too now (promoted from a Helper) and a new one."""
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková", ANNA)
    gchd = _add_tag(workspace, "GCHD", colour="#112233")
    eight = _add_tag(workspace, "8.M", parent_id=gchd, building_allow=["A"])
    vedouci = _add_tag(workspace, "Vedoucí")
    _give_organizer(workspace, "Anna Nováková", eight)
    _give(workspace, "Petr Svoboda", vedouci, gchd)
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna N.", ANNA)
    _add_organizer(workspace, "Nový Organizátor", "new@example.test")
    petr = _helper(mutations.get_state(workspace), "Petr Svoboda")["id"]
    mutations.promote_helper(workspace, petr)


def _import(workspace, label="2025-podzim"):
    return mutations.import_from_season(workspace, _source_id(workspace, label))


# -- re-applying the Tags to Organizers ------------------------------------------


def test_an_organizers_direct_tags_are_reapplied_to_the_confidently_linked_organizer_under_another_name(workspace):
    _standard(workspace)

    summary = _import(workspace)

    state = mutations.get_state(workspace)
    assert _org_tag_names(state, "Anna N.") == ["8.M"]  # same e-mail, different name
    assert _org_tag_names(state, "Nový Organizátor") == []
    section = _tags_section(summary)
    assert "Anna N." in section["organizers_tagged"]
    assert "Nový Organizátor" not in section["organizers_tagged"]


def test_implied_tags_are_not_copied_onto_organizers(workspace):
    _standard(workspace)
    _import(workspace)

    state = mutations.get_state(workspace)
    anna = _organizer(state, "Anna N.")
    assert anna["tags"] == [_tag(state, "8.M")["id"]]  # GCHD is only computed live
    assert mutations.organizer_tags(state, anna["id"])["implied"] == [_tag(state, "GCHD")["id"]]


def test_a_helper_promoted_to_organizer_gets_their_helper_tags_from_the_source(workspace):
    _standard(workspace)

    summary = _import(workspace)

    state = mutations.get_state(workspace)
    assert _org_tag_names(state, "Petr Svoboda") == ["Vedoucí", "GCHD"]  # Helper Tags of 2025-podzim, now an Organizer
    assert sorted(_tags_section(summary)["organizers_tagged"]) == ["Anna N.", "Petr Svoboda"]
    assert _tags_section(summary)["helpers_tagged"] == []


def test_a_source_organizer_who_is_a_helper_now_gives_the_helper_their_tags(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková", ANNA)
    _give_organizer(workspace, "Anna Nováková", _add_tag(workspace, "8.M"))
    _season(workspace, "2026-jaro", [("Anna N.", ANNA), ("Petr Svoboda", PETR)])

    summary = _import(workspace)

    state = mutations.get_state(workspace)
    by_id = {t["id"]: t["name"] for t in state["tags"]}
    assert [by_id[t] for t in _helper(state, "Anna N.")["tags"]] == ["8.M"]
    assert _tags_section(summary)["helpers_tagged"] == ["Anna N."]
    assert _tags_section(summary)["organizers_tagged"] == []


def test_running_the_import_again_tags_organizers_only_once(workspace):
    _standard(workspace)
    _import(workspace)
    once = mutations.get_state(workspace)

    summary = _import(workspace)

    twice = mutations.get_state(workspace)
    assert [o.get("tags") for o in twice["organizers"]] == [o.get("tags") for o in once["organizers"]]
    assert _tags_section(summary)["organizers_tagged"] == []


def test_a_tag_an_organizer_gained_by_hand_is_kept_when_the_import_adds_the_rest(workspace):
    _standard(workspace)
    mine = _add_tag(workspace, "Mine")
    _give_organizer(workspace, "Anna N.", mine)

    _import(workspace)

    assert _org_tag_names(mutations.get_state(workspace), "Anna N.") == ["Mine", "8.M"]


def test_the_source_season_is_not_modified_by_tagging_organizers(workspace):
    _standard(workspace)
    source_file = workspace.root / "2025-podzim" / "state.json"
    before = source_file.read_bytes()

    _import(workspace)

    assert source_file.read_bytes() == before


# -- the skip rule ---------------------------------------------------------------


def test_an_assignment_that_would_strand_an_organizer_on_buildings_is_skipped_and_counted(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)], buildings=("A", "B", "C"))
    _add_organizer(workspace, "Anna Nováková", ANNA)
    t1 = _add_tag(workspace, "T1", building_allow=["A", "B"])
    t2 = _add_tag(workspace, "T2", building_allow=["B", "C"])
    _give_organizer(workspace, "Anna Nováková", t1, t2)  # fine there: they may still be in B
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)], buildings=("A", "C"))  # B is gone
    _add_organizer(workspace, "Anna Nováková", ANNA)

    summary = _import(workspace)

    state = mutations.get_state(workspace)
    assert _org_tag_names(state, "Anna Nováková") == ["T1"]
    (skipped,) = _tags_section(summary)["skipped_assignments"]
    assert (skipped["organizer"], skipped["tag"]) == ("Anna Nováková", "T2")
    assert "budovu" in skipped["reason"]
    assert mutations.organizer_allowed(state, _organizer(state, "Anna Nováková")["id"])["buildings"] == ["A"]
    assert _tags_section(summary)["organizers_tagged"] == ["Anna Nováková"]  # still tagged, with T1


def test_the_role_axis_never_skips_an_organizer(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková", ANNA)
    no_roles = _add_tag(workspace, "NoRoles", role_deny=[role.name for role in Role])  # a dead end for a Helper only
    _give_organizer(workspace, "Anna Nováková", no_roles)
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková", ANNA)

    summary = _import(workspace)

    assert _org_tag_names(mutations.get_state(workspace), "Anna Nováková") == ["NoRoles"]
    assert _tags_section(summary)["skipped_assignments"] == []


def test_the_same_role_dead_end_still_skips_a_helper(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    no_roles = _add_tag(workspace, "NoRoles", role_deny=[role.name for role in Role])
    state = mutations.get_state(workspace)
    state["helpers"][0]["tags"] = [no_roles]  # a stored state may hold what an edit refuses
    workspace.save(state)
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)])

    summary = _import(workspace)

    (skipped,) = _tags_section(summary)["skipped_assignments"]
    assert (skipped["helper"], skipped["tag"]) == ("Petr Svoboda", "NoRoles")
    assert "roli" in skipped["reason"]


# -- awaiting review -------------------------------------------------------------


def _uncertain_setup(workspace):
    """An Organizer created by hand without e-mail in both Seasons: the earlier
    one carries 8.M, the current one is only an uncertain name match."""
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková")
    gchd = _add_tag(workspace, "GCHD")
    eight = _add_tag(workspace, "8.M", parent_id=gchd)
    _give_organizer(workspace, "Anna Nováková", eight)
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)])
    organizer_id = _add_organizer(workspace, "Anna Nováková")
    return organizer_id


def test_an_unreviewed_uncertain_organizer_is_not_tagged_and_is_reported_as_awaiting_review(workspace):
    _uncertain_setup(workspace)
    assert mutations.get_uncertain_organizer_matches(workspace)

    summary = _import(workspace)

    state = mutations.get_state(workspace)
    assert _org_tag_names(state, "Anna Nováková") == []
    section = _tags_section(summary)
    assert section["organizers_awaiting_review"] == ["Anna Nováková"]
    assert section["awaiting_review"] == []
    assert any("Organizátoři čekající na posouzení" in line and "Anna Nováková" in line for line in section["lines"])


def test_an_uncertain_organizer_whose_person_carried_no_tags_is_not_reported(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková")
    _add_tag(workspace, "8.M")
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková")

    assert _tags_section(_import(workspace))["organizers_awaiting_review"] == []


def test_an_uncertain_helper_whose_person_was_an_organizer_before_is_awaiting_review(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková", ANNA)
    _give_organizer(workspace, "Anna Nováková", _add_tag(workspace, "8.M"))
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR), ("Anna Nováková", ANNA_NEW)])

    summary = _import(workspace)

    assert _tag_names_of_helper(workspace, "Anna Nováková") == []
    assert _tags_section(summary)["awaiting_review"] == ["Anna Nováková"]


def _tag_names_of_helper(workspace, name) -> list[str]:
    state = mutations.get_state(workspace)
    by_id = {t["id"]: t["name"] for t in state["tags"]}
    return [by_id[t] for t in _helper(state, name).get("tags", [])]


# -- the late "apply their Tags?" step -------------------------------------------


def test_confirming_an_organizers_link_after_the_import_offers_to_apply_their_tags(workspace):
    organizer_id = _uncertain_setup(workspace)
    _import(workspace)
    assert mutations.late_link_organizer_tag_offer(workspace, organizer_id) is None  # not linked yet
    (entry,) = mutations.get_uncertain_organizer_matches(workspace)

    mutations.link_organizer(workspace, organizer_id, entry["candidates"][0]["person_id"])

    offer = mutations.late_link_organizer_tag_offer(workspace, organizer_id)
    assert offer["organizer_id"] == organizer_id
    assert offer["organizer_name"] == "Anna Nováková"
    assert [(t["name"], t["source"]) for t in offer["tags"]] == [("8.M", "2025-podzim")]
    assert _org_tag_names(mutations.get_state(workspace), "Anna Nováková") == []  # only an offer so far

    result = mutations.apply_late_link_organizer_tags(workspace, organizer_id)

    assert result["applied"] == ["8.M"]
    assert result["skipped"] == []
    assert _org_tag_names(mutations.get_state(workspace), "Anna Nováková") == ["8.M"]
    assert mutations.late_link_organizer_tag_offer(workspace, organizer_id) is None  # done


def test_the_late_organizer_offer_resolves_by_origin_and_never_recreates_a_deleted_tag(workspace):
    organizer_id = _uncertain_setup(workspace)
    _import(workspace)
    state = mutations.get_state(workspace)
    tag_rules.update_tag(workspace, _tag(state, "8.M")["id"], name="9.M")
    (entry,) = mutations.get_uncertain_organizer_matches(workspace)
    mutations.link_organizer(workspace, organizer_id, entry["candidates"][0]["person_id"])

    offer = mutations.late_link_organizer_tag_offer(workspace, organizer_id)
    assert [t["name"] for t in offer["tags"]] == ["9.M"]  # origin first: the renamed Tag, no stray 8.M

    mutations.delete_tag(workspace, _tag(mutations.get_state(workspace), "9.M")["id"], confirmed=True)
    assert mutations.late_link_organizer_tag_offer(workspace, organizer_id) is None
    assert "8.M" not in [t["name"] for t in mutations.get_state(workspace)["tags"]]


def test_a_late_tag_that_would_strand_the_organizer_is_skipped(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková")
    _give_organizer(workspace, "Anna Nováková", _add_tag(workspace, "OnlyA", building_allow=["A"]))
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR)])
    organizer_id = _add_organizer(workspace, "Anna Nováková")
    _import(workspace)
    only_b = _add_tag(workspace, "OnlyB", building_allow=["B"])
    mutations.add_tag_to_helpers(workspace, only_b, [], organizer_ids=[organizer_id])  # carried by hand
    (entry,) = mutations.get_uncertain_organizer_matches(workspace)
    mutations.link_organizer(workspace, organizer_id, entry["candidates"][0]["person_id"])

    result = mutations.apply_late_link_organizer_tags(workspace, organizer_id)

    assert result["applied"] == []
    assert [s["tag"] for s in result["skipped"]] == ["OnlyA"]
    assert _org_tag_names(mutations.get_state(workspace), "Anna Nováková") == ["OnlyB"]


def test_a_helper_linked_late_to_a_person_who_was_an_organizer_is_offered_their_tags(workspace):
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková", ANNA)
    _give_organizer(workspace, "Anna Nováková", _add_tag(workspace, "8.M"))
    _season(workspace, "2026-jaro", [("Petr Svoboda", PETR), ("Anna Nováková", ANNA_NEW)])
    _import(workspace)
    helper_id = _helper(mutations.get_state(workspace), "Anna Nováková")["id"]
    (entry,) = mutations.get_uncertain_matches(workspace)
    mutations.link_helper(workspace, helper_id, entry["candidates"][0]["person_id"])

    offer = mutations.late_link_tag_offer(workspace, helper_id)
    assert [(t["name"], t["source"]) for t in offer["tags"]] == [("8.M", "2025-podzim")]
    assert mutations.apply_late_link_tags(workspace, helper_id)["applied"] == ["8.M"]
    assert _tag_names_of_helper(workspace, "Anna Nováková") == ["8.M"]


def test_the_late_organizer_offer_refuses_an_unknown_organizer(workspace):
    _standard(workspace)
    with pytest.raises(mutations.RosteringError):
        mutations.late_link_organizer_tag_offer(workspace, 999)
    with pytest.raises(mutations.RosteringError):
        mutations.apply_late_link_organizer_tags(workspace, 999)


# -- Class promotion with Organizer carriers -------------------------------------


def test_class_promotion_and_late_links_keep_working_for_organizer_carriers(workspace):
    _season(workspace, "2025-jaro", [("Petr Svoboda", PETR)])
    _add_organizer(workspace, "Anna Nováková")
    _add_organizer(workspace, "Jana Dvořáková", "jana@example.test")
    eight = _add_tag(workspace, "8.M")
    _give_organizer(workspace, "Anna Nováková", eight)
    _give_organizer(workspace, "Jana Dvořáková", eight)
    _season(workspace, "2025-podzim", [("Petr Svoboda", PETR)])
    anna_id = _add_organizer(workspace, "Anna Nováková")  # an uncertain match
    _add_organizer(workspace, "Jana D.", "jana@example.test")  # a confident one

    summary = _import(workspace, "2025-jaro")
    assert summary["promotion_prompt"] is True
    assert _org_tag_names(mutations.get_state(workspace), "Jana D.") == ["8.M"]  # tagged by the import

    offer = mutations.class_promotion_offer(workspace)
    assert [(s["name"], s["target"]) for s in offer["suggestions"]] == [("8.M", "9.M")]
    mutations.apply_class_promotion(workspace, {offer["suggestions"][0]["tag_id"]: "9.M"})
    assert _org_tag_names(mutations.get_state(workspace), "Jana D.") == ["9.M"]  # renamed in place, carriers stay

    (entry,) = mutations.get_uncertain_organizer_matches(workspace)
    mutations.link_organizer(workspace, anna_id, entry["candidates"][0]["person_id"])
    late = mutations.late_link_organizer_tag_offer(workspace, anna_id)
    assert [t["name"] for t in late["tags"]] == ["9.M"]  # by origin: the promoted name, no stray "8.M"
    mutations.apply_late_link_organizer_tags(workspace, anna_id)
    state = mutations.get_state(workspace)
    assert _org_tag_names(state, "Anna Nováková") == ["9.M"]
    assert [t["name"] for t in state["tags"]] == ["9.M"]
