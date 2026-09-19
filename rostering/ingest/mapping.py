"""Declarative column-mapping table for raw survey exports.

The registration form's exact header wording changes almost every season
(see CLAUDE.md "Known historical data quirks"). Rather than hardcoding one
season's headers, each canonical field lists every historical phrasing seen
so far; matching is substring-based on normalized text (accent/whitespace
insensitive), tried in the order listed. Extend these lists — never branch
ingestion logic — when a new season introduces new wording.
"""
from __future__ import annotations

FIELD_HEADER_CANDIDATES: dict[str, list[str]] = {
    "name": [
        "Tvé jméno a příjme,ní",  # historical typo, seen verbatim in 2026 export
        "Tvé jméno a příjmení",
        "Tvoje jméno a příjmení",
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

# Substring (normalized) -> equipment flag. The equipment question is a
# multi-select checkbox, e.g. "Notebook, Fotoaparát".
EQUIPMENT_ALIASES: dict[str, str] = {
    "notebook": "notebook",
    "pocitac": "notebook",  # "počítač" = computer, seen in the 2023 form
    "fotoaparat": "camera",
}
