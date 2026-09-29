"""Who is counted, and where, for the per-Building T-shirt totals (and any
other per-Building list built from the roster).

Built against today's model: a person is placed either by a solved
Assignment (a Helper, in their solved Building) or by holding an Organizer
role, which names a Building (see CONTEXT.md "Organizer role"). The rules:

- Every solved Helper counts in their solved Building.
- Whoever holds an Organizer role counts in the Building the role entry
  names — a registered Helper keeps their T-shirt size, a hand-typed name is
  Unknown. An entry with no Building places nobody.
- A person counts **once**, whatever mix of Additional roles, Organizer roles
  and solved Role they hold; their solved Building wins over an Organizer
  role's. Additional roles never add anyone: they only duplicate a Helper who
  is already solved.

Can't attend and the Organizer entity aren't implemented yet; when they land,
the same rules apply to them here and nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass

from rostering.domain import (
    TSHIRT_SIZES,
    UNKNOWN_TSHIRT_SIZE,
    Competition,
    ManualRoles,
    SolveResult,
    manual_assignment_name,
    normalize_name,
)


@dataclass(frozen=True)
class CountedPerson:
    name: str
    building: str
    tshirt_size: str


def counted_people(comp: Competition, result: SolveResult, manual: ManualRoles) -> list[CountedPerson]:
    """Every person to count, each exactly once, in the Building they are
    placed in. Buildings are not filtered here: callers keep only the
    Buildings they show."""
    helper_by_id = {h.id: h for h in comp.helpers}
    name_by_id = {h.id: h.name for h in comp.helpers}

    def size_of(helper_id: int) -> str:
        helper = helper_by_id.get(helper_id)
        # Anything outside the accepted set counts as Unknown, so nobody is
        # silently dropped from the totals.
        if helper is not None and helper.tshirt_size in TSHIRT_SIZES:
            return helper.tshirt_size
        return UNKNOWN_TSHIRT_SIZE

    # Person key -> person. A registered Helper is keyed by id, a hand-typed
    # name by its normalized text (the only identity such a person has).
    people: dict[tuple, CountedPerson] = {}

    for a in result.assignments:
        people.setdefault(
            ("id", a.helper_id),
            CountedPerson(name=a.helper_name, building=a.building, tshirt_size=size_of(a.helper_id)),
        )

    for entry in manual.structural:
        if not entry.building:
            continue
        if entry.helper_id is not None:
            key = ("id", entry.helper_id)
            size = size_of(entry.helper_id)
        else:
            typed_name = (entry.helper_name or "").strip()
            if not typed_name:
                continue
            key = ("name", normalize_name(typed_name))
            size = UNKNOWN_TSHIRT_SIZE
        name = manual_assignment_name(entry.helper_id, entry.helper_name, name_by_id)
        people.setdefault(key, CountedPerson(name=name, building=entry.building, tshirt_size=size))

    return list(people.values())
