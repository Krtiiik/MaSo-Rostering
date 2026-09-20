from pathlib import Path

import pytest

from rostering.domain import Helper, Preference, Role
from rostering.ingest.legacy import load_helpers_csv, write_helpers_csv
from rostering.ingest.raw_survey import parse_raw_survey

REPO_ROOT = Path(__file__).resolve().parents[1]
SEASONS_DIR = REPO_ROOT / "data" / "seasons"

# Every season's raw export, and the minimum number of helpers we expect to
# find (a loose floor, not an exact count — real data can gain/lose rows).
REAL_SEASONS = [
    ("2023-podzim", 100),
    ("2024-jaro", 90),
    ("2024-podzim", 100),
    ("2025-jaro", 90),
    ("2025-podzim", 100),
    ("2026-jaro", 110),
]


@pytest.mark.parametrize("season,min_helpers", REAL_SEASONS)
def test_parses_every_real_season_without_crashing(season, min_helpers):
    raw_path = SEASONS_DIR / season / "raw-response.xlsx"
    result = parse_raw_survey(raw_path)
    assert len(result.helpers) >= min_helpers
    # ids must be unique and sequential starting at 1
    ids = [h.id for h in result.helpers]
    assert ids == list(range(1, len(ids) + 1))


def test_2026_jaro_extracts_equipment_and_multi_building_preference():
    result = parse_raw_survey(SEASONS_DIR / "2026-jaro" / "raw-response.xlsx")
    by_name = {h.name: h for h in result.helpers}

    someone_with_both = next(h for h in result.helpers if h.can_bring_notebook and h.can_bring_camera)
    assert someone_with_both.can_bring_notebook and someone_with_both.can_bring_camera

    multi_building = [h for h in result.helpers if len(h.building_preferences) > 1]
    assert multi_building, "expected at least one helper to accept multiple buildings"


def test_unresolved_friend_names_are_surfaced_not_dropped():
    result = parse_raw_survey(SEASONS_DIR / "2026-jaro" / "raw-response.xlsx")
    someone_unresolved = next(h for h in result.helpers if h.unresolved_friend_names)
    assert someone_unresolved.unresolved_friend_names
    # Unresolved friend names are surfaced via `unresolved_friend_names` (and
    # resolved interactively in the UI), not duplicated into `warnings`.
    assert not any("could not resolve friend name" in w for w in result.warnings)


def test_legacy_csv_round_trip(tmp_path):
    helpers = [
        Helper(
            id=1,
            name="Anna",
            role_preferences={Role.Opravovatel: Preference.Ano},
            building_preferences=frozenset({"Karlov", "Malá Strana"}),
            friends=[2],
            can_bring_notebook=True,
            can_bring_camera=False,
            unresolved_friend_names=["Some Unresolved Name"],
        ),
        Helper(id=2, name="Petr"),
    ]
    csv_path = tmp_path / "helpers.csv"
    write_helpers_csv(helpers, csv_path)

    result = load_helpers_csv(csv_path)
    assert result.warnings == []
    loaded = {h.id: h for h in result.helpers}
    assert loaded[1].name == "Anna"
    assert loaded[1].role_preferences == {Role.Opravovatel: Preference.Ano}
    assert loaded[1].building_preferences == frozenset({"Karlov", "Malá Strana"})
    assert loaded[1].friends == [2]
    assert loaded[1].can_bring_notebook is True
    assert loaded[1].can_bring_camera is False


def test_legacy_single_building_csv_warns_and_defaults_ineligible(tmp_path):
    csv_path = tmp_path / "old.csv"
    csv_path.write_text(
        "id,name,role_preferences,building_preference,friends\n"
        "1,Anna,Opravovatel=Ano,Karlov,\n",
        encoding="utf-8",
    )
    result = load_helpers_csv(csv_path)
    assert len(result.warnings) == 1
    helper = result.helpers[0]
    assert helper.building_preferences == frozenset({"Karlov"})
    assert helper.can_bring_notebook is False
    assert helper.can_bring_camera is False
