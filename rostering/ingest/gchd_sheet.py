"""Reader for the optional "GChD" sheet of a Helpers' survey export (.xlsx).

Besides the response sheet (always the first one, read by ``raw_survey``), the
export may carry a sheet named GChD: the responses of students of the GCHD
school, in the same layout plus two questions the other responses lack -- are
you a current GCHD student, and which class are you in. The sheet is optional;
this module only reads it, and what becomes of the classes (the GCHD Tag and its
class Tags) is decided by ``mutations`` (see CONTEXT.md "GCHD sheet").
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from rostering.domain import normalize_email, normalize_name
from rostering.ingest.mapping import GCHD_FIELD_HEADER_CANDIDATES
from rostering.ingest.raw_survey import _cell_str, _find_columns

SHEET_NAME = "GChD"


@dataclass(frozen=True)
class GchdStudent:
    """One populated row of the GChD sheet."""

    name: str
    email: Optional[str]  # normalized
    school_class: str  # as the student wrote it, whitespace tidied


def _is_gchd_sheet(name: str) -> bool:
    return normalize_name(name) == normalize_name(SHEET_NAME)


def read_gchd_sheet(path: str | Path) -> list[GchdStudent]:
    """The students listed on the export's GChD sheet; empty when the export has
    no such sheet (the first sheet is the response sheet itself and never
    counts), the sheet lacks the class question, or no row names a class.

    A row counts when its class cell is filled and the "current student" answer,
    if the sheet asks it, is not a plain "no"."""
    with pd.ExcelFile(path) as workbook:
        names = [n for n in workbook.sheet_names[1:] if _is_gchd_sheet(str(n))]
        if not names:
            return []
        df = workbook.parse(names[0])

    columns = _find_columns(list(df.columns), GCHD_FIELD_HEADER_CANDIDATES)
    class_col = columns.get("school_class")
    if class_col is None:
        return []
    name_col = columns.get("name")
    email_col = columns.get("email")
    student_col = columns.get("student")

    students: list[GchdStudent] = []
    for _, row in df.iterrows():
        school_class = " ".join((_cell_str(row.get(class_col)) or "").split())
        if not school_class:
            continue
        if student_col is not None and normalize_name(_cell_str(row.get(student_col))) == "ne":
            continue
        name = (_cell_str(row.get(name_col)) if name_col else None) or ""
        email = normalize_email(_cell_str(row.get(email_col))) if email_col else None
        if not name and not email:
            continue
        students.append(GchdStudent(name=name, email=email, school_class=school_class))
    return students
