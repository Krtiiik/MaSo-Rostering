"""Parsing free Czech text into Role / Preference enum values.

Shared by both ingestion paths (raw survey export and the legacy simplified
CSV) so the two never drift apart.
"""
from __future__ import annotations

from typing import Optional

from rostering.domain import Preference, Role, normalize_name

_PREFERENCE_VARIANTS: dict[Preference, list[str]] = {
    Preference.Ano: ["Ano", "Ano, prosím", "Ano prosím", "Ano prosim"],
    Preference.Klidne: ["Klidně", "Klidne"],
    Preference.Nevadi: ["Nevadí", "Nevadí mi", "Nevadi mi", "Nevadi"],
    Preference.Spise_ne: ["Spíš ne", "Spise ne", "Spíše ne", "Spise_ne"],
    Preference.Ne: ["Ne", "Nechci"],
}

_PREFERENCE_LOOKUP: dict[str, Preference] = {
    normalize_name(text): pref
    for pref, variants in _PREFERENCE_VARIANTS.items()
    for text in variants
}


def parse_preference(text: Optional[str]) -> Optional[Preference]:
    if not text or not text.strip():
        return None
    lookup = normalize_name(text)
    if lookup in _PREFERENCE_LOOKUP:
        return _PREFERENCE_LOOKUP[lookup]
    for pref in Preference:
        if normalize_name(pref.name) == lookup:
            return pref
    return None


def parse_role_token(text: Optional[str]) -> Optional[Role]:
    if not text or not text.strip():
        return None
    lookup = normalize_name(text)
    for role in Role:
        if normalize_name(role.value) == lookup or normalize_name(role.name) == lookup:
            return role
    return None
