from pathlib import Path

import pandas as pd
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


# ---- T-shirt size (synthetic surveys; never the real Season exports) ----

_NAME_HEADER = "Tvoje jméno a příjmení"
_SIZE_HEADER = "Tvoje velikost trička"


def _write_survey(tmp_path, names, sizes=None):
    """A minimal synthetic survey export: a name column and, unless ``sizes``
    is None, a T-shirt size column."""
    data = {_NAME_HEADER: names}
    if sizes is not None:
        data[_SIZE_HEADER] = sizes
    path = tmp_path / "survey.xlsx"
    pd.DataFrame(data).to_excel(path, index=False)
    return path


def test_tshirt_size_recognized_sizes_are_stored_ignoring_case_and_whitespace(tmp_path):
    path = _write_survey(
        tmp_path,
        ["A", "B", "C", "D", "E", "F", "G"],
        ["XS", "s", " M", "L ", "xl ", " Xxl ", "XL"],
    )
    result = parse_raw_survey(path)
    assert [h.tshirt_size for h in result.helpers] == ["XS", "S", "M", "L", "XL", "XXL", "XL"]
    assert not any("T-shirt" in w for w in result.warnings)


def test_tshirt_size_unrecognized_value_is_unknown_with_warning_naming_helper_and_raw_text(tmp_path):
    path = _write_survey(tmp_path, ["Anna Nováková", "Petr"], ["?", "M"])
    result = parse_raw_survey(path)
    by_name = {h.name: h for h in result.helpers}
    assert by_name["Anna Nováková"].tshirt_size == "Unknown"
    assert by_name["Petr"].tshirt_size == "M"
    size_warnings = [w for w in result.warnings if "T-shirt" in w]
    assert len(size_warnings) == 1
    assert "Anna Nováková" in size_warnings[0]
    assert "'?'" in size_warnings[0]


def test_tshirt_size_free_text_and_blank_are_unknown_with_warning(tmp_path):
    path = _write_survey(tmp_path, ["Anna", "Petr", "Klara"], ["dámské M", None, "XXXL"])
    result = parse_raw_survey(path)
    assert [h.tshirt_size for h in result.helpers] == ["Unknown", "Unknown", "Unknown"]
    size_warnings = [w for w in result.warnings if "T-shirt" in w]
    assert len(size_warnings) == 3
    assert "Anna" in size_warnings[0] and "dámské M" in size_warnings[0]
    assert "Petr" in size_warnings[1]
    assert "Klara" in size_warnings[2] and "XXXL" in size_warnings[2]


def test_tshirt_size_missing_column_warns_once_and_leaves_every_helper_unknown(tmp_path):
    path = _write_survey(tmp_path, ["Anna", "Petr"], sizes=None)
    result = parse_raw_survey(path)
    assert [h.tshirt_size for h in result.helpers] == ["Unknown", "Unknown"]
    size_warnings = [w for w in result.warnings if "'tshirt_size'" in w]
    assert len(size_warnings) == 1
    # No per-helper spam when the whole column is absent.
    assert not any("unrecognized T-shirt size" in w for w in result.warnings)


def test_tshirt_size_header_wording_is_matched_loosely(tmp_path):
    path = tmp_path / "survey.xlsx"
    pd.DataFrame({_NAME_HEADER: ["Anna"], "tvoje  VELIKOST tricka": ["L"]}).to_excel(path, index=False)
    assert parse_raw_survey(path).helpers[0].tshirt_size == "L"


def test_legacy_csv_round_trips_tshirt_size_and_defaults_unknown_when_column_absent(tmp_path):
    helpers = [Helper(id=1, name="Anna", tshirt_size="XL"), Helper(id=2, name="Petr")]
    csv_path = tmp_path / "helpers.csv"
    write_helpers_csv(helpers, csv_path)
    loaded = {h.id: h for h in load_helpers_csv(csv_path).helpers}
    assert loaded[1].tshirt_size == "XL"
    assert loaded[2].tshirt_size == "Unknown"

    old = tmp_path / "old.csv"
    old.write_text(
        "id,name,role_preferences,building_preferences,friends,can_bring_notebook,can_bring_camera\n"
        "1,Anna,,,,false,false\n",
        encoding="utf-8",
    )
    assert load_helpers_csv(old).helpers[0].tshirt_size == "Unknown"


