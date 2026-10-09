"""Class promotion: renaming school-class Tags one school year up per school year
crossed since the imported Season. Mutation-layer tests against a temp-dir
workspace holding several synthetic stored Seasons (never anything from data/)."""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations
from tests import tag_rules

_NAME_HEADER = "Tvoje jméno a příjmení"
_EMAIL_HEADER = "E-mailová adresa"

ANNA = "anna@example.test"
ANNA_NEW = "anna.new@example.test"
PETR = "petr@example.test"


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


def _season(workspace, label, rows=(("Anna Nováková", ANNA),), buildings=("A", "B")):
    """Store a new Season (which stays open) with these ``(name, email)`` Helpers."""
    mutations.new_season(workspace)
    mutations.upload_responses(workspace, _survey(list(rows)), "s.xlsx", label=label)
    return mutations.put_config(workspace, _config(*buildings))


def _ids(workspace) -> dict[str, str]:
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def _helper(state, name):
    return next(h for h in state["helpers"] if h["name"] == name)


def _tag(state, name):
    return next(t for t in state["tags"] if t["name"] == name)


def _names(workspace) -> list[str]:
    return sorted(t["name"] for t in mutations.get_state(workspace)["tags"])


def _add_tag(workspace, name, **kwargs) -> int:
    return _tag(tag_rules.add_tag(workspace, name, **kwargs), name)["id"]


def _give(workspace, helper_name, *tag_ids):
    state = mutations.get_state(workspace)
    for tag_id in tag_ids:
        mutations.add_tag_to_helpers(workspace, tag_id, [_helper(state, helper_name)["id"]])


def _imported(workspace, source_label, current_label, tag_names=("8.M",), rows=(("Anna Nováková", ANNA),)):
    """A source Season carrying these Tags (Anna holds each directly), then the
    current Season (left open) with them imported. Returns the import summary."""
    _season(workspace, source_label, rows)
    for name in tag_names:
        _give(workspace, "Anna Nováková", _add_tag(workspace, name))
    source_id = _ids(workspace)[source_label]
    _season(workspace, current_label, rows)
    return mutations.import_from_season(workspace, source_id)


def _suggested(workspace) -> dict[str, str]:
    """The suggested renames: current name -> target name."""
    return {s["name"]: s["target"] for s in mutations.class_promotion_offer(workspace)["suggestions"]}


def _promote(workspace, *names, extra=None):
    """Tick these suggested Tags (by current name), plus ``extra`` (current name
    -> typed target), and apply."""
    state = mutations.get_state(workspace)
    suggested = _suggested(workspace)
    renames = {_tag(state, name)["id"]: suggested[name] for name in names}
    for name, target in (extra or {}).items():
        renames[_tag(state, name)["id"]] = target
    return mutations.apply_class_promotion(workspace, renames)


# -- recognizing class Tags --------------------------------------------------------


def test_only_tags_named_number_dot_optional_space_letters_are_suggested(workspace):
    _imported(
        workspace,
        "2025-podzim",
        "2026-podzim",
        tag_names=["8.M", "8. M", "10.M", "7.Ž", "GCHD", "8M", "8.M2", "8 .M", "8.  M", "Vedoucí", "8."],
    )

    assert _suggested(workspace) == {"8.M": "9.M", "8. M": "9. M", "10.M": "11.M", "7.Ž": "8.Ž"}
    other = {t["name"] for t in mutations.class_promotion_offer(workspace)["other_tags"]}
    assert other == {"GCHD", "8M", "8.M2", "8 .M", "8.  M", "Vedoucí", "8."}


