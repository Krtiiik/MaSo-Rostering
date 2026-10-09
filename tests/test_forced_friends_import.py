"""Forced friends groups in the "Import from previous Season" offer, as its second
section after Tags (see CONTEXT.md: Forced friends group, Tag import).

Mutation-layer tests against a temp-dir workspace holding several synthetic stored
Seasons (never anything from data/): the overview, the per-group tick, recognized
people, placeholders for the missing, independent copies, repeat imports and the
result summary.
"""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import forced_groups, mutations
from tests import tag_rules

_NAME_HEADER = "Tvoje jméno a příjmení"
_EMAIL_HEADER = "E-mailová adresa"

ANNA = "anna@example.test"
PETR = "petr@example.test"
JANA = "jana@example.test"
KAREL = "karel@example.test"


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
    """Store a new Season (which stays open) with these ``(name, email)`` Helpers."""
    mutations.new_season(workspace)
    mutations.upload_responses(workspace, _survey(rows), "s.xlsx", label=label)
    return mutations.put_config(workspace, _config(*buildings))


def _ids(workspace) -> dict[str, str]:
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def _source_id(workspace, label="2025-podzim") -> str:
    return _ids(workspace)[label]


def _person(state, name) -> str:
    return next(h for h in state["helpers"] if h["name"] == name)["person_id"]


def _groups_section(summary) -> dict:
    return next(s for s in summary["sections"] if s["key"] == "forced_groups")


def _group(state, name) -> dict:
    return next(g for g in forced_groups.list_groups(state) if g["name"] == name)


def _member(group, name) -> dict:
    return next(m for m in group["members"] if m["name"] == name)


def _standard(workspace):
    """2025-podzim holds Anna, Petr, Jana and Karel with three groups: Rodina
    (Anna, Petr, Jana; Building and Room), Dvojice (Anna, Jana; Room) and
    Cizinci (Jana, Karel; Building). 2026-jaro (left open) has Anna and Petr
    (same e-mails, Anna under another name) and a newcomer; Jana and Karel did
    not return."""
    _season(
        workspace,
        "2025-podzim",
        [("Anna Nováková", ANNA), ("Petr Svoboda", PETR), ("Jana Dvořáková", JANA), ("Karel Nový", KAREL)],
    )
    state = mutations.get_state(workspace)
    people = {n: _person(state, n) for n in ("Anna Nováková", "Petr Svoboda", "Jana Dvořáková", "Karel Nový")}
    anna, petr, jana, karel = people.values()
    forced_groups.add_group(workspace, "Rodina", [anna, petr, jana], ["building", "room"])
    forced_groups.add_group(workspace, "Dvojice", [anna, jana], ["room"])
    forced_groups.add_group(workspace, "Cizinci", [jana, karel], ["building"])
    _season(workspace, "2026-jaro", [("Anna N.", ANNA), ("Petr Svoboda", PETR), ("Nový Helper", "new@example.test")])
    return people


# -- the offer and the overview --------------------------------------------------


def test_forced_friends_groups_are_the_second_section_of_the_offer(workspace):
    _standard(workspace)

    sections = mutations.tag_import_offer(workspace)["sections"]

    assert [s["key"] for s in sections] == ["tags", "forced_groups"]
    assert sections[1]["title"] == "Vynucené skupinky kamarádů"


def test_the_overview_lists_each_groups_returning_and_missing_members(workspace):
    _standard(workspace)

    overview = mutations.import_overview(workspace, _source_id(workspace))

    assert [s["key"] for s in overview["sections"]] == ["forced_groups"]  # Tags has nothing to choose
    groups = {g["name"]: g for g in overview["sections"][0]["groups"]}
    assert set(groups) == {"Rodina", "Dvojice", "Cizinci"}
    rodina = groups["Rodina"]
    assert rodina["rules"] == [{"kind": "share", "axis": "building"}, {"kind": "share", "axis": "room"}]
    assert rodina["rule_texts"] == ["musí sdílet budovu", "musí sdílet místnost"]
    assert rodina["returning"] == ["Anna N.", "Petr Svoboda"]  # named as they are in this Season
    assert rodina["missing"] == ["Jana Dvořáková"]
    assert rodina["importable"] is True and rodina["already_present"] is False
    assert groups["Dvojice"]["returning"] == ["Anna N."] and groups["Dvojice"]["missing"] == ["Jana Dvořáková"]
    assert groups["Cizinci"]["returning"] == [] and groups["Cizinci"]["importable"] is False


