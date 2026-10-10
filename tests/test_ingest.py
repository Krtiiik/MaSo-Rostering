import pandas as pd
import pytest

from rostering.domain import Helper, Preference, Role, parse_tshirt_size
from rostering.ingest.raw_survey import parse_raw_survey
from tests.survey_factory import UNRESOLVABLE_FRIEND, generate_survey, write_survey

# ---- generated surveys (never the real Season exports) ----

# The two form layouts the parser has to read (see tests/survey_factory.py).
FORM_STYLES = ["likert", "freetext"]


@pytest.mark.parametrize("style", FORM_STYLES)
@pytest.mark.parametrize("count", [1, 15, 120])
def test_parses_a_generated_survey_of_any_size(tmp_path, style, count):
    result = parse_raw_survey(write_survey(tmp_path / "survey.xlsx", count=count, style=style))
    assert len(result.helpers) == count
    # ids must be unique and sequential starting at 1
    ids = [h.id for h in result.helpers]
    assert ids == list(range(1, len(ids) + 1))


def test_a_generated_survey_is_reproducible_from_its_seed():
    assert generate_survey(30, seed=4).equals(generate_survey(30, seed=4))
    assert not generate_survey(30, seed=4).equals(generate_survey(30, seed=5))


def test_likert_form_reads_one_preference_per_role(tmp_path):
    result = parse_raw_survey(write_survey(tmp_path / "survey.xlsx", count=40, style="likert"))
    assert all(set(h.role_preferences) == {r for r in Role if r is not Role.Zaloha} for h in result.helpers)
    assert {p for h in result.helpers for p in h.role_preferences.values()} == set(Preference)


def test_freetext_form_reads_one_wanted_and_one_unwanted_role(tmp_path):
    result = parse_raw_survey(write_survey(tmp_path / "survey.xlsx", count=40, style="freetext"))
    for helper in result.helpers:
        prefs = list(helper.role_preferences.values())
        assert sorted(prefs) == [Preference.Ne, Preference.Ano]


@pytest.mark.parametrize("style", FORM_STYLES)
def test_extracts_equipment_and_multi_building_preference(tmp_path, style):
    result = parse_raw_survey(write_survey(tmp_path / "survey.xlsx", style=style))

    someone_with_both = next(h for h in result.helpers if h.can_bring_notebook and h.can_bring_camera)
    assert someone_with_both.can_bring_notebook and someone_with_both.can_bring_camera

    multi_building = [h for h in result.helpers if len(h.building_preferences) > 1]
    assert multi_building, "expected at least one helper to accept multiple buildings"
    assert {"Malá Strana", "Karlov"} <= set(result.helpers[0].building_preferences)
    assert not any("budovy" in w for w in result.warnings)


@pytest.mark.parametrize("style", FORM_STYLES)
def test_unresolved_friend_names_are_surfaced_not_dropped(tmp_path, style):
    result = parse_raw_survey(write_survey(tmp_path / "survey.xlsx", style=style))
    someone_unresolved = next(h for h in result.helpers if h.unresolved_friend_names)
    assert someone_unresolved.unresolved_friend_names == [UNRESOLVABLE_FRIEND]
    # The other name in the same answer is still resolved.
    assert someone_unresolved.friends == [3]
    # Unresolved friend names are surfaced via `unresolved_friend_names` (and
    # resolved interactively in the UI), not duplicated into `warnings`.
    assert not any("could not resolve friend name" in w for w in result.warnings)


def test_friend_names_resolve_to_the_named_registrant(tmp_path):
    result = parse_raw_survey(write_survey(tmp_path / "survey.xlsx"))
    assert result.helpers[3].friends == [5]
    assert not result.helpers[3].unresolved_friend_names


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
    size_warnings = [w for w in result.warnings if "trička" in w]
    assert len(size_warnings) == 1
    assert "Anna Nováková" in size_warnings[0]
    assert "'?'" in size_warnings[0]


