"""The optional "GChD" sheet of a Helpers' export: when it names classes, the
upload creates the GCHD Tag, one child Tag per class and tags the Helpers with
the same e-mail. Mutation-layer tests against a temp-dir workspace and generated
workbooks (never anything from data/)."""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

from rostering.ingest.gchd_sheet import read_gchd_sheet
from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

_NAME = "Tvé jméno a příjmení"
_EMAIL = "E-mailová adresa"
_STUDENT = "Jsi aktuální student GCHD?"
_CLASS = "Z jaké jsi třídy?"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "seasons")


def _workbook(helpers, gchd=None, gchd_sheet_name="GChD") -> bytes:
    """``helpers``: (name, e-mail) rows of the response sheet; ``gchd``: (name,
    e-mail, student answer, class) rows of the GChD sheet, or None for no sheet."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame(
            {
                "Časová značka": [datetime(2026, 9, 2)] * len(helpers),
                _NAME: [n for n, _ in helpers],
                _EMAIL: [e for _, e in helpers],
            }
        ).to_excel(writer, sheet_name="Odpovědi formuláře 1", index=False)
        if gchd is not None:
            pd.DataFrame(
                {
                    "Časová značka": [datetime(2026, 9, 2)] * len(gchd),
                    _EMAIL: [g[1] for g in gchd],
                    _NAME: [g[0] for g in gchd],
                    _STUDENT: [g[2] for g in gchd],
                    _CLASS: [g[3] for g in gchd],
                }
            ).to_excel(writer, sheet_name=gchd_sheet_name, index=False)
    return buffer.getvalue()


HELPERS = [
    ("Anna Nováková", "anna@gchd.cz"),
    ("Petr Svoboda", "petr@gchd.cz"),
    ("Jana Černá", "jana@gchd.cz"),
    ("Karel Outsider", "karel@example.test"),
]
GCHD_ROWS = [
    ("Anna Nováková", "anna@gchd.cz", "Ano", "6.M"),
    ("Petr Svoboda", " Petr@GCHD.cz ", "Ano", "2.c"),
    ("Jana Černá", "jana@gchd.cz", "Ano", "6.M"),
]


def _carried(state, email):
    names = {t["id"]: t["name"] for t in state["tags"]}
    helper = next(h for h in state["helpers"] if h["email"] == email)
    return [names[i] for i in helper.get("tags") or []]


def _tree(state):
    names = {t["id"]: t["name"] for t in state["tags"]}
    return {t["name"]: names.get(t["parent_id"]) for t in state["tags"]}


def test_upload_creates_the_gchd_tree_and_tags_matched_helpers(workspace):
    state = mutations.upload_responses(workspace, _workbook(HELPERS, GCHD_ROWS), "x.xlsx", label="2026-podzim")

    assert _tree(state) == {"GCHD": None, "6.M": "GCHD", "2.c": "GCHD"}
    assert _carried(state, "anna@gchd.cz") == ["6.M"]
    assert _carried(state, "petr@gchd.cz") == ["2.c"]  # the class exactly as written
    assert _carried(state, "jana@gchd.cz") == ["6.M"]
    assert _carried(state, "karel@example.test") == []
    assert not [w for w in state["ingestion_warnings"] if "GChD" in w]


def test_students_without_a_matching_helper_are_reported_not_tagged(workspace):
    rows = [*GCHD_ROWS, ("Marek Nikdo", "nikdo@gchd.cz", "Ano", "8.M")]

    state = mutations.upload_responses(workspace, _workbook(HELPERS, rows), "x.xlsx", label="2026-podzim")

    assert _tree(state)["8.M"] == "GCHD"  # the class is still in the responses
    (warning,) = [w for w in state["ingestion_warnings"] if "GChD" in w]
    assert "Marek Nikdo" in warning


def test_a_student_answering_no_is_skipped(workspace):
    rows = [("Anna Nováková", "anna@gchd.cz", "Ne", "6.M"), ("Petr Svoboda", "petr@gchd.cz", "Ano", "5.M")]

    state = mutations.upload_responses(workspace, _workbook(HELPERS, rows), "x.xlsx", label="2026-podzim")

    assert _tree(state) == {"GCHD": None, "5.M": "GCHD"}
    assert _carried(state, "anna@gchd.cz") == []


@pytest.mark.parametrize(
    "gchd",
    [None, [], [("Anna Nováková", "anna@gchd.cz", "Ano", None)]],
    ids=["no sheet", "empty sheet", "no class given"],
)
def test_nothing_is_created_without_populated_classes(workspace, gchd):
    state = mutations.upload_responses(workspace, _workbook(HELPERS, gchd), "x.xlsx", label="2026-podzim")

    assert state["tags"] == []


def test_a_sheet_that_is_not_named_gchd_is_ignored(workspace):
    data = _workbook(HELPERS, GCHD_ROWS, gchd_sheet_name="Něco jiného")

    state = mutations.upload_responses(workspace, data, "x.xlsx", label="2026-podzim")

    assert state["tags"] == []


def test_reupload_reuses_existing_tags_and_keeps_other_tags(workspace):
    mutations.upload_responses(workspace, _workbook(HELPERS, GCHD_ROWS), "x.xlsx", label="2026-podzim")
    state = mutations.add_tag(workspace, "Foto")
    foto = next(t["id"] for t in state["tags"] if t["name"] == "Foto")
    anna = next(h["id"] for h in state["helpers"] if h["email"] == "anna@gchd.cz")
    mutations.add_tag_to_helpers(workspace, foto, [anna])

    state = mutations.upload_responses(workspace, _workbook(HELPERS, GCHD_ROWS), "x.xlsx")

    assert sorted(t["name"] for t in state["tags"]) == ["2.c", "6.M", "Foto", "GCHD"]
    assert sorted(_carried(state, "anna@gchd.cz")) == ["6.M", "Foto"]


def test_an_existing_tag_of_the_same_name_is_used_as_it_is(workspace):
    mutations.upload_responses(workspace, _workbook(HELPERS), "x.xlsx", label="2026-podzim")
    mutations.add_tag(workspace, "6.m", colour="#112233")

    state = mutations.upload_responses(workspace, _workbook(HELPERS, GCHD_ROWS), "x.xlsx")

    (six,) = [t for t in state["tags"] if t["name"].lower() == "6.m"]
    assert six["name"] == "6.m" and six["colour"] == "#112233" and six["parent_id"] is None
    assert _carried(state, "anna@gchd.cz") == ["6.m"]


def test_reader_returns_students_with_normalized_email_and_tidy_class(tmp_path):
    path = tmp_path / "x.xlsx"
    path.write_bytes(_workbook(HELPERS, [("Anna", " Anna@GCHD.cz ", "Ano", " 6. M  ")]))

    (student,) = read_gchd_sheet(path)

    assert (student.name, student.email, student.school_class) == ("Anna", "anna@gchd.cz", "6. M")