def test_the_overview_says_which_groups_are_already_in_this_season(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))

    groups = {g["name"]: g for g in mutations.import_overview(workspace, _source_id(workspace))["sections"][0]["groups"]}

    assert groups["Rodina"]["already_present"] and groups["Dvojice"]["already_present"]
    assert not groups["Cizinci"]["already_present"]


def test_the_overview_refuses_what_the_import_refuses(workspace):
    _standard(workspace)
    with pytest.raises(mutations.RosteringError):
        mutations.import_overview(workspace, "no-such-season")


# -- what is imported ------------------------------------------------------------


def test_every_group_with_a_recognized_person_is_imported_with_placeholders_for_the_missing(workspace):
    _standard(workspace)

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    state = mutations.get_state(workspace)
    assert sorted(g["name"] for g in state["forced_groups"]) == ["Dvojice", "Rodina"]  # Cizinci: nobody returned
    rodina = _group(state, "Rodina")
    assert rodina["rules"] == [{"kind": "share", "axis": "building"}, {"kind": "share", "axis": "room"}]
    assert rodina["status"] == "active"  # two of its three are here
    assert [(m["name"], m["state"]) for m in rodina["members"]] == [
        ("Anna N.", "active"),
        ("Petr Svoboda", "active"),
        ("Jana Dvořáková", "not_registered"),  # a dim placeholder, in the group all the same
    ]
    assert _groups_section(summary)["groups_imported"] == ["Rodina", "Dvojice"]


def test_a_group_left_with_fewer_than_two_is_imported_inactive(workspace):
    _standard(workspace)

    mutations.import_from_season(workspace, _source_id(workspace))

    dvojice = _group(mutations.get_state(workspace), "Dvojice")
    assert dvojice["active"] is False and dvojice["status"] == "dormant"
    assert "Jana Dvořáková není v tomto ročníku registrován(a)" in dvojice["reason"]
    assert _member(dvojice, "Jana Dvořáková")["state"] == "not_registered"


def test_a_missing_member_becomes_live_when_they_register_later_and_are_recognized(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))

    # Jana registers now; the same e-mail links her to her earlier Person.
    mutations.upload_responses(
        workspace, _survey([("Anna N.", ANNA), ("Petr Svoboda", PETR), ("Jana D.", JANA)]), "s.xlsx"
    )

    dvojice = _group(mutations.get_state(workspace), "Dvojice")
    assert _member(dvojice, "Jana D.")["state"] == "active"
    assert dvojice["active"] is True


def test_an_unreviewed_link_is_not_carried_and_confirming_it_later_makes_the_person_live(workspace):
    people = _standard(workspace)
    # In this Season Jana turns up under a different e-mail: only an uncertain, same-name match.
    mutations.upload_responses(
        workspace,
        _survey([("Anna N.", ANNA), ("Petr Svoboda", PETR), ("Jana Dvořáková", "jana.new@example.test")]),
        "s.xlsx",
    )
    state = mutations.get_state(workspace)
    jana_here = next(h for h in state["helpers"] if h["name"] == "Jana Dvořáková")
    assert mutations.get_uncertain_matches(workspace)  # awaiting review

    mutations.import_from_season(workspace, _source_id(workspace))

    # Unreviewed links are not carried: she is still a placeholder.
    dvojice = _group(mutations.get_state(workspace), "Dvojice")
    assert _member(dvojice, "Jana Dvořáková")["state"] == "not_registered"
    assert dvojice["status"] == "dormant"

    # Confirming the link afterwards makes her the group's live member; no second import is needed.
    mutations.link_helper(workspace, jana_here["id"], people["Jana Dvořáková"])
    dvojice = _group(mutations.get_state(workspace), "Dvojice")
    assert _member(dvojice, "Jana Dvořáková")["state"] == "active"
    assert dvojice["status"] == "active"

    # ... and importing again does not double the groups already here (Cizinci, whose Jana is
    # recognized now, is the only new one).
    summary = mutations.import_from_season(workspace, _source_id(workspace))
    assert _groups_section(summary)["groups_imported"] == ["Cizinci"]
    assert _groups_section(summary)["groups_skipped"] == ["Rodina", "Dvojice"]
    assert sorted(g["name"] for g in mutations.get_state(workspace)["forced_groups"]) == [
        "Cizinci",
        "Dvojice",
        "Rodina",
    ]


