"""No default building layout: a new Season starts with none, and the layout comes
from an earlier Season through the "Rozložení budov" section of the import offer
(its first section: Tag rules are copied only with the Buildings the Season has).

Mutation-layer tests against a temp-dir workspace holding synthetic stored Seasons.
"""
import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

OLD = [
    {
        "name": "Alfa",
        "capacities": {"Opravovatel": {"minimum": 1}},
        "rooms": [
            {"name": "A1", "capacities": {"Opravovatel": {"minimum": 2}}},
            {"name": "A2", "capacities": {"Opravovatel": {"minimum": 3}}},
        ],
    },
    {"name": "Beta", "capacities": {}, "rooms": [{"name": "B1", "capacities": {"Zaloha": {"minimum": 1}}}]},
]
NEW = [{"name": "Gama", "capacities": {}, "rooms": [{"name": "G1", "capacities": {}}]}]


@pytest.fixture
def workspace(tmp_path):
    return Workspace(root=tmp_path / "seasons")


def _season(workspace, label, config):
    mutations.new_season(workspace)  # blank, not a copy of the Season open now
    workspace.create_season(label)
    return mutations.put_config(workspace, config) if config else mutations.get_state(workspace)


def _source_id(workspace, label="2025-podzim"):
    return next(s["id"] for s in mutations.list_seasons(workspace) if s["label"] == label)


def _layout_section(summary):
    return next(s for s in summary["sections"] if s["key"] == "layout")


def _two_seasons(workspace, open_config=None):
    """2025-podzim holds OLD with a sideways merge of A1 and A2 for Opravovatel;
    2026-jaro (left open) holds ``open_config`` (none by default)."""
    _season(workspace, "2025-podzim", OLD)
    mutations.set_cell_merges(workspace, "Opravovatel", "Alfa", [["A1", "A2"]], True)
    _season(workspace, "2026-jaro", open_config)


# -- no default ---------------------------------------------------------------------


def test_a_new_season_has_no_buildings(workspace):
    assert mutations.get_state(workspace)["config"] == []  # blank draft
    workspace.create_season("2026-jaro")
    assert mutations.get_state(workspace)["config"] == []


def test_start_over_wipes_the_layout_with_everything_else(workspace):
    workspace.create_season("2026-jaro")
    mutations.put_config(workspace, OLD)

    assert mutations.reset_workspace(workspace)["config"] == []


