"""Seeded, fully fictional survey exports for the tests.

Stands in for the real Season exports under ``data/`` (which hold helpers'
personal data and are neither committed nor present on a fresh checkout). The
headers copy the wording of the real forms, in the two layouts the parser has
to handle:

- ``"likert"``: the 2025/2026 form, one "Výběr role [X]" column per role;
- ``"freetext"``: the 2023/2024 form, one free-text "preferred role" and one
  "role you don't want" question.

Every name, e-mail and phone number is invented (``example.test`` addresses),
and the output depends only on ``(count, seed, style)``. The first rows are
shaped on purpose so each feature the tests look for is always present rather
than left to chance: see :func:`generate_survey`.
"""
from __future__ import annotations

import io
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

Style = Literal["likert", "freetext"]

FIRST_NAMES = [
    "Anna", "Petr", "Tereza", "Jakub", "Veronika", "Martin", "Klára", "Ondřej",
    "Eliška", "Filip", "Lucie", "Matěj",
]
LAST_NAMES = [
    "Nováková", "Svoboda", "Dvořáková", "Černý", "Procházková", "Kučera",
    "Veselá", "Horák", "Němcová", "Marek", "Pospíšilová", "Král",
]
MAX_HELPERS = len(FIRST_NAMES) * len(LAST_NAMES)

# The place question's answer options, as the form words them (address details
# in parentheses, and commas inside one option).
BUILDING_OPTIONS = [
    "Malá Strana (MS - Malostranské nám. 25)",
    "Karlov (budova M - Ke Karlovu 3)",
    "Impakt + Troja (budova N, budova T, areál Troja - V Holešovičkách 2)",
    "Karlín (Křižíkova)",
]
LIKERT_ANSWERS = ["Ano, prosím", "Klidně", "Nevadí mi", "Spíš ne", "Nechci"]
ROLE_NAMES = ["Opravovatel", "Měnič", "Skenovač", "Kreslič", "Fotograf"]
SIZES = ["XS", "S", "M", "L", "XL", "XXL"]

# A friend answer no registrant matches (neither by name nor, fuzzily, by
# first name), so it must come back as an unresolved friend name.
UNRESOLVABLE_FRIEND = "Kolega z fakulty"

_NAME = "Tvoje jméno a příjmení"
_COLUMNS = {
    "likert": {
        "place": "Na jakém místě bys chtěl/a pomáhat?",
        "friends": "Chtěl/a bys být v místnosti s někým konkrétním?",
    },
    "freetext": {
        "place": "Na jakém místě chceš pomáhat?",
        "friends": "Chceš být v místnosti s někým konkrétním?",
    },
}


def generate_survey(count: int = 110, seed: int = 0, style: Style = "likert") -> pd.DataFrame:
    """A survey export of ``count`` distinct registrants.

    Row 0 can bring both a notebook and a camera and accepts two Buildings,
    row 1 asks for a friend nobody can be matched to (``UNRESOLVABLE_FRIEND``)
    and for row 2's full name, row 3 names row 4 by full name only. The rest is
    drawn from ``seed``.
    """
    if not 0 < count <= MAX_HELPERS:
        raise ValueError(f"count must be between 1 and {MAX_HELPERS}")
    rng = random.Random(seed)
    names = [f"{first} {last}" for first in FIRST_NAMES for last in LAST_NAMES]
    names = rng.sample(names, count)
    columns = _COLUMNS[style]
    started = datetime(2026, 1, 5, 8, 0)

    rows = []
    for i, name in enumerate(names):
        buildings = rng.sample(BUILDING_OPTIONS, rng.choice([1, 1, 2, 3]))
        equipment = rng.sample(["Notebook", "Fotoaparát"], rng.choice([0, 1, 1, 2]))
        friends = ""
        if rng.random() < 0.3 and count > 1:
            friends = rng.choice([n for n in names if n != name])
        if i == 0:
            buildings, equipment = BUILDING_OPTIONS[:2], ["Notebook", "Fotoaparát"]
        elif i == 1 and count > 2:
            friends = f"{UNRESOLVABLE_FRIEND}, {names[2]}"
        elif i == 3 and count > 4:
            friends = names[4]
        row = {
            "Časová značka": started + timedelta(hours=3 * i),
            _NAME: name,
            "E-mailová adresa": f"helper{i + 1}@example.test",
            "Telefonní číslo": f"+420 777 {100 + i:03d} {200 + i:03d}",
            "Tvoje velikost trička": rng.choice(SIZES),
            "Můžeš něco z níže uvedených přinést na soutěž?": ", ".join(equipment),
            columns["place"]: ", ".join(buildings),
            columns["friends"]: friends or None,
        }
        if style == "likert":
            for role in ROLE_NAMES:
                row[f"Výběr role [{role}]"] = rng.choice(LIKERT_ANSWERS)
        else:
            wanted, unwanted = rng.sample(ROLE_NAMES, 2)
            row["Máš nějakou preferovanou roli, kterou bys chtěl/a při soutěži vykonávat?"] = wanted
            row["Máš nějakou roli, kterou bys určitě nechtěl/a vykonávat?"] = unwanted
        rows.append(row)
    return pd.DataFrame(rows)


def survey_bytes(count: int = 110, seed: int = 0, style: Style = "likert") -> bytes:
    """The generated export as the bytes of an ``.xlsx`` file."""
    buffer = io.BytesIO()
    generate_survey(count, seed, style).to_excel(buffer, index=False)
    return buffer.getvalue()


def write_survey(path: Path, count: int = 110, seed: int = 0, style: Style = "likert") -> Path:
    """Write the generated export to ``path`` (and return it)."""
    path.write_bytes(survey_bytes(count, seed, style))
    return path