# -- submission timestamps (Season label prefill) -----------------------------


def _write_timestamped_survey(tmp_path, stamps, names=None, header="Časová značka"):
    names = names or [f"Helper {i}" for i in range(len(stamps))]
    path = tmp_path / "survey.xlsx"
    pd.DataFrame({header: stamps, _NAME_HEADER: names}).to_excel(path, index=False)
    return path


def test_submission_timestamps_are_read_from_a_datetime_column(tmp_path):
    from datetime import datetime

    stamps = [datetime(2026, 1, 12, 15, 45), datetime(2026, 2, 3, 9, 0)]
    result = parse_raw_survey(_write_timestamped_survey(tmp_path, stamps))
    assert result.submission_timestamps == stamps


@pytest.mark.parametrize("header", ["Časová značka", "Časové razítko", "Timestamp", "časova  ZNAČKA "])
def test_submission_timestamp_header_wording_is_matched_loosely(tmp_path, header):
    from datetime import datetime

    path = _write_timestamped_survey(tmp_path, [datetime(2025, 9, 20, 8, 0)], header=header)
    assert parse_raw_survey(path).submission_timestamps == [datetime(2025, 9, 20, 8, 0)]


def test_submission_timestamps_in_text_form_are_parsed(tmp_path):
    from datetime import date

    stamps = ["2026/01/12 3:45:12 PM EET", "2026-02-03 09:00:00", "3. 2. 2026 10:15:00"]
    result = parse_raw_survey(_write_timestamped_survey(tmp_path, stamps))
    assert [t.date() for t in result.submission_timestamps] == [date(2026, 1, 12), date(2026, 2, 3), date(2026, 2, 3)]


def test_submission_timestamps_skip_unreadable_cells_and_nameless_rows(tmp_path):
    from datetime import datetime

    stamps = [datetime(2026, 1, 12), "not a date", None, datetime(2026, 1, 20)]
    names = ["Anna", "Petr", "Klara", None]
    result = parse_raw_survey(_write_timestamped_survey(tmp_path, stamps, names=names))
    # Only Anna's row has both a name and a readable timestamp.
    assert result.submission_timestamps == [datetime(2026, 1, 12)]


def test_submission_timestamps_are_empty_without_a_timestamp_column(tmp_path):
    result = parse_raw_survey(_write_survey(tmp_path, ["Anna", "Petr"]))
    assert result.submission_timestamps == []
    # Not a mapped-feature warning: the timestamp only feeds a label prefill.
    assert not any("'timestamp'" in w for w in result.warnings)


def test_read_submission_timestamps_matches_the_full_parse(tmp_path):
    from datetime import datetime

    from rostering.ingest.raw_survey import read_submission_timestamps

    stamps = [datetime(2026, 1, 12), datetime(2026, 2, 3)]
    path = _write_timestamped_survey(tmp_path, stamps)
    assert read_submission_timestamps(path) == stamps


# -- e-mail capture and duplicate submissions (synthetic surveys) ---------------

_EMAIL_HEADER = "E-mailová adresa"


def _write_email_survey(tmp_path, rows, email_header=_EMAIL_HEADER, stamp_header="Časová značka"):
    """A synthetic export from ``rows`` of ``(name, email, submitted_at)``;
    ``email_header``/``stamp_header`` of None leave that column out."""
    data = {}
    if stamp_header is not None:
        data[stamp_header] = [r[2] for r in rows]
    data[_NAME_HEADER] = [r[0] for r in rows]
    if email_header is not None:
        data[email_header] = [r[1] for r in rows]
    path = tmp_path / "survey.xlsx"
    pd.DataFrame(data).to_excel(path, index=False)
    return path


def test_email_is_read_and_normalized_by_trimming_and_lowercasing(tmp_path):
    from datetime import datetime

    when = datetime(2026, 1, 12)
    path = _write_email_survey(
        tmp_path,
        [("Anna", "  Anna.Novakova@Example.TEST ", when), ("Petr", "petr@example.test", when)],
    )
    result = parse_raw_survey(path)
    assert [h.email for h in result.helpers] == ["anna.novakova@example.test", "petr@example.test"]