def test_a_returning_person_who_is_an_organizer_now_is_recognized_and_keeps_the_role_badge(workspace):
    people = _standard(workspace)
    mutations.open_season(workspace, _source_id(workspace))
    forced_groups.add_group(workspace, "Tým", list(people.values())[:3], ["role"])  # Anna, Petr, Jana
    mutations.open_season(workspace, _ids(workspace)["2026-jaro"])
    mutations.add_organizer(workspace, "Jana Dvořáková", JANA)  # the same Person, an Organizer here

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    state = mutations.get_state(workspace)
    section = _groups_section(summary)
    assert "Tým" in section["groups_imported"]
    assert "Cizinci" in section["groups_imported"]  # Jana is recognized there too
    team = _group(state, "Tým")
    assert _member(team, "Jana Dvořáková")["kind"] == "organizer"  # recognized: no placeholder
    assert team["badges"] == ["Role se na Jana Dvořáková neuplatní"]  # kept, the Role axis not applied to her
    assert _member(_group(state, "Cizinci"), "Karel Nový")["state"] == "not_registered"


def test_an_unticked_group_is_left_out(workspace):
    _standard(workspace)
    overview = mutations.import_overview(workspace, _source_id(workspace))["sections"][0]["groups"]
    rodina = next(g for g in overview if g["name"] == "Rodina")

    summary = mutations.import_from_season(workspace, _source_id(workspace), {"forced_groups": [rodina["group_id"]]})

    assert [g["name"] for g in mutations.get_state(workspace)["forced_groups"]] == ["Rodina"]
    assert _groups_section(summary)["groups_left_out"] == ["Dvojice"]


def test_a_group_without_a_recognized_person_cannot_be_ticked_in(workspace):
    _standard(workspace)
    overview = mutations.import_overview(workspace, _source_id(workspace))["sections"][0]["groups"]
    cizinci = next(g for g in overview if g["name"] == "Cizinci")

    summary = mutations.import_from_season(workspace, _source_id(workspace), {"forced_groups": [cizinci["group_id"]]})

    assert mutations.get_state(workspace)["forced_groups"] == []
    assert _groups_section(summary)["groups_without_returning"] == ["Cizinci"]


def test_ticking_nothing_imports_no_group_but_still_imports_tags(workspace):
    _standard(workspace)

    summary = mutations.import_from_season(workspace, _source_id(workspace), {"forced_groups": []})

    assert mutations.get_state(workspace)["forced_groups"] == []
    assert [s["key"] for s in summary["sections"]] == ["tags", "forced_groups"]


# -- copies and repeats ----------------------------------------------------------


def test_imported_groups_are_independent_copies_and_the_source_is_never_edited(workspace):
    _standard(workspace)
    source_before = workspace.stored_state(_source_id(workspace))

    mutations.import_from_season(workspace, _source_id(workspace))
    copy = _group(mutations.get_state(workspace), "Rodina")
    forced_groups.update_group(workspace, copy["id"], name="Rodina 2026", person_ids=[copy["members"][0]["person_id"]])
    forced_groups.dissolve_group(workspace, _group(mutations.get_state(workspace), "Dvojice")["id"])

    assert workspace.stored_state(_source_id(workspace)) == source_before  # untouched, id counters included
    assert sorted(g["name"] for g in workspace.stored_state(_source_id(workspace))["forced_groups"]) == [
        "Cizinci",
        "Dvojice",
        "Rodina",
    ]


def test_a_copy_gets_its_own_id_in_this_seasons_numbering(workspace):
    _standard(workspace)
    forced_groups.add_group(
        workspace, "Vlastní", [_person(mutations.get_state(workspace), n) for n in ("Anna N.", "Petr Svoboda")], ["role"]
    )

    mutations.import_from_season(workspace, _source_id(workspace))

    ids = [g["id"] for g in mutations.get_state(workspace)["forced_groups"]]
    assert len(ids) == len(set(ids)) == 3


def test_a_repeat_import_skips_a_group_already_present_with_identical_members_and_axes(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    assert sorted(g["name"] for g in mutations.get_state(workspace)["forced_groups"]) == ["Dvojice", "Rodina"]
    section = _groups_section(summary)
    assert section["groups_imported"] == []
    assert section["groups_skipped"] == ["Rodina", "Dvojice"]


def test_a_renamed_copy_still_counts_as_the_same_group_but_other_rules_do_not(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))
    state = mutations.get_state(workspace)
    forced_groups.update_group(workspace, _group(state, "Rodina")["id"], name="Familie")  # same members and rules
    forced_groups.update_group(workspace, _group(state, "Dvojice")["id"], rules=["role"])  # other rules

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    section = _groups_section(summary)
    assert section["groups_skipped"] == ["Rodina"]
    assert section["groups_imported"] == ["Dvojice"]
    assert sorted(g["name"] for g in mutations.get_state(workspace)["forced_groups"]) == [
        "Dvojice",
        "Dvojice",
        "Familie",
    ]