def test_saving_a_layout_writes_nothing_outside_the_season(workspace, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace.create_season("2026-jaro")

    mutations.put_config(workspace, OLD)

    assert not (tmp_path / "data").exists()


# -- the offer ---------------------------------------------------------------------


def test_the_layout_is_the_first_section_of_the_offer(workspace):
    _two_seasons(workspace)

    sections = mutations.tag_import_offer(workspace)["sections"]

    assert [s["key"] for s in sections][:1] == ["layout"]
    assert sections[0]["title"] == "Rozložení budov"


def test_the_overview_describes_the_source_layout(workspace):
    _two_seasons(workspace)

    overview = mutations.import_overview(workspace, _source_id(workspace))
    (section,) = [s for s in overview["sections"] if s["key"] == "layout"]

    assert section["buildings"] == [
        {"name": "Alfa", "rooms": ["A1", "A2"]},
        {"name": "Beta", "rooms": ["B1"]},
    ]
    assert section["importable"] is True
    assert section["replaces"] is False  # the open Season has no layout yet


def test_the_overview_says_when_it_would_replace_a_layout(workspace):
    _two_seasons(workspace, NEW)

    (section,) = [
        s for s in mutations.import_overview(workspace, _source_id(workspace))["sections"] if s["key"] == "layout"
    ]

    assert section["replaces"] is True


def test_a_source_without_a_layout_offers_nothing(workspace):
    _season(workspace, "2025-podzim", None)
    _season(workspace, "2026-jaro", None)

    (section,) = [
        s for s in mutations.import_overview(workspace, _source_id(workspace))["sections"] if s["key"] == "layout"
    ]

    assert section["importable"] is False


# -- importing ---------------------------------------------------------------------


def test_an_empty_season_takes_the_layout_with_its_counts_and_merges(workspace):
    _two_seasons(workspace)

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    state = mutations.get_state(workspace)
    assert state["config"] == OLD
    assert state["cell_merges"] == {"Opravovatel": {"Alfa": [["A1", "A2"]]}}
    assert _layout_section(summary)["imported"] is True
    assert _layout_section(summary)["lines"]


def test_tall_cells_come_along(workspace):
    _season(workspace, "2025-podzim", OLD)
    mutations.set_cell_merges(workspace, "PravaRuka", "Alfa", [["A1", "A2"]], True)
    mutations.set_cell_merges(workspace, "VedouciBudovy", "Alfa", [["A1", "A2"]], True)
    mutations.set_row_merge(workspace, "VedouciBudovy", "Alfa", "A1", True)
    _season(workspace, "2026-jaro", None)

    mutations.import_from_season(workspace, _source_id(workspace))

    assert mutations.get_state(workspace)["row_merges"] == [{"building": "Alfa", "room": "A1", "row": "VedouciBudovy"}]


def test_the_leadership_slot_holders_stay_behind(workspace):
    _season(workspace, "2025-podzim", OLD)
    anna = mutations.add_organizer(workspace, "Anna")["organizers"][-1]["id"]
    mutations.assign_organizer(workspace, anna, "VedouciBudovy", "Alfa")
    _season(workspace, "2026-jaro", None)

    mutations.import_from_season(workspace, _source_id(workspace))

    state = mutations.get_state(workspace)
    assert state["manual_roles"]["structural"] == []
    assert state["organizers"] == []


def test_the_source_is_only_read(workspace):
    _two_seasons(workspace)
    before = workspace.stored_state(_source_id(workspace))

    mutations.import_from_season(workspace, _source_id(workspace))

    assert workspace.stored_state(_source_id(workspace)) == before


def test_a_built_layout_is_left_alone_unless_ticked(workspace):
    _two_seasons(workspace, NEW)

    summary = mutations.import_from_season(workspace, _source_id(workspace))

    assert mutations.get_state(workspace)["config"] == NEW
    assert _layout_section(summary)["imported"] is False


def test_ticking_it_replaces_a_built_layout_after_a_confirmation(workspace):
    _two_seasons(workspace, NEW)

    with pytest.raises(mutations.ConfirmationRequired) as asked:
        mutations.import_from_season(workspace, _source_id(workspace), {"layout": True})
    assert mutations.get_state(workspace)["config"] == NEW  # nothing changed
    assert asked.value.lines

    mutations.import_from_season(workspace, _source_id(workspace), {"layout": True}, confirmed=True)

    assert mutations.get_state(workspace)["config"] == OLD


def test_the_same_layout_needs_no_confirmation(workspace):
    _two_seasons(workspace, OLD)

    summary = mutations.import_from_season(workspace, _source_id(workspace), {"layout": True})

    assert _layout_section(summary)["imported"] is False


def test_unticking_it_leaves_an_empty_layout_empty(workspace):
    _two_seasons(workspace)

    mutations.import_from_season(workspace, _source_id(workspace), {"layout": False})

    assert mutations.get_state(workspace)["config"] == []


def test_replacing_a_layout_under_a_roster_makes_it_stale(workspace):
    _two_seasons(workspace, NEW)
    state = workspace.load()
    state["assignments"] = [
        {"helper_id": 1, "helper_name": "Anna", "building": "Gama", "room": "G1", "role": "Opravovatel"}
    ]
    workspace.save(state)

    mutations.import_from_season(workspace, _source_id(workspace), {"layout": True}, confirmed=True)

    assert mutations.stale_reasons(mutations.get_state(workspace))


def test_the_confirmation_names_what_the_replacement_touches(workspace):
    _two_seasons(workspace, NEW)
    state = workspace.load()
    state["assignments"] = [
        {"helper_id": 1, "helper_name": "Anna", "building": "Gama", "room": "G1", "role": "Opravovatel"}
    ]
    workspace.save(state)

    with pytest.raises(mutations.ConfirmationRequired) as asked:
        mutations.import_from_season(workspace, _source_id(workspace), {"layout": True})

    text = " ".join(asked.value.lines)
    assert "Gama" in text and "1" in text