def test_a_class_tag_without_an_origin_is_not_suggested_but_can_be_added_by_hand(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M"])
    _add_tag(workspace, "6.A")  # made by hand in this Season: no source to count the years from

    offer = mutations.class_promotion_offer(workspace)

    assert [s["name"] for s in offer["suggestions"]] == ["8.M"]
    assert "6.A" in [t["name"] for t in offer["other_tags"]]


def test_a_season_with_no_import_has_nothing_to_promote(workspace):
    _season(workspace, "2026-podzim")
    _add_tag(workspace, "8.M")

    offer = mutations.class_promotion_offer(workspace)

    assert offer["suggestions"] == [] and offer["nothing_to_promote"] is True
    assert [t["name"] for t in offer["other_tags"]] == ["8.M"]


# -- how far a class moves ---------------------------------------------------------


@pytest.mark.parametrize(
    "source, current, years",
    [
        ("2025-podzim", "2026-podzim", 1),  # one autumn
        ("2026-jaro", "2026-podzim", 1),  # the school year turns at the jaro -> podzim boundary
        ("2026-jaro", "2027-jaro", 1),
        ("2025-jaro", "2027-jaro", 2),
        ("2024-podzim", "2026-podzim", 2),
        ("2025-jaro", "2026-podzim", 2),
        ("2025-podzim", "2026-jaro", 0),  # the same school year
        ("2025-jaro", "2025-podzim", 1),
        ("2025-podzim", "2027-jaro", 1),
    ],
)
def test_the_number_goes_up_by_the_school_years_crossed(workspace, source, current, years):
    _imported(workspace, source, current)

    assert _suggested(workspace) == ({"8.M": f"{8 + years}.M"} if years else {})


def test_there_is_no_top_year(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["12.M", "15.B"])

    assert _suggested(workspace) == {"12.M": "13.M", "15.B": "16.B"}


def test_zero_years_crossed_says_there_is_nothing_to_promote_but_hand_adding_still_works(workspace):
    _imported(workspace, "2025-podzim", "2026-jaro", tag_names=["8.M", "GCHD"])

    offer = mutations.class_promotion_offer(workspace)

    assert offer["suggestions"] == []
    assert offer["nothing_to_promote"] is True
    assert {t["name"] for t in offer["other_tags"]} == {"8.M", "GCHD"}
    state = mutations.get_state(workspace)
    mutations.apply_class_promotion(workspace, {_tag(state, "8.M")["id"]: "9.M"})
    assert _names(workspace) == ["9.M", "GCHD"]


def test_the_number_of_years_crossed_is_not_part_of_the_offer(workspace):
    _imported(workspace, "2024-podzim", "2026-podzim")

    offer = mutations.class_promotion_offer(workspace)

    assert set(offer) == {"suggestions", "other_tags", "nothing_to_promote"}
    assert set(offer["suggestions"][0]) == {"tag_id", "name", "target"}


def test_the_years_follow_the_source_seasons_current_label(workspace):
    _imported(workspace, "2025-jaro", "2026-podzim")
    assert _suggested(workspace) == {"8.M": "10.M"}

    mutations.rename_season(workspace, _ids(workspace)["2025-jaro"], "2025-podzim")  # the source was mislabelled

    assert _suggested(workspace) == {"8.M": "9.M"}


# -- when the dialog opens by itself -----------------------------------------------


@pytest.mark.parametrize(
    "source, current, prompt",
    [
        ("2025-podzim", "2026-podzim", True),
        ("2026-jaro", "2026-podzim", True),
        ("2024-jaro", "2026-podzim", True),
        ("2025-podzim", "2026-jaro", False),  # nothing crossed
        ("2024-podzim", "2026-jaro", False),  # crossed, but the current Season is jaro
        ("2025-jaro", "2026-jaro", False),
    ],
)
def test_the_dialog_opens_after_an_import_only_for_podzim_with_a_school_year_crossed(
    workspace, source, current, prompt
):
    summary = _imported(workspace, source, current)

    assert summary["promotion_prompt"] is prompt


# -- applying ----------------------------------------------------------------------


def test_nothing_is_written_until_apply_and_the_offer_can_come_back(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "10.M"])
    before = mutations.get_state(workspace)

    first = mutations.class_promotion_offer(workspace)  # opened, then skipped
    second = mutations.class_promotion_offer(workspace)

    assert mutations.get_state(workspace) == before
    assert first == second
    assert [s["name"] for s in second["suggestions"]] == ["8.M", "10.M"]


def test_apply_renames_in_place_and_keeps_everything_else(workspace):
    _season(workspace, "2025-podzim")
    gchd = _add_tag(workspace, "GCHD")
    eight = _add_tag(
        workspace, "8. M", colour="#445566", note="class", parent_id=gchd, building_allow=["A"], role_deny=["Fotograf"]
    )
    _add_tag(workspace, "Kapitán", parent_id=eight)
    _give(workspace, "Anna Nováková", eight)
    source = _ids(workspace)["2025-podzim"]
    _season(workspace, "2026-podzim")
    mutations.import_from_season(workspace, source)
    old = _tag(mutations.get_state(workspace), "8. M")

    state = _promote(workspace, "8. M")

    new = _tag(state, "9. M")  # the original spacing is kept
    assert new["id"] == old["id"]
    assert {k: v for k, v in new.items() if k != "name"} == {k: v for k, v in old.items() if k != "name"}
    assert new["parent_id"] == _tag(state, "GCHD")["id"]
    assert _tag(state, "Kapitán")["parent_id"] == new["id"]
    assert _helper(state, "Anna Nováková")["tags"] == [new["id"]]
    assert sorted(t["name"] for t in state["tags"]) == ["9. M", "GCHD", "Kapitán"]


def test_ticked_tags_are_renamed_together_so_a_chain_shifts_without_trampling(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "9.M", "10.M"])
    ids = {name: _tag(mutations.get_state(workspace), name)["id"] for name in ("8.M", "9.M", "10.M")}

    state = _promote(workspace, "8.M", "9.M", "10.M")

    assert {t["id"]: t["name"] for t in state["tags"]} == {ids["8.M"]: "9.M", ids["9.M"]: "10.M", ids["10.M"]: "11.M"}