def test_tshirt_size_free_text_and_blank_are_unknown_with_warning(tmp_path):
    path = _write_survey(tmp_path, ["Anna", "Petr", "Klara"], ["blue shirt", None, "XXXL"])
    result = parse_raw_survey(path)
    assert [h.tshirt_size for h in result.helpers] == ["Unknown", "Unknown", "Unknown"]
    size_warnings = [w for w in result.warnings if "trička" in w]
    assert len(size_warnings) == 3
    assert "Anna" in size_warnings[0] and "blue shirt" in size_warnings[0]
    assert "Petr" in size_warnings[1]
    assert "Klara" in size_warnings[2] and "XXXL" in size_warnings[2]


def test_tshirt_size_gender_prefixed_sizes_are_stored_as_their_own_size(tmp_path):
    path = _write_survey(
        tmp_path,
        ["A", "B", "C", "D", "E"],
        ["pánské M", "Dámské S", " dámské  xl ", "Pánské tričko L", "plain M"],
    )
    result = parse_raw_survey(path)
    assert [h.tshirt_size for h in result.helpers] == ["pánské M", "dámské S", "dámské XL", "pánské L", "Unknown"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("M", "M"),
        ("pánské M", "pánské M"),
        ("PANSKE m", "pánské M"),
        ("dámské - S", "dámské S"),
        ("Dámské: xxl", "dámské XXL"),
        ("XL dámské", "dámské XL"),
        ("pánský L", "pánské L"),
        ("dámské", None),
        ("pánské dámské M", None),
        ("pánské M L", None),
        ("menší M", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_tshirt_size_is_flexible_about_the_gender_prefix(text, expected):
    assert parse_tshirt_size(text) == expected


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


# -- phone capture (display-only hint for uncertain matches) ---------------------


def _write_phone_survey(tmp_path, phones, phone_header):
    data = {_NAME_HEADER: [f"Helper {i}" for i in range(len(phones))]}
    if phone_header is not None:
        data[phone_header] = phones
    path = tmp_path / "survey.xlsx"
    pd.DataFrame(data).to_excel(path, index=False)
    return path


@pytest.mark.parametrize("header", ["Telefonní číslo", "Tvoje telefonní číslo", "Telefon", "Phone number"])
def test_phone_is_read_whatever_the_header_wording(tmp_path, header):
    path = _write_phone_survey(tmp_path, ["+420 111 222 333", "  777888999 ", None], header)
    result = parse_raw_survey(path)
    assert [h.phone for h in result.helpers] == ["+420 111 222 333", "777888999", None]
    assert not any("'phone'" in w for w in result.warnings)


def test_a_missing_phone_column_leaves_phones_empty_without_a_warning(tmp_path):
    result = parse_raw_survey(_write_phone_survey(tmp_path, [None], None))
    assert [h.phone for h in result.helpers] == [None]
    assert not any("'phone'" in w for w in result.warnings)


def test_a_numeric_phone_cell_is_kept_as_text(tmp_path):
    path = _write_phone_survey(tmp_path, [777888999], "Telefonní číslo")
    assert parse_raw_survey(path).helpers[0].phone == "777888999"


# ---- raw responses ----


def test_every_column_of_the_row_is_kept_as_a_raw_response_even_when_not_parsed(tmp_path):
    survey = generate_survey(3)
    survey["Něco navíc, co aplikace nečte"] = ["Mám rád/a koláče", None, 42.0]
    path = tmp_path / "survey.xlsx"
    survey.to_excel(path, index=False)

    result = parse_raw_survey(path)

    first = dict(result.helpers[0].survey_responses)
    assert [q for q, _ in result.helpers[0].survey_responses] == list(survey.columns)
    assert first["Něco navíc, co aplikace nečte"] == "Mám rád/a koláče"
    assert first["Tvoje jméno a příjmení"] == result.helpers[0].name
    assert first["Časová značka"] == "5. 1. 2026 08:00:00"
    # A blank cell stays in the list as an empty answer; a whole number loses its ".0".
    assert dict(result.helpers[1].survey_responses)["Něco navíc, co aplikace nečte"] == ""
    assert dict(result.helpers[2].survey_responses)["Něco navíc, co aplikace nečte"] == "42"
