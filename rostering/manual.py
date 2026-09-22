"""Loader for the manual, post-solve role overlay file (see CLAUDE.md
"Out-of-solver roles"). The solver never touches these — they're hand-typed
by the organizer and merged into the export.

Expected YAML shape::

    structural:
      - role: VedouciBudovy        # or VedouciMistnosti / PravaRuka / TechnickaPodpora
        building: Malá Strana
        room: S3                   # only meaningful for VedouciMistnosti / PravaRuka
        helper_id: 12               # a registered helper, or...
        helper_name: Some Person    # ...a hand-typed name for someone unregistered
    overlay:
      - role: Registrace            # or UvadeciUcastniku / FoceniPredavaniCen
        helper_id: 3
        helper_name: Some Person
        building: Malá Strana        # building-scoped for Registrace (room
        room: S3                     # left unset); room also required for
                                      # UvadeciUcastniku/FoceniPredavaniCen
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from rostering.domain import (
    ManualRoles,
    OverlayAssignment,
    OverlayRole,
    StructuralAssignment,
    StructuralRole,
)
from rostering.domain import normalize_name


def _match_enum(enum_cls, value: str):
    lookup = normalize_name(value)
    for member in enum_cls:
        if normalize_name(member.name) == lookup or normalize_name(member.value) == lookup:
            return member
    raise ValueError(f"Unknown {enum_cls.__name__}: {value!r}")


def load_manual_roles(path: Optional[str | Path]) -> ManualRoles:
    if path is None or not Path(path).exists():
        return ManualRoles()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    structural = [
        StructuralAssignment(
            role=_match_enum(StructuralRole, entry["role"]),
            building=entry["building"],
            helper_id=entry.get("helper_id"),
            helper_name=entry.get("helper_name"),
            room=entry.get("room"),
        )
        for entry in data.get("structural", []) or []
    ]
    overlay = [
        OverlayAssignment(
            role=_match_enum(OverlayRole, entry["role"]),
            helper_id=entry.get("helper_id"),
            helper_name=entry.get("helper_name"),
            building=entry.get("building"),
            room=entry.get("room"),
        )
        for entry in data.get("overlay", []) or []
    ]
    return ManualRoles(structural=structural, overlay=overlay)