def test_a_ticked_tag_colliding_with_an_unticked_one_blocks_apply_and_nothing_is_merged(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "9.M"])
    before = mutations.get_state(workspace)
    ticked = {_tag(before, "8.M")["id"]: "9.M"}

    problems = mutations.class_promotion_conflicts(workspace, ticked)
    with pytest.raises(mutations.RosteringError) as raised:
        mutations.apply_class_promotion(workspace, ticked)

    assert len(problems) == 1 and "9.M" in problems[0]
    assert "9.M" in str(raised.value)
    assert mutations.get_state(workspace) == before


def test_a_chain_with_a_gap_still_blocks_on_the_tag_that_is_not_ticked(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "9.M", "10.M"])
    state = mutations.get_state(workspace)
    ticked = {_tag(state, "8.M")["id"]: "9.M", _tag(state, "10.M")["id"]: "11.M"}  # 9.M is left where it is

    assert mutations.class_promotion_conflicts(workspace, ticked)
    assert mutations.class_promotion_conflicts(workspace, {_tag(state, "10.M")["id"]: "11.M"}) == []


def test_the_collision_check_ignores_case_and_two_tags_cannot_share_a_target(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "7.M", "9.m"])
    state = mutations.get_state(workspace)

    assert mutations.class_promotion_conflicts(workspace, {_tag(state, "8.M")["id"]: "9.M"})  # 9.m is there, unticked
    assert mutations.class_promotion_conflicts(
        workspace, {_tag(state, "8.M")["id"]: "20.M", _tag(state, "7.M")["id"]: "20.m"}
    )


def test_a_blank_target_name_blocks_apply(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim")
    state = mutations.get_state(workspace)
    blank = {_tag(state, "8.M")["id"]: "  "}

    assert mutations.class_promotion_conflicts(workspace, blank)
    with pytest.raises(mutations.RosteringError):
        mutations.apply_class_promotion(workspace, blank)
    assert _names(workspace) == ["8.M"]


def test_unticked_class_tags_are_left_alone(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "6.A"])

    _promote(workspace, "8.M")

    assert _names(workspace) == ["6.A", "9.M"]


def test_a_tag_added_by_hand_gets_an_editable_target_prefilled_with_its_exact_name(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "GCHD"])
    _add_tag(workspace, "Šesťáci 6.A")

    other = {t["name"]: t["target"] for t in mutations.class_promotion_offer(workspace)["other_tags"]}

    assert other == {"GCHD": "GCHD", "Šesťáci 6.A": "Šesťáci 6.A"}  # exact current names, nothing guessed
    state = mutations.get_state(workspace)
    mutations.apply_class_promotion(
        workspace,
        {
            _tag(state, "8.M")["id"]: "9.M",
            _tag(state, "Šesťáci 6.A")["id"]: "Šesťáci 7.A",
            _tag(state, "GCHD")["id"]: "GCHD",  # typed but unchanged: no rename
        },
    )
    assert _names(workspace) == ["9.M", "GCHD", "Šesťáci 7.A"]


def test_only_the_open_season_is_edited(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim")
    source_id = _ids(workspace)["2025-podzim"]
    source_before = workspace.stored_state(source_id)

    _promote(workspace, "8.M")

    assert workspace.stored_state(source_id) == source_before
    assert [t["name"] for t in source_before["tags"]] == ["8.M"]


def test_apply_refuses_an_unknown_tag(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim")

    with pytest.raises(mutations.RosteringError):
        mutations.apply_class_promotion(workspace, {9999: "9.M"})


# -- what the Season remembers -----------------------------------------------------


def test_a_promoted_tag_is_not_suggested_again_but_a_left_alone_one_still_is(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "10.M"])

    _promote(workspace, "8.M")  # 10.M was suggested but left unticked

    assert _suggested(workspace) == {"10.M": "11.M"}


def test_the_season_records_the_steps_applied_per_source_and_the_tags_left_unpromoted(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "10.M"])
    source = _ids(workspace)["2025-podzim"]
    state = mutations.get_state(workspace)
    ten_origin = _tag(state, "10.M")["origins"][0]["tag_id"]

    _promote(workspace, "8.M")

    record = mutations.get_state(workspace)["tag_imports"][source]
    assert record["promoted_years"] == 1
    assert record["unpromoted_tag_ids"] == [ten_origin]

    _promote(workspace, "10.M")  # ticked later: no longer left unpromoted

    record = mutations.get_state(workspace)["tag_imports"][source]
    assert record["unpromoted_tag_ids"] == []
    assert _suggested(workspace) == {}