def test_a_group_the_user_dissolved_comes_back_on_an_explicit_reimport(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))
    forced_groups.dissolve_group(workspace, _group(mutations.get_state(workspace), "Rodina")["id"])

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    assert _groups_section(summary)["groups_imported"] == ["Rodina"]


# -- the summary and the roster --------------------------------------------------


def test_the_summary_reports_groups_alongside_tags(workspace):
    _standard(workspace)

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    assert [s["key"] for s in summary["sections"]] == ["tags", "forced_groups"]
    section = _groups_section(summary)
    assert section["title"] == "Vynucené skupinky kamarádů"
    assert section["lines"][0] == "Importované skupinky: 2 (Rodina, Dvojice)"
    assert "Skupinky bez vracející se osoby, neimportovány: 1 (Cizinci)" in section["lines"]
    assert any(line.startswith("Skupinky už v tomto ročníku, přeskočeno: 0") for line in section["lines"])
    assert "Zatím neaktivní (žádné pravidlo se zatím neuplatní): 1 (Dvojice)" in section["lines"]


def test_an_import_raises_the_stale_flag_only_when_a_roster_exists_and_a_group_arrived(workspace):
    _standard(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))
    assert mutations.stale_reasons(mutations.get_state(workspace)) == []  # no roster yet: nothing to be stale

    forced_groups.dissolve_group(workspace, _group(mutations.get_state(workspace), "Dvojice")["id"])
    mutations.solve(workspace)
    assert mutations.stale_reasons(mutations.get_state(workspace)) == []
    mutations.import_from_season(workspace, _source_id(workspace))  # Dvojice returns: nobody moves, roster stale
    assert mutations.stale_reasons(mutations.get_state(workspace))
    assert mutations.get_state(workspace)["assignments"]

    mutations.solve(workspace)
    mutations.import_from_season(workspace, _source_id(workspace))  # nothing new
    assert mutations.stale_reasons(mutations.get_state(workspace)) == []


def test_imported_groups_are_part_of_versions(workspace):
    _standard(workspace)
    mutations.save_version(workspace, "before import")
    mutations.import_from_season(workspace, _source_id(workspace))
    assert mutations.get_state(workspace)["forced_groups"]

    restored = mutations.restore_version(workspace, mutations.list_versions(workspace)[0]["slug"])

    assert restored["forced_groups"] == []


def test_a_selection_naming_no_group_of_the_source_is_ignored(workspace):
    _standard(workspace)

    summary = mutations.import_from_season(workspace, _source_id(workspace), {"forced_groups": [9999]})

    assert mutations.get_state(workspace)["forced_groups"] == []
    assert _groups_section(summary)["groups_imported"] == []


def test_a_group_whose_members_tags_already_clash_here_is_still_imported_and_the_summary_says_so(workspace):
    _standard(workspace)
    state = mutations.get_state(workspace)
    anna = next(h["id"] for h in state["helpers"] if h["name"] == "Anna N.")
    petr = next(h["id"] for h in state["helpers"] if h["name"] == "Petr Svoboda")
    state = tag_rules.add_tag(workspace, "Jen A", building_allow=["A"])
    only_a = next(t["id"] for t in state["tags"] if t["name"] == "Jen A")
    state = tag_rules.add_tag(workspace, "Jen B", building_allow=["B"])
    only_b = next(t["id"] for t in state["tags"] if t["name"] == "Jen B")
    mutations.add_tag_to_helpers(workspace, only_a, [anna])
    mutations.add_tag_to_helpers(workspace, only_b, [petr])

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    section = _groups_section(summary)
    assert "Rodina" in section["groups_imported"]  # never blocked: it shows as a Broken rule once solved
    assert section["tag_clashes"] and "Skupinka Rodina nemůže sdílet budovu" in section["tag_clashes"][0]
    assert any(line.startswith("Importováno, ale štítky jejich členů nemají nic společného") for line in section["lines"])
