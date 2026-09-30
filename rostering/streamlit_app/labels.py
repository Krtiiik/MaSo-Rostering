"""The Czech labels the app shares between modules (tab names double as the
tab strip's state keys, so they live in one place)."""
from __future__ import annotations

APP_TITLE = "Rozdělování pomocníků"

TAB_PEOPLE = "1. Lidé"
TAB_TAGS = "2. Štítky"
TAB_FORCED = "3. Vynucené skupinky kamarádů"
TAB_BUILDINGS = "4. Budovy"
TAB_SOLVER = "5. Parametry rozřazování"
TAB_ROSTER = "6. Rozdělení pomocníků"

TABS = [TAB_PEOPLE, TAB_TAGS, TAB_FORCED, TAB_BUILDINGS, TAB_SOLVER, TAB_ROSTER]

# The survey answers that can change for a placed Helper are stored under these
# English names (``mutations._MATERIAL_ANSWERS``, persisted on the record), so
# only their display is translated.
ANSWER_LABELS = {
    "Building preference": "Preferované budovy",
    "Preferences": "Preference rolí",
    "Equipment": "Vybavení",
}


def answer_label(name: str) -> str:
    return ANSWER_LABELS.get(name, name)


SEASON_LABEL_FIELD = "Označení ročníku"
SEASON_LABEL_HELP = "Rok a jaro nebo podzim, např. 2026-jaro."
