"""Core domain model shared by ingestion, the solver, and export.

Terminology follows CLAUDE.md — read that first if a term
here (Role, building preference "set", friend scoring, manual/overlay roles)
is unclear.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # rostering.tags needs nothing from here at runtime
    from rostering.forced_friends import ForcedGroup
    from rostering.tags import Tag


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


def group_adjacent_rooms(room_names: list[str], merged_pairs: list[list[str]]) -> list[list[str]]:
    """Group one building's rooms (in season-config order) into display
    columns for the roster grid and Excel export, given a set of
    currently-merged adjacent-room-name pairs (see CLAUDE.md "Out-of-solver
    roles" — the grid's room-merge UI). Merging is purely presentational:
    two adjacent rooms collapse into one wider column showing the union of
    both rooms' content, but the underlying per-helper room assignment is
    untouched. A pair that no longer names two rooms that are actually
    adjacent (e.g. after a season-config edit) is silently ignored, so
    stale merge state never breaks rendering."""
    merged = {(a, b) for a, b in merged_pairs}
    groups: list[list[str]] = []
    for name in room_names:
        if groups and (groups[-1][-1], name) in merged:
            groups[-1].append(name)
        else:
            groups.append([name])
    return groups


def normalize_name(value: Optional[str]) -> str:
    """Diacritics/whitespace-insensitive normalization used throughout
    ingestion to match Czech free text across seasons."""
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(
        ch for ch in normalized.lower() if not unicodedata.combining(ch)
    ).replace(" ", "").replace("_", "").replace("-", "")


def normalize_email(value: Optional[str]) -> Optional[str]:
    """The comparison form of an e-mail address: trimmed and lower-cased.
    ``None`` for a blank or absent value, so "no e-mail" is never a key that
    two people could share."""
    text = (value or "").strip().lower()
    return text or None


# The T-shirt sizes the survey answer may resolve to, in the order the
# "Trička" sheet lists them. Extend this tuple (nothing else) to accept a new
# size such as "XXXL".
TSHIRT_SIZES: tuple[str, ...] = ("XS", "S", "M", "L", "XL", "XXL")
UNKNOWN_TSHIRT_SIZE = "Unknown"


def parse_tshirt_size(value: Optional[str]) -> Optional[str]:
    """The canonical size in ``TSHIRT_SIZES`` that ``value`` names, ignoring
    case and surrounding whitespace, or None if it names none of them."""
    text = (value or "").strip().upper()
    return text if text in TSHIRT_SIZES else None


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
    # One of TSHIRT_SIZES, or UNKNOWN_TSHIRT_SIZE (the default: hand-added
    # helpers, legacy CSV rows and unparsed survey answers).
    tshirt_size: str = UNKNOWN_TSHIRT_SIZE
    # The survey's e-mail answer, normalized (trimmed, lower-cased; see
    # rostering.persons.normalize_email), or None when blank/absent. The first
    # key for recognizing a Returning helper across Seasons.
    email: Optional[str] = None
    # The survey's phone answer as typed (trimmed), or None. Display-only: a
    # hint shown next to an uncertain Person match, never a key.
    phone: Optional[str] = None
    # Durable identity of the individual across Seasons (never reused). Not
    # known to ingestion: it is assigned when the export is loaded into a
    # Season, by matching against the stored Seasons (rostering.persons).
    person_id: Optional[str] = None
    # Can't attend (see CONTEXT.md): the Helper is unavailable for the Season
    # and is left out of the solver, the grid and the export counts. Set by
    # hand, never by survey data, and reversible.
    cant_attend: bool = False
    # Ids of the Tags assigned to this Helper directly (see rostering.tags);
    # the implied ones are computed from the Tag tree, never stored here.
    tags: list[int] = field(default_factory=list)


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
    # The Season's Tag definitions (with their constraints); the Helpers carry
    # only their direct Tag ids.
    tags: list["Tag"] = field(default_factory=list)
    # The Season's Organizers (see CONTEXT.md "Organizer"). They are not
    # Helpers: the solver never sees them and they use no Role or Role
    # capacity; the export names them in their Organizer role slots.
    organizers: list["Organizer"] = field(default_factory=list)
    # The Season's Forced friends groups (see rostering.forced_friends); their
    # members are Persons, resolved against the Helpers by ``person_id``.
    forced_groups: list["ForcedGroup"] = field(default_factory=list)

    def attending(self) -> "Competition":
        """This Competition without the Helpers flagged Can't attend: the one
        rule for who takes part, applied by the solver, the Broken-rule check
        and the export."""
        if not any(h.cant_attend for h in self.helpers):
            return self
        return Competition(
            buildings=self.buildings,
            helpers=[h for h in self.helpers if not h.cant_attend],
            tags=self.tags,
            organizers=self.organizers,
            forced_groups=self.forced_groups,
        )


@dataclass
class Assignment:
    helper_id: int
    helper_name: str
    building: str
    room: str
    role: Role
    # A Locked Assignment (see CONTEXT.md): a full Solve keeps it. The solver
    # itself ignores this flag; callers pass the locked ones as fixed.
    locked: bool = False


@dataclass(frozen=True)
class RuleInstance:
    """The identity of one hard-rule instance: rule kind plus the entity it
    binds, e.g. ``("room_minimum", ("Karlín", "N4", "Fotograf"))`` or
    ``("equipment", (helper_id,))``. The solver's relaxation reports its
    Broken rules under these identities, and the live checker must emit the
    same ones so the two can be compared."""

    kind: str
    entity: tuple


@dataclass(frozen=True)
class FixTarget:
    """Where the "Go fix" button of a Broken rule leads: ``tab`` is a logical
    name (``"buildings"`` for a minimum, ``"helpers"`` for the Helper list;
    later rule families add their own), the other fields preselect the entity
    on that tab."""

    tab: str
    building: Optional[str] = None
    room: Optional[str] = None
    role: Optional[str] = None
    helper_id: Optional[int] = None
    tag_id: Optional[int] = None
    group_id: Optional[int] = None


@dataclass(frozen=True)
class BrokenRule:
    """One hard rule the roster fails to satisfy (see CONTEXT.md "Broken
    rule"): ``family`` is the rule family's name, ``amount`` the size of the
    violation in people (a minimum's shortfall; 1 for an all-or-nothing rule)
    and ``line`` the human-readable description.

    The rest is filled only by the live checker (the solver's report leaves
    it empty): ``cells`` the grid cells affected, as ``(building, room, role
    name)`` — a role of ``None`` means the whole Room —, ``helper_ids`` the
    Helper chips affected and ``fix`` the "Go fix" target, if any."""

    instance: RuleInstance
    family: str
    amount: int
    line: str
    cells: tuple[tuple[str, str, Optional[str]], ...] = ()
    helper_ids: tuple[int, ...] = ()
    fix: Optional[FixTarget] = None


@dataclass
class SolveResult:
    assignments: list[Assignment]
    status: str
    # The ordinary preference/friend objective only; the penalties for
    # Broken rules are not included.
    objective_value: float
    # (helper_a_id, helper_b_id) pairs whose friend request was not satisfied.
    unsatisfied_friend_pairs: list[tuple[int, int]] = field(default_factory=list)
    # (helper_a_id, helper_b_id) pairs whose friend request ended up satisfied
    # (both assigned to the same room).
    satisfied_friend_pairs: list[tuple[int, int]] = field(default_factory=list)
    # The hard rules the solver had to bend to return a full roster, stricter
    # tiers last. Empty when every rule holds.
    broken_rules: list[BrokenRule] = field(default_factory=list)


@dataclass
class Organizer:
    """A tracked person who is not a Helper (see CONTEXT.md "Organizer").
    ``building``/``room`` are their single placement, derived from the Organizer
    role slot(s) they hold: both unset while they hold none, ``room`` unset for
    a Building-level placement."""

    id: int
    name: str
    person_id: Optional[str] = None
    email: Optional[str] = None  # normalized; optional
    building: Optional[str] = None
    room: Optional[str] = None


@dataclass
class StructuralAssignment:
    role: StructuralRole
    building: str
    # A slot entry saved before Organizers existed holds a Helper (helper_id)
    # or hand-typed text (helper_name) — a *legacy* entry, still displayed and
    # exported until it is replaced. Exactly one of the two is meaningful:
    # helper_id for a registered helper, helper_name for someone typed in by
    # hand.
    helper_id: Optional[int] = None
    helper_name: Optional[str] = None
    room: Optional[str] = None  # only meaningful for VedouciMistnosti / PravaRuka
    # The tracked Organizer holding the slot (see Organizer); set instead of
    # helper_id/helper_name on every entry made since Organizers exist.
    organizer_id: Optional[int] = None


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


def manual_assignment_name(
    helper_id: Optional[int],
    helper_name: Optional[str],
    helper_name_by_id: dict[int, str],
    organizer_id: Optional[int] = None,
    organizer_name_by_id: Optional[dict[int, str]] = None,
) -> str:
    """Resolve a manual-role entry's display name: the tracked Organizer's name
    if ``organizer_id`` is set, else the registered helper's name if
    ``helper_id`` is set, otherwise the hand-typed ``helper_name``."""
    if organizer_id is not None:
        return (organizer_name_by_id or {}).get(organizer_id, f"#{organizer_id}")
    if helper_id is not None:
        return helper_name_by_id.get(helper_id, f"#{helper_id}")
    return helper_name or ""
