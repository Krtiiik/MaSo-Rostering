"""Core domain model shared by ingestion, the solver, and export.

Terminology follows CLAUDE.md — read that first if a term
here (Role, building preference "set", friend scoring, manual/overlay roles)
is unclear.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


class Role(Enum):
    """The 6 roles the solver assigns. See CLAUDE.md for the full glossary."""

    Opravovatel = "Opravovatel"
    Menic = "Měnič"
    Skenovac = "Skenovač"
    Kreslic = "Kreslič"
    Fotograf = "Fotograf"
    Zaloha = "Záloha"


class Preference(IntEnum):
    """5-point ordinal scale for role preferences. Higher = more willing."""

    Ano = 5
    Klidne = 4
    Nevadi = 3
    Spise_ne = 2
    Ne = 1


class StructuralRole(Enum):
    """Manual, post-solve leadership/support roles (see CLAUDE.md)."""

    VedouciBudovy = "Vedoucí budovy"
    PravaRuka = "Pravá ruka"
    VedouciMistnosti = "Vedoucí místností"
    TechnickaPodpora = "Technická podpora"


class OverlayRole(Enum):
    """Manual, post-solve before/after-event duties layered on top of a
    helper's solved role (see CLAUDE.md)."""

    Registrace = "Registrace"
    UvadeciUcastniku = "Uvaděči účastníků"
    FoceniPredavaniCen = "Focení předávání cen"


def normalize_name(value: Optional[str]) -> str:
    """Diacritics/whitespace-insensitive normalization used throughout
    ingestion to match Czech free text across seasons."""
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(
        ch for ch in normalized.lower() if not unicodedata.combining(ch)
    ).replace(" ", "").replace("_", "").replace("-", "")


@dataclass
class Helper:
    id: int
    name: str
    role_preferences: dict[Role, Preference] = field(default_factory=dict)
    # Acceptable buildings (the form's place question is multi-select) —
    # empty set means no preference expressed.
    building_preferences: frozenset[str] = field(default_factory=frozenset)
    # IDs of helpers this helper asked to share a room with (soft, see
    # rostering.solver.scoring for how requests are scored).
    friends: list[int] = field(default_factory=list)
    can_bring_notebook: bool = False
    can_bring_camera: bool = False
    # Free-text friend names that could not be resolved to a helper id
    # during ingestion — surfaced so the season's data can be fixed by hand
    # rather than silently losing the preference.
    unresolved_friend_names: list[str] = field(default_factory=list)


@dataclass
class RoleCapacity:
    minimum: int = 0


@dataclass
class Room:
    name: str
    capacities: dict[Role, RoleCapacity] = field(default_factory=dict)


@dataclass
class Building:
    name: str
    rooms: list[Room] = field(default_factory=list)
    # Additional requirements that apply across the whole building rather
    # than to one room (e.g. "2 Fotograf somewhere in this building").
    capacities: dict[Role, RoleCapacity] = field(default_factory=dict)


@dataclass
class Competition:
    buildings: dict[str, Building]
    helpers: list[Helper]


@dataclass
class Assignment:
    helper_id: int
    helper_name: str
    building: str
    room: str
    role: Role


@dataclass
class SolveResult:
    assignments: list[Assignment]
    status: str
    objective_value: float
    # (helper_a_id, helper_b_id) pairs whose friend request was not satisfied.
    unsatisfied_friend_pairs: list[tuple[int, int]] = field(default_factory=list)
    # (helper_a_id, helper_b_id) pairs whose friend request ended up satisfied
    # (both assigned to the same room).
    satisfied_friend_pairs: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class StructuralAssignment:
    role: StructuralRole
    building: str
    # Exactly one of helper_id/helper_name is meaningful: helper_id for a
    # registered helper, helper_name for someone typed in by hand (manual
    # roles are often filled by people who never registered as a helper).
    helper_id: Optional[int] = None
    helper_name: Optional[str] = None
    room: Optional[str] = None  # only meaningful for VedouciMistnosti / PravaRuka


@dataclass
class OverlayAssignment:
    role: OverlayRole
    helper_id: Optional[int] = None
    helper_name: Optional[str] = None
    # Only meaningful for room-scoped overlay roles (a helper can only be
    # duplicated into an overlay slot in the room they're already solved
    # into); None for building/global-scoped overlay roles like Registrace.
    building: Optional[str] = None
    room: Optional[str] = None


@dataclass
class ManualRoles:
    structural: list[StructuralAssignment] = field(default_factory=list)
    overlay: list[OverlayAssignment] = field(default_factory=list)


def manual_assignment_name(helper_id: Optional[int], helper_name: Optional[str], helper_name_by_id: dict[int, str]) -> str:
    """Resolve a manual-role entry's display name: the registered helper's
    name if ``helper_id`` is set, otherwise the hand-typed ``helper_name``."""
    if helper_id is not None:
        return helper_name_by_id.get(helper_id, f"#{helper_id}")
    return helper_name or ""