def test_the_records_are_part_of_versions(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim")
    mutations.save_version(workspace, "before promotion")
    _promote(workspace, "8.M")
    assert _names(workspace) == ["9.M"]

    restored = mutations.restore_version(workspace, mutations.list_versions(workspace)[0]["slug"])

    assert [t["name"] for t in restored["tags"]] == ["8.M"]
    assert _suggested(workspace) == {"8.M": "9.M"}


# -- imports after a promotion -----------------------------------------------------


def test_a_reimport_after_promotion_finds_the_renamed_tag_by_origin(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim")
    _promote(workspace, "8.M")

    summary = mutations.import_from_season(workspace, _ids(workspace)["2025-podzim"])

    assert _names(workspace) == ["9.M"]  # no stray 8.M
    tags_section = next(s for s in summary["sections"] if s["key"] == "tags")
    assert tags_section["tags_created"] == []


def test_a_promoted_tag_that_was_deleted_comes_back_on_reimport_under_the_promoted_name(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim")
    _promote(workspace, "8.M")
    state = mutations.get_state(workspace)
    mutations.delete_tag(workspace, _tag(state, "9.M")["id"], confirmed=True)

    summary = mutations.import_from_season(workspace, _ids(workspace)["2025-podzim"])

    assert _names(workspace) == ["9.M"]
    tags_section = next(s for s in summary["sections"] if s["key"] == "tags")
    assert tags_section["tags_restored"] == ["9.M"]
    assert [t["name"] for t in mutations.get_state(workspace)["tags"]] == ["9.M"]
    assert _helper(mutations.get_state(workspace), "Anna Nováková")["tags"]  # Anna got it again


def test_a_tag_left_unpromoted_comes_back_under_its_old_name(workspace):
    _imported(workspace, "2025-podzim", "2026-podzim", tag_names=["8.M", "10.M"])
    _promote(workspace, "8.M")  # 10.M deliberately left
    state = mutations.get_state(workspace)
    mutations.delete_tag(workspace, _tag(state, "10.M")["id"], confirmed=True)

    mutations.import_from_season(workspace, _ids(workspace)["2025-podzim"])

    assert _names(workspace) == ["10.M", "9.M"]


def _late_setup(workspace, tag_names=("8.M",)):
    """Anna is an unreviewed uncertain match at import time (new e-mail, same
    name); returns her Helper id and her earlier Person's id."""
    _season(workspace, "2025-podzim")
    for name in tag_names:
        _give(workspace, "Anna Nováková", _add_tag(workspace, name))
    source = _ids(workspace)["2025-podzim"]
    _season(workspace, "2026-podzim", [("Anna Nováková", ANNA_NEW)])
    mutations.import_from_season(workspace, source)
    (entry,) = mutations.get_uncertain_matches(workspace)
    return entry["helper_id"], entry["candidates"][0]["person_id"]


def test_a_late_confirmed_link_receives_the_promoted_name(workspace):
    helper_id, person_id = _late_setup(workspace)
    _promote(workspace, "8.M")

    mutations.link_helper(workspace, helper_id, person_id)
    offer = mutations.late_link_tag_offer(workspace, helper_id)
    mutations.apply_late_link_tags(workspace, helper_id)

    assert [t["name"] for t in offer["tags"]] == ["9.M"]
    state = mutations.get_state(workspace)
    assert _names(workspace) == ["9.M"]
    assert _helper(state, "Anna Nováková")["tags"] == [_tag(state, "9.M")["id"]]


def test_a_late_link_finds_an_existing_tag_by_the_promoted_name_when_no_origin_matches(workspace):
    helper_id, person_id = _late_setup(workspace)
    _promote(workspace, "8.M")
    state = mutations.get_state(workspace)
    mutations.delete_tag(workspace, _tag(state, "9.M")["id"], confirmed=True)
    mine = _add_tag(workspace, "9.M")  # a hand-made 9.M: no origin, but the promoted name matches

    mutations.link_helper(workspace, helper_id, person_id)
    offer = mutations.late_link_tag_offer(workspace, helper_id)

    assert [(t["tag_id"], t["name"]) for t in offer["tags"]] == [(mine, "9.M")]


def test_a_late_link_after_a_tag_was_left_unpromoted_gets_the_unpromoted_name(workspace):
    helper_id, person_id = _late_setup(workspace, tag_names=("10.M", "8.M"))
    _promote(workspace, "8.M")  # 10.M left
    state = mutations.get_state(workspace)
    mutations.delete_tag(workspace, _tag(state, "10.M")["id"], confirmed=True)
    mine = _add_tag(workspace, "10.M")  # hand-made, matches the unpromoted name only

    mutations.link_helper(workspace, helper_id, person_id)
    offer = mutations.late_link_tag_offer(workspace, helper_id)

    assert (mine, "10.M") in [(t["tag_id"], t["name"]) for t in offer["tags"]]