@pytest.mark.parametrize(
    "header",
    [
        "E-mailová adresa",  # Google Forms' own collected-address column
        "Email Address",
        "Tvůj e-mail",
        "Tvůj email (pro zaslání informací)",
        "e-mail",
        "  E-MAIL  ",
    ],
)
def test_email_header_wording_is_matched_loosely(tmp_path, header):
    from datetime import datetime

    path = _write_email_survey(tmp_path, [("Anna", "a@example.test", datetime(2026, 1, 12))], email_header=header)
    result = parse_raw_survey(path)
    assert result.helpers[0].email == "a@example.test"
    assert not any("'email'" in w for w in result.warnings)


def test_blank_email_is_none_and_a_missing_column_warns_once(tmp_path):
    from datetime import datetime

    when = datetime(2026, 1, 12)
    blank = parse_raw_survey(_write_email_survey(tmp_path, [("Anna", None, when), ("Petr", "  ", when)]))
    assert [h.email for h in blank.helpers] == [None, None]

    missing = parse_raw_survey(_write_email_survey(tmp_path, [("Anna", None, when)], email_header=None))
    assert [h.email for h in missing.helpers] == [None]
    assert len([w for w in missing.warnings if "'email'" in w]) == 1


def test_duplicate_rows_with_the_same_email_collapse_to_the_latest_submission(tmp_path):
    from datetime import datetime

    path = tmp_path / "survey.xlsx"
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 1, 12), datetime(2026, 1, 13), datetime(2026, 1, 14), datetime(2026, 1, 11)],
            _NAME_HEADER: ["Anna Nováková", "Petr", "Anna Nováková (oprava)", "Klára"],
            _EMAIL_HEADER: ["anna@example.test", "petr@example.test", " ANNA@example.test", "klara@example.test"],
            _SIZE_HEADER: ["S", "M", "L", "XL"],
        }
    ).to_excel(path, index=False)

    result = parse_raw_survey(path)
    assert [h.name for h in result.helpers] == ["Petr", "Anna Nováková (oprava)", "Klára"]
    assert [h.tshirt_size for h in result.helpers] == ["M", "L", "XL"]
    # Ids are sequential over the Helpers that remain.
    assert [h.id for h in result.helpers] == [1, 2, 3]
    assert any("anna@example.test" in w for w in result.warnings)


def test_the_latest_submission_wins_by_timestamp_even_if_it_is_not_the_last_row(tmp_path):
    from datetime import datetime

    path = _write_email_survey(
        tmp_path,
        [
            ("Anna (new)", "anna@example.test", datetime(2026, 2, 1)),
            ("Anna (old)", "anna@example.test", datetime(2026, 1, 1)),
        ],
    )
    assert [h.name for h in parse_raw_survey(path).helpers] == ["Anna (new)"]


def test_duplicate_emails_without_readable_timestamps_keep_the_last_row(tmp_path):
    path = _write_email_survey(
        tmp_path,
        [("Anna (first)", "anna@example.test", None), ("Anna (last)", "anna@example.test", None)],
    )
    assert [h.name for h in parse_raw_survey(path).helpers] == ["Anna (last)"]


def test_same_name_with_different_emails_and_blank_emails_are_never_collapsed(tmp_path):
    from datetime import datetime

    when = datetime(2026, 1, 12)
    path = _write_email_survey(
        tmp_path,
        [
            ("Anna Nováková", "anna1@example.test", when),
            ("Anna Nováková", "anna2@example.test", when),
            ("Petr", None, when),
            ("Petr", None, when),
        ],
    )
    assert [h.name for h in parse_raw_survey(path).helpers] == ["Anna Nováková", "Anna Nováková", "Petr", "Petr"]


def test_friend_names_resolve_against_the_collapsed_helpers(tmp_path):
    from datetime import datetime

    friends_header = "Chtěl/a bys být v místnosti s někým konkrétním?"
    path = tmp_path / "survey.xlsx"
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3)],
            _NAME_HEADER: ["Anna Nováková", "Petr Svoboda", "Anna Nováková"],
            _EMAIL_HEADER: ["anna@example.test", "petr@example.test", "anna@example.test"],
            friends_header: [None, "Anna Nováková", None],
        }
    ).to_excel(path, index=False)

    result = parse_raw_survey(path)
    assert [h.name for h in result.helpers] == ["Petr Svoboda", "Anna Nováková"]
    assert result.helpers[0].friends == [2]  # Anna's surviving id, not her dropped first row's
