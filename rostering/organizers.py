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

import difflib
from typing import Any, Iterable, Optional

from rostering.domain import StructuralRole, normalize_name

# What a slot's address must look like. "building": a Building and no Room;
# "room": a Building and a Room of it; "either": a Building, with or without a
# Room (Pravá ruka is the Vedoucí budovy's deputy for one Building or Room).
SLOT_SCOPES: dict[StructuralRole, str] = {
    StructuralRole.VedouciBudovy: "building",
    StructuralRole.PravaRuka: "either",
    StructuralRole.VedouciMistnosti: "room",
    StructuralRole.TechnickaPodpora: "building",
}

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


_SIMILAR_CUTOFF = 0.7


def _tokens(name: str) -> list[str]:
    return [token for token in (normalize_name(t) for t in name.split()) if token]


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def name_similarity(name: str, other: str) -> float:
    """How alike two person names are, 0..1 (1 = the same ignoring case,
    diacritics, spacing and word order). Free text from a hand-drawn sheet is
    often a first name or surname only, a nickname ("Terka" for "Tereza") or
    misspelt, so besides the whole name it compares word by word: every word of
    the shorter name must resemble a different word of the other, and a single
    word is judged against the best-fitting word of the longer name."""
    mine, theirs = _tokens(name), _tokens(other)
    if not mine or not theirs:
        return 0.0
    if sorted(mine) == sorted(theirs):
        return 1.0
    whole = _ratio("".join(sorted(mine)), "".join(sorted(theirs)))
    short, long = (mine, theirs) if len(mine) <= len(theirs) else (theirs, mine)
    free = list(long)
    scores = []
    for word in short:
        best = max(free, key=lambda w: _ratio(word, w))
        scores.append(_ratio(word, best))
        free.remove(best)
    return max(whole, sum(scores) / len(scores))


def similar_names(
    name: str, candidates: Iterable[tuple[int, str]], limit: int = 3, cutoff: float = _SIMILAR_CUTOFF
) -> list[int]:
    """The ids of the ``(id, name)`` candidates whose name resembles ``name``
    (:func:`name_similarity` at least ``cutoff``), the most alike first, at most
    ``limit`` of them."""
    scored = [(name_similarity(name, other), other, ident) for ident, other in candidates]
    scored = [item for item in scored if item[0] >= cutoff]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [ident for _score, _other, ident in scored[:limit]]


def placement_of(entries: Iterable[dict[str, Any]], organizer_id: int) -> tuple[Optional[str], Optional[str]]:
    """The placement the slot entries give an Organizer: the Building and Room
    of the one they hold (every entry they hold shares it, see the mutation
    layer), ``(None, None)`` while they hold none."""
    held = [e for e in entries if e.get("organizer_id") == organizer_id]
    if not held:
        return None, None
    last = held[-1]
    return last["building"], last.get("room") or None
