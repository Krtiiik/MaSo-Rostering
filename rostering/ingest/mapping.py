"""Declarative column-mapping table for raw survey exports.

The registration form's exact header wording changes almost every season
(see CLAUDE.md "Known historical data quirks"). Rather than hardcoding one
season's headers, each canonical field lists every historical phrasing seen
so far; matching is substring-based on normalized text (accent/whitespace
insensitive), tried in the order listed. Extend these lists — never branch
ingestion logic — when a new season introduces new wording.
"""
from __future__ import annotations

from typing import Optional

from rostering.domain import normalize_name

FIELD_HEADER_CANDIDATES: dict[str, list[str]] = {
    # Google Forms' automatic first column. Only feeds the Season label
    # prefill (see rostering.persistence.season_label), so its absence is
    # not a warning.
    "timestamp": [
        "Časová značka",
        "Časové razítko",
        "Timestamp",
    ],
    "name": [
        "Tvé jméno a příjme,ní",  # historical typo, seen verbatim in 2026 export
        "Tvé jméno a příjmení",
        "Tvoje jméno a příjmení",
    ],
    # The contact e-mail: Google Forms' own "collect e-mail addresses" column
    # or a form question. Only the wording varies, never the meaning; matching
    # ignores case, accents, spaces and hyphens, so "e-mail" also covers
    # "Email" and "E-mailová adresa" etc.
    "email": [
        "E-mailová adresa",
        "Email Address",
        "Tvůj e-mail",
        "E-mail",
    ],
    # The contact phone number. Only ever shown as a hint next to an uncertain
    # Person match — never a match key (returners change it far too often).
    "phone": [
        "Telefonní číslo",
        "Telefon",
        "Phone",
    ],
    "building_preference": [
        "Na jakém místě bys chtěl/a pomáhat?",
        "Na jakém místě chceš pomáhat?",
        "Místo",
    ],
    "friends": [
        "Chtěl/a bys být v místnosti s někým konkrétním?",
        "Chceš být v místnosti s někým konkrétním?",
    ],
    "equipment": [
        "Můžeš něco z níže uvedených přinést na soutěž?",
    ],
    "tshirt_size": [
        "Tvoje velikost trička",  # worded identically in every season so far
    ],
    "role_pref_Opravovatel": ["Výběr role [Opravovatel]"],
    "role_pref_Menic": ["Výběr role [Měnič]"],
    "role_pref_Skenovac": ["Výběr role [Skenovač]"],
    "role_pref_Kreslic": ["Výběr role [Kreslič]"],
    "role_pref_Fotograf": ["Výběr role [Fotograf]"],
    # Older seasons (e.g. 2023-podzim, 2024-jaro) ask one free-text
    # "preferred role" question and one "role you don't want" question
    # instead of the 5 per-role Likert columns above.
    "preferred_role_freetext": [
        "Máš nějakou preferovanou roli, kterou bys chtěl/a při soutěži vykonávat?",
        "Máš nějakou preferovanou roli, kterou bys při soutěži chtěl/a vykonávat?",
    ],
    "unwanted_role_freetext": [
        "Máš nějakou roli, kterou bys určitě nechtěl/a vykonávat?",
        "Máš nějakou roli, kterou bys při soutěži určitě nechtěl/a vykonávat?",
    ],
}

# The Organizers' own form (see CONTEXT.md "Organizer"): a different sheet with
# its own questions, so its columns are listed apart from the Helpers'. The same
# rules apply (substring match on normalized text, tried in the order listed;
# extend the lists, never branch the parser). The answers every field after
# ``tshirt_size`` holds are kept as the Organizer's read-only survey answers.
ORGANIZER_FIELD_HEADER_CANDIDATES: dict[str, list[str]] = {
    "timestamp": FIELD_HEADER_CANDIDATES["timestamp"],
    "name": [
        "Jméno a příjmení",
        "Tvé jméno a příjmení",
        "Tvoje jméno a příjmení",
    ],
    "email": FIELD_HEADER_CANDIDATES["email"],
    "phone": FIELD_HEADER_CANDIDATES["phone"],
    "tshirt_size": ["Velikost trička"],
    "simulation": ["Zúčastníš se Simulace", "Simulace"],
    "event_day": ["Připojíš se v den soutěže", "v den soutěže (pátek"],
    "role_VedouciMistnosti": ["[Vedoucí místnosti]"],
    "role_VedouciBudovy": ["[Vedoucí budovy]"],
    "role_Registrace": ["[Registrace]"],
    "role_TechnickaPodpora": ["[Technická podpora]"],
    "role_JinaMista": ["[Jet na jiné místo]"],
    "places": ["Preferované místo", "Preferované místa"],
    "friends": ["Chceš být/nebýt v místnosti", "být v místnosti s někým konkrétním"],
    "equipment": ["přinést notebook nebo foťák", "přinést notebook"],
    "photo_consent": ["pořizováním fotografií", "pořizování fotografií"],
    "comment": ["Prostor pro další komentáře", "další komentáře"],
}

# The optional "GChD" sheet of a Helpers' export (see CONTEXT.md "GCHD sheet"): a
# table of the same form's responses from students of the GCHD school, with the
# school questions the other responses lack. Same matching rules as above.
GCHD_FIELD_HEADER_CANDIDATES: dict[str, list[str]] = {
    "name": FIELD_HEADER_CANDIDATES["name"],
    "email": FIELD_HEADER_CANDIDATES["email"],
    "student": ["Jsi aktuální student GCHD?", "student GCHD"],
    "school_class": ["Z jaké jsi třídy?", "Z jaké třídy"],
}

# Substring (normalized) -> canonical building name. The place question's
# answer text includes address details in parentheses, so matching is
# substring-based, not exact.
BUILDING_ALIASES: dict[str, str] = {
    "malastrana": "Malá Strana",
    "karlov": "Karlov",
    "impakt": "Impakt + Troja",
    "troja": "Impakt + Troja",
    "krizikova": "Karlín",
    "karlin": "Karlín",
}


def resolve_building_aliases(text: Optional[str]) -> set[str]:
    """Canonical building names whose alias appears in ``text`` (any
    diacritics/case/spacing)."""
    norm_text = normalize_name(text)
    return {name for alias, name in BUILDING_ALIASES.items() if alias in norm_text}


def building_keys(name: Optional[str]) -> frozenset[str]:
    """Comparison keys for a building name, so a Helper's Building preference
    (as ingestion spells it, e.g. "Malá Strana", "Impakt + Troja") can be
    matched against a Season config's own spelling ("Mala Strana", "Troja").
    Two names denote the same Building iff their key sets intersect. A name no
    alias recognizes falls back to its normalized text."""
    canonical = resolve_building_aliases(name)
    if canonical:
        return frozenset(normalize_name(c) for c in canonical)
    return frozenset({normalize_name(name)})


# Substring (normalized) -> equipment flag. The equipment question is a
# multi-select checkbox, e.g. "Notebook, Fotoaparát".
EQUIPMENT_ALIASES: dict[str, str] = {
    "notebook": "notebook",
    "pocitac": "notebook",  # "počítač" = computer, seen in the 2023 form
    "fotoaparat": "camera",
}
