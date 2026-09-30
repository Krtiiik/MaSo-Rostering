"""Organizers in the four leadership slots (see ``CONTEXT.md``: Organizer,
Organizer role).

An Organizer is a tracked person, not a Helper, saved per Season as a record
in ``state["organizers"]`` (``id``, ``person_id``, ``name``, optional
``email``, and a single optional placement ``building``/``room``). There is no
separate placement step: an Organizer is placed only by holding a slot
(``state["manual_roles"]["structural"]`` entries carrying their
``organizer_id``), and the placement is derived from those entries, never set
on its own.

This module holds the pure rules — what each slot's scope is, whether a slot
address is well-formed, and what placement the entries imply — so the
mutation layer, the grid and tests share one definition. It does no I/O.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from rostering.domain import StructuralRole

# What a slot's address must look like. "building": a Building and no Room;
# "room": a Building and a Room of it; "either": a Building, with or without a
# Room (Pravá ruka is the Vedoucí budovy's deputy for one Building or Room).
SLOT_SCOPES: dict[StructuralRole, str] = {
    StructuralRole.VedouciBudovy: "building",
    StructuralRole.PravaRuka: "either",
    StructuralRole.VedouciMistnosti: "room",
    StructuralRole.TechnickaPodpora: "building",
}

# Slots that hold one person per cell: a newly assigned Organizer replaces the
# holder. Technická podpora can have several.
SINGLE_HOLDER_ROLES = frozenset(
    {StructuralRole.VedouciBudovy, StructuralRole.PravaRuka, StructuralRole.VedouciMistnosti}
)


def parse_slot_role(role: str) -> StructuralRole:
    """The slot named by its enum name (``"VedouciBudovy"``) or its Czech label;
    ``ValueError`` for anything else — Additional roles included, which stay
    Helper-only."""
    for member in StructuralRole:
        if role in (member.name, member.value):
            return member
    raise ValueError(f"Not an Organizer role slot: {role!r}")


def check_slot(
    role: StructuralRole,
    building: Optional[str],
    room: Optional[str],
    buildings: dict[str, Iterable[str]],
) -> None:
    """Raise ``ValueError`` unless (``building``, ``room``) is a well-formed
    address for ``role``: the slot's scope matches (a Building-scoped slot takes
    no Room, a Room-scoped one needs one) and the Building — and Room — exist in
    ``buildings`` (Building name -> its Room names)."""
    if not building or building not in buildings:
        raise ValueError(f"Neznámá budova: {building!r}")
    scope = SLOT_SCOPES[role]
    if scope == "building" and room:
        raise ValueError(f"{role.value} patří k budově, ne k místnosti.")
    if scope == "room" and not room:
        raise ValueError(f"{role.value} patří k místnosti — uveďte ji.")
    if room and room not in set(buildings[building]):
        raise ValueError(f"Neznámá místnost {room!r} v budově {building}.")


def placement_of(entries: Iterable[dict[str, Any]], organizer_id: int) -> tuple[Optional[str], Optional[str]]:
    """The placement the slot entries give an Organizer: the Building and Room
    of the one they hold (every entry they hold shares it, see the mutation
    layer), ``(None, None)`` while they hold none."""
    held = [e for e in entries if e.get("organizer_id") == organizer_id]
    if not held:
        return None, None
    last = held[-1]
    return last["building"], last.get("room") or None
