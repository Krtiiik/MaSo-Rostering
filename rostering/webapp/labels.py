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


# The keys of an Organizer's survey answers (``rostering.ingest.organizer_survey
# .ANSWER_FIELDS``, persisted as ``survey`` on the record) and of the other
# fields an import of the Organizers' sheet fills, in the order they are shown.
ORGANIZER_ANSWER_LABELS = {
    "simulation": "Zúčastní se Simulace",
    "event_day": "Připojí se v den soutěže",
    "role_VedouciMistnosti": "Role: Vedoucí místnosti",
    "role_VedouciBudovy": "Role: Vedoucí budovy",
    "role_Registrace": "Role: Registrace",
    "role_TechnickaPodpora": "Role: Technická podpora",
    "role_JinaMista": "Role: Jet na jiné místo",
    "places": "Preferovaná místa",
    "friends": "Kamarádi (z pomocníků a organizátorů)",
    "equipment": "Notebook / fotoaparát",
    "photo_consent": "Souhlas s focením",
    "comment": "Komentář",
}
ORGANIZER_FIELD_LABELS = {"phone": "Telefon", "tshirt_size": "Velikost trička", **ORGANIZER_ANSWER_LABELS}


def organizer_field_label(key: str) -> str:
    return ORGANIZER_FIELD_LABELS.get(key, key)


SEASON_LABEL_FIELD = "Označení ročníku"
SEASON_LABEL_HELP = "Rok a jaro nebo podzim, např. 2026-jaro."


# The list of differences shown when importing a Season (``rostering.season_diff``):
# its categories and the persisted field names are English, so only the display
# is translated; a field with no entry is shown as it is stored.
DIFF_CATEGORY_LABELS = {
    "label": "Označení ročníku",
    "helpers": "Pomocníci",
    "organizers": "Organizátoři",
    "assignments": "Přiřazení",
    "locks": "Zámky",
    "flags": "Příznaky (Nemůže se zúčastnit)",
    "tags": "Štítky",
    "forced_groups": "Vynucené skupinky kamarádů",
    "layout": "Budovy a místnosti",
    "manual_roles": "Manuální role",
    "merges": "Sloučené buňky",
    "solver_config": "Parametry rozřazování",
    "versions": "Uložené verze",
}
DIFF_FIELD_LABELS = {
    "name": "jméno",
    "email": "e-mail",
    "phone": "telefon",
    "tshirt_size": "velikost trička",
    "building": "budova",
    "room": "místnost",
    "role": "role",
    "colour": "barva",
    "note": "poznámka",
    "parent_id": "nadřazený štítek",
    "tags": "štítky",
    "friends": "kamarádi",
    "role_preferences": "preference rolí",
    "building_preferences": "preferované budovy",
    "can_bring_notebook": "notebook",
    "can_bring_camera": "fotoaparát",
    "cant_attend": "nemůže se zúčastnit",
    "locked": "zámek",
    "capacities": "počty lidí",
    "rules": "pravidla",
    "members": "členové",
}


# Parts of a Season the difference list reports as one piece, without fields.
DIFF_WHOLE_PARTS = ("manual_roles", "merges", "solver_config")


def diff_category_title(category: dict) -> str:
    return DIFF_CATEGORY_LABELS.get(category["key"], category["key"])


def diff_category_lines(category: dict) -> list[str]:
    """One line per difference of a category: ``+`` what the import adds, ``−``
    what it takes away and ``~`` what it changes (with the fields)."""
    lines = [f"+ {name}" for name in category["added"]]
    lines += [f"− {name}" for name in category["removed"]]
    for change in category["changed"]:
        fields = ", ".join(DIFF_FIELD_LABELS.get(f, f) for f in change["fields"])
        if fields:
            lines.append(f"~ {change['label']} ({fields})")
        elif category["key"] in DIFF_WHOLE_PARTS:
            lines.append("~ změněno")
        else:
            lines.append(f"~ {change['label']}")
    return lines
