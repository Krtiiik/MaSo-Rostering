"""Importing the Organizers' survey export (see CONTEXT.md "Organizer"): the
parser's column mapping, what a row becomes on the Organizer record, recognizing
the same person again on a re-upload, the summary it leaves behind and the
shirt size reaching the export. Everything runs on generated, fictional sheets."""
import importlib
import io

import openpyxl
import pandas as pd
import pytest

from rostering.domain import (
    Building,
    Competition,
    ManualRoles,
    Organizer,
    Role,
    Room,
    SolveResult,
    StructuralAssignment,
    StructuralRole,
)
from rostering.export.people import counted_people
from rostering.ingest.organizer_survey import parse_organizer_survey
from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

from tests.survey_factory import (
    ORGANIZER_HEADERS as H,
    generate_organizer_survey,
    organizer_survey_bytes,
    survey_bytes,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    ws = Workspace(root=tmp_path / "seasons")
    mutations.upload_responses(ws, survey_bytes(10, seed=3), "helpers.xlsx", label="2026-podzim")
    return ws


def _xlsx(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    return buffer.getvalue()


def _organizers(workspace) -> dict[str, dict]:
    return {o["name"]: o for o in workspace.load()["organizers"]}


def _sheet(*people: dict) -> bytes:
    """An Organizers' export of exactly these people (the keys of ``H`` as
    columns; whatever is left out is blank)."""
    base = generate_organizer_survey(1, seed=0).iloc[0].to_dict()
    rows = []
    for person in people:
        row = {column: None for column in base}
        row[H["event_day"]] = "Ano"
        for key, value in person.items():
            row[H[key]] = value
        rows.append(row)
    return _xlsx(pd.DataFrame(rows))


# ---------------------------------------------------------------- parser


def test_the_parser_reads_every_column_of_the_sheet(tmp_path):
    path = tmp_path / "organizers.xlsx"
    path.write_bytes(organizer_survey_bytes(6, seed=7))
    result = parse_organizer_survey(path)
    assert len(result.organizers) == 6
    row = result.organizers[3]
    assert row.phone.startswith("+420 606")
    assert row.tshirt_size.split()[0] in ("pánské", "dámské")
    assert set(row.answers) >= {"simulation", "event_day", "role_VedouciMistnosti", "role_JinaMista", "places", "photo_consent"}
    assert row.answers["role_VedouciBudovy"] in ("Preferoval bych dělat", "Nevadí mi dělat", "Nechci dělat")


def test_a_no_to_the_event_day_is_the_only_thing_that_marks_someone_absent(tmp_path):
    path = tmp_path / "organizers.xlsx"
    path.write_bytes(
        _sheet(
            {"name": "Anna Nováková", "event_day": "Ne"},
            {"name": "Petr Svoboda", "event_day": "Ano"},
            {"name": "Jana Veselá", "event_day": None},
            {"name": "Karel Horák", "event_day": "Nevím"},
        )
    )
    result = parse_organizer_survey(path)
    assert [r.attending for r in result.organizers] == [False, True, True, True]
    assert any("Karel Horák" in w and "Nevím" in w for w in result.warnings)


def test_an_unreadable_shirt_size_is_unknown_with_a_warning(tmp_path):
    path = tmp_path / "organizers.xlsx"
    path.write_bytes(organizer_survey_bytes(3, seed=7))
    result = parse_organizer_survey(path)
    assert result.organizers[1].tshirt_size == "Unknown"
    assert any("nerozpoznaná velikost trička" in w for w in result.warnings)


def test_a_helper_export_is_refused(tmp_path):
    path = tmp_path / "helpers.xlsx"
    path.write_bytes(survey_bytes(5))
    with pytest.raises(ValueError, match="nevypadá jako odpovědi organizátorů"):
        parse_organizer_survey(path)


# ---------------------------------------------------------------- import


def test_an_import_creates_the_organizers_with_their_fields(workspace):
    state = mutations.import_organizers(workspace, organizer_survey_bytes(5, seed=7), "organizers.xlsx")
    organizers = state["organizers"]
    assert len(organizers) == 5
    first = organizers[0]
    assert first["phone"].startswith("+420 606")
    assert first["tshirt_size"] in ("pánské S", "pánské M", "pánské L", "dámské XS", "dámské M")
    assert first["survey"]["event_day"] == "Ne"
    assert first["cant_attend"] is True  # row 0 answered "Ne"
    assert not organizers[1].get("cant_attend")
    assert "tshirt_size" not in organizers[1]  # the unreadable size stays Unknown
    assert "phone" not in organizers[2]  # a blank phone is no phone
    assert all(o["person_id"] and o["building"] is None for o in organizers)
    summary = mutations.organizer_upload_summary(workspace)
    assert [e["name"] for e in summary["new"]] == [o["name"] for o in organizers]
    assert summary["new"][0]["cant_attend"] is True
    assert any("velikost trička" in w for w in summary["warnings"])


def test_an_import_with_no_season_open_needs_a_label_and_changes_nothing(tmp_path):
    ws = Workspace(root=tmp_path / "empty")
    with pytest.raises(mutations.SeasonLabelRequired, match="označení"):
        mutations.import_organizers(ws, organizer_survey_bytes(2), "organizers.xlsx")
    assert ws.open_season() is None
    assert ws.load()["organizers"] == []


def test_an_import_with_no_season_open_creates_the_season(tmp_path):
    ws = Workspace(root=tmp_path / "empty")
    state = mutations.import_organizers(ws, organizer_survey_bytes(3, seed=7), "organizers.xlsx", label="2026-podzim")
    assert ws.open_season()["label"] == "2026-podzim"
    assert state["season"]["label"] == "2026-podzim"
    assert len(state["organizers"]) == 3
    assert state["helpers"] == []
    assert len(Workspace(root=tmp_path / "empty").load()["organizers"]) == 3  # stored, not a draft


def test_a_taken_label_refuses_the_import_and_creates_nothing(tmp_path):
    ws = Workspace(root=tmp_path / "empty")
    mutations.import_organizers(ws, organizer_survey_bytes(2, seed=7), "organizers.xlsx", label="2026-podzim")
    mutations.new_season(ws)
    with pytest.raises(mutations.RosteringError, match="již existuje"):
        mutations.import_organizers(ws, organizer_survey_bytes(2, seed=7), "organizers.xlsx", label="2026-podzim")
    assert ws.open_season() is None


def test_a_wrong_file_is_a_rostering_error_and_changes_nothing(workspace):
    with pytest.raises(mutations.RosteringError, match="nevypadá jako odpovědi organizátorů"):
        mutations.import_organizers(workspace, survey_bytes(4), "helpers.xlsx")
    assert workspace.load()["organizers"] == []


def test_a_hand_made_organizer_with_the_same_name_is_adopted(workspace):
    mutations.add_organizer(workspace, "Ludmila Dobrá")
    own_id = workspace.load()["organizers"][0]["id"]
    state = mutations.import_organizers(
        workspace,
        _sheet({"name": "ludmila dobra", "phone": "777111222", "size": "dámské M", "VedouciBudovy": "Nechci dělat"}),
        "organizers.xlsx",
    )
    assert len(state["organizers"]) == 1
    adopted = state["organizers"][0]
    assert adopted["id"] == own_id
    assert (adopted["phone"], adopted["tshirt_size"]) == ("777111222", "dámské M")
    assert adopted["survey"]["role_VedouciBudovy"] == "Nechci dělat"
    summary = mutations.organizer_upload_summary(workspace)
    assert [e["organizer_id"] for e in summary["adopted"]] == [own_id]
    assert summary["new"] == []


def test_the_same_name_twice_in_a_file_makes_two_organizers_with_a_warning(workspace):
    state = mutations.import_organizers(
        workspace, _sheet({"name": "Jan Novák", "phone": "1"}, {"name": "Jan Novák", "phone": "2"}), "organizers.xlsx"
    )
    assert [o["phone"] for o in state["organizers"]] == ["1", "2"]
    assert any("Jan Novák" in w and "2×" in w for w in mutations.organizer_upload_summary(workspace)["warnings"])


def test_a_name_a_helper_shares_is_reported_and_nothing_is_removed(workspace):
    helper = workspace.load()["helpers"][0]["name"]
    mutations.import_organizers(workspace, _sheet({"name": helper}), "organizers.xlsx")
    assert len(workspace.load()["helpers"]) == 10
    assert [e["name"] for e in mutations.organizer_upload_summary(workspace)["also_helper"]] == [helper]
    # Deleting the Helper clears the line.
    mutations.delete_helper(workspace, workspace.load()["helpers"][0]["id"])
    assert mutations.organizer_upload_summary(workspace)["also_helper"] == []


def test_an_email_column_recognizes_people_and_links_returners(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    ws = Workspace(root=tmp_path / "seasons")
    mutations.upload_responses(ws, survey_bytes(3), "helpers.xlsx", label="2025-podzim")
    mutations.add_organizer(ws, "Dana Stará", "dana@example.test")
    earlier = ws.load()["organizers"][0]["person_id"]
    mutations.new_season(ws)
    mutations.upload_responses(ws, survey_bytes(3), "helpers.xlsx", label="2026-podzim")

    df = generate_organizer_survey(1, seed=0)
    df.insert(0, "E-mailová adresa", ["Dana@Example.test"])
    df[H["name"]] = ["Dana S."]  # another spelling: only the e-mail says who it is
    state = mutations.import_organizers(ws, _xlsx(df), "organizers.xlsx")
    assert state["organizers"][0]["email"] == "dana@example.test"
    assert state["organizers"][0]["person_id"] == earlier


# ---------------------------------------------------------------- re-upload


def _import_two(workspace):
    return mutations.import_organizers(
        workspace,
        _sheet(
            {"name": "Anna Nováková", "phone": "111", "size": "pánské M", "VedouciBudovy": "Nevadí mi dělat"},
            {"name": "Petr Svoboda", "phone": "222", "size": "pánské L", "VedouciBudovy": "Nechci dělat"},
        ),
        "organizers.xlsx",
    )


def test_a_reupload_refreshes_in_place_and_reports_what_changed(workspace):
    first = _import_two(workspace)
    ids = {o["name"]: o["id"] for o in first["organizers"]}
    mutations.dismiss_organizer_upload_summary(workspace)

    state = mutations.import_organizers(
        workspace,
        _sheet(
            {"name": "Anna Nováková", "phone": "111", "size": "pánské L", "VedouciBudovy": "Nevadí mi dělat"},
            {"name": "Petr Svoboda", "phone": "222", "size": "pánské L", "VedouciBudovy": "Nechci dělat"},
        ),
        "organizers.xlsx",
    )
    assert {o["name"]: o["id"] for o in state["organizers"]} == ids
    assert _organizers(workspace)["Anna Nováková"]["tshirt_size"] == "pánské L"
    summary = mutations.organizer_upload_summary(workspace)
    assert summary["new"] == []
    assert [(e["name"], e["fields"]) for e in summary["changed"]] == [("Anna Nováková", ["tshirt_size"])]


def test_a_reupload_leaves_placement_tags_flags_and_hand_typed_fields_alone(workspace):
    first = _import_two(workspace)
    anna = next(o for o in first["organizers"] if o["name"] == "Anna Nováková")
    building = workspace.load()["config"][0]["name"]
    mutations.assign_organizer(workspace, anna["id"], "VedouciBudovy", building)
    mutations.update_organizer(workspace, anna["id"], phone="999 000")
    mutations.set_organizer_cant_attend(workspace, anna["id"], True, confirmed=True)
    petr = next(o for o in first["organizers"] if o["name"] == "Petr Svoboda")
    mutations.set_organizer_cant_attend(workspace, petr["id"], True)
    mutations.set_organizer_cant_attend(workspace, petr["id"], False)

    mutations.import_organizers(
        workspace,
        _sheet(
            {"name": "Anna Nováková", "phone": "111", "size": "pánské M", "event_day": "Ne"},
            {"name": "Petr Svoboda", "phone": "222", "size": "pánské L", "event_day": "Ne"},
        ),
        "organizers.xlsx",
    )
    organizers = _organizers(workspace)
    assert organizers["Anna Nováková"]["phone"] == "999 000"  # typed by hand
    assert organizers["Anna Nováková"]["cant_attend"] is True
    assert not organizers["Petr Svoboda"].get("cant_attend")  # the sheet's "Ne" does not re-flag
    changed = {e["name"]: e["fields"] for e in mutations.organizer_upload_summary(workspace)["changed"]}
    assert "event_day" in changed["Petr Svoboda"]


def test_organizers_missing_from_a_reupload_are_listed_and_kept(workspace):
    _import_two(workspace)
    mutations.add_organizer(workspace, "Vytvořen Ručně")  # never in a sheet: never "missing"
    state = mutations.import_organizers(workspace, _sheet({"name": "Anna Nováková", "phone": "111"}), "organizers.xlsx")
    assert {o["name"] for o in state["organizers"]} == {"Anna Nováková", "Petr Svoboda", "Vytvořen Ručně"}
    assert [e["name"] for e in mutations.organizer_upload_summary(workspace)["missing"]] == ["Petr Svoboda"]


def test_an_unread_summary_accumulates_and_dismissing_clears_it(workspace):
    _import_two(workspace)
    mutations.import_organizers(
        workspace,
        _sheet({"name": "Anna Nováková"}, {"name": "Petr Svoboda"}, {"name": "Eva Nová"}),
        "organizers.xlsx",
    )
    summary = mutations.organizer_upload_summary(workspace)
    assert sorted(e["name"] for e in summary["new"]) == ["Anna Nováková", "Eva Nová", "Petr Svoboda"]
    mutations.dismiss_organizer_upload_summary(workspace)
    assert mutations.organizer_upload_summary(workspace) is None


# ---------------------------------------------------------------- editing and export


def test_an_organizers_phone_and_shirt_size_are_edited_by_hand(workspace):
    _import_two(workspace)
    anna = _organizers(workspace)["Anna Nováková"]
    state = mutations.update_organizer(workspace, anna["id"], phone="  ", tshirt_size="dámské S")
    record = next(o for o in state["organizers"] if o["id"] == anna["id"])
    assert "phone" not in record and record["tshirt_size"] == "dámské S"
    assert set(record["hand_typed"]) == {"phone", "tshirt_size"}
    with pytest.raises(mutations.RosteringError, match="Neznámá velikost"):
        mutations.update_organizer(workspace, anna["id"], tshirt_size="gigantické")
    mutations.update_organizer(workspace, anna["id"], tshirt_size="Unknown")
    assert "tshirt_size" not in _organizers(workspace)["Anna Nováková"]


def test_the_export_counts_an_organizer_in_their_own_shirt_size():
    buildings = {"A": Building(name="A", rooms=[Room(name="A1")])}
    comp = Competition(
        buildings=buildings,
        helpers=[],
        organizers=[
            Organizer(id=1, name="Anna", tshirt_size="dámské M"),
            Organizer(id=2, name="Petr"),
        ],
    )
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="A", organizer_id=1),
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="A", organizer_id=2),
        ]
    )
    result = SolveResult(assignments=[], status="OPTIMAL", objective_value=0.0)
    sizes = {p.name: p.tshirt_size for p in counted_people(comp, result, manual)}
    assert sizes == {"Anna": "dámské M", "Petr": "Unknown"}


def test_the_shirt_size_survives_the_state_round_trip(workspace):
    _import_two(workspace)
    competition = mutations._build_competition(workspace.load())
    assert {o.name: o.tshirt_size for o in competition.organizers} == {"Anna Nováková": "pánské M", "Petr Svoboda": "pánské L"}
