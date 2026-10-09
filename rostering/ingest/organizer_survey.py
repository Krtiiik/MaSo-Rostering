"""Parser for the Organizers' survey export (.xlsx, a Google Forms response sheet).

A sibling of ``raw_survey`` for the other form: the Organizers answer their own
questions (Simulation and event-day attendance, preferences for the Organizer
role slots, places, friends, equipment, photo consent, a comment) and, like the
Helpers, give a name, a phone number and a T-shirt size. Columns are found
through the candidate table in ``mapping.py``, never by one fixed phrase.

Only the name, phone, T-shirt size and e-mail (when the sheet has one) become
fields of the Organizer; everything else is kept as the read-only answers the
person sheet shows, as the text the person gave (see CONTEXT.md "Organizer").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from rostering.domain import (
    UNKNOWN_TSHIRT_SIZE,
    normalize_email,
    normalize_name,
    parse_tshirt_size,
)
from rostering.ingest.mapping import ORGANIZER_FIELD_HEADER_CANDIDATES
from rostering.ingest.raw_survey import _cell_str, _phone_str

# The survey answers kept on the Organizer, in the order they are shown. The keys
# are persisted on the record (``survey``), so only their display is translated
# (``rostering.webapp.labels.ORGANIZER_ANSWER_LABELS``).
ANSWER_FIELDS: tuple[str, ...] = (
    "simulation",
    "event_day",
    "role_VedouciMistnosti",
    "role_VedouciBudovy",
    "role_Registrace",
    "role_TechnickaPodpora",
    "role_JinaMista",
    "places",
    "friends",
    "equipment",
    "photo_consent",
    "comment",
)

# Columns only the Organizers' form has: a sheet with none of them is not one.
_ORGANIZER_ONLY_FIELDS = tuple(f for f in ANSWER_FIELDS if f.startswith("role_")) + ("simulation", "event_day")


@dataclass
class OrganizerRow:
    """One Organizer of the export."""

    name: str
    email: str | None = None  # normalized
    phone: str | None = None
    tshirt_size: str = UNKNOWN_TSHIRT_SIZE
    # False only for a plain "no" to the event-day question: a blank or an
    # unrecognized answer never flags anyone.
    attending: bool = True
    # ``ANSWER_FIELDS`` key -> the answer as written (blank answers are absent).
    answers: dict[str, str] = field(default_factory=dict)


@dataclass
class OrganizerSurveyResult:
    organizers: list[OrganizerRow]
    warnings: list[str]


def _find_columns(headers: list[str]) -> dict[str, str]:
    normalized_headers = {h: normalize_name(str(h)) for h in headers}
    found: dict[str, str] = {}
    for key, candidates in ORGANIZER_FIELD_HEADER_CANDIDATES.items():
        for candidate in candidates:
            norm_candidate = normalize_name(candidate)
            match = next((h for h, nh in normalized_headers.items() if norm_candidate in nh and h not in found.values()), None)
            if match is not None:
                found[key] = match
                break
    return found


def _is_yes(text: str) -> bool:
    return normalize_name(text).startswith("ano")


def _is_no(text: str) -> bool:
    norm = normalize_name(text)
    return norm == "ne" or norm.startswith(("ne,", "nemu", "nepri", "nebud", "nezuc", "nechci", "nejdu"))


def parse_organizer_survey(path: str | Path) -> OrganizerSurveyResult:
    """Parse an Organizers' survey export. Raises ``ValueError`` (a Czech
    message) for a file with no name column or that is not the Organizers' form."""
    df = pd.read_excel(path)
    headers = list(df.columns)
    columns = _find_columns(headers)
    warnings: list[str] = []

    name_col = columns.get("name")
    if name_col is None:
        raise ValueError(f"V souboru se nepodařilo najít sloupec se jménem — hlavičky byly: {headers}")
    if not any(f in columns for f in _ORGANIZER_ONLY_FIELDS):
        raise ValueError(
            "Tento soubor nevypadá jako odpovědi organizátorů (chybí otázky o rolích organizátorů a o účasti). "
            "Odpovědi pomocníků se nahrávají na záložce Lidé v kartě Soubor s odpověďmi."
        )

    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].reset_index(drop=True)
    tshirt_col, email_col, phone_col = columns.get("tshirt_size"), columns.get("email"), columns.get("phone")

    rows: list[OrganizerRow] = []
    seen: dict[str, int] = {}
    for _, record in df.iterrows():
        name = str(record[name_col]).strip()
        row = OrganizerRow(name=name)
        seen[normalize_name(name)] = seen.get(normalize_name(name), 0) + 1
        if email_col:
            row.email = normalize_email(_cell_str(record.get(email_col)))
        if phone_col:
            row.phone = _phone_str(record.get(phone_col))
        if tshirt_col:
            text = _cell_str(record.get(tshirt_col))
            size = parse_tshirt_size(text)
            if size is None:
                warnings.append(f"{name}: nerozpoznaná velikost trička {text or ''!r}")
            else:
                row.tshirt_size = size
        for key in ANSWER_FIELDS:
            column = columns.get(key)
            text = _cell_str(record.get(column)) if column else None
            if text:
                row.answers[key] = text
        event_day = row.answers.get("event_day")
        if event_day and not _is_yes(event_day):
            if _is_no(event_day):
                row.attending = False
            else:
                warnings.append(f"{name}: nerozpoznaná odpověď o účasti v den soutěže {event_day!r} — bráno jako účast")
        rows.append(row)

    for key, count in seen.items():
        if count > 1:
            shown = next(r.name for r in rows if normalize_name(r.name) == key)
            warnings.append(f"{shown}: {count}× v souboru — každý řádek je zvláštní organizátor")
    for key in ("tshirt_size", "phone"):
        if key not in columns:
            label = {"tshirt_size": "velikost trička", "phone": "telefon"}[key]
            warnings.append(f"Sloupec pro {label} nebyl v souboru nalezen — údaj zůstal prázdný u všech organizátorů")
    return OrganizerSurveyResult(organizers=rows, warnings=warnings)
