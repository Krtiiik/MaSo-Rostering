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

Each person also carries the Room and Role to show for them (the per-Building
helper lists): a Helper's solved Room and Role; whoever holds Organizer roles
in their counted Building is shown by those Organizer role(s) instead (joined
with ", " when several), in their solved Room, or — for someone only an
Organizer — in the first Room an entry names, empty at Building level.

A Helper flagged Can't attend is never counted, however they are still placed
(``without_absent`` drops their Assignment and Manual role entries).

The Organizer entity isn't implemented yet; when it lands, the same rules
apply to it here and nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple

from rostering.domain import (
    TSHIRT_SIZES,
    UNKNOWN_TSHIRT_SIZE,
    Competition,
    ManualRoles,
    SolveResult,
    StructuralAssignment,
    manual_assignment_name,
    normalize_name,
)


@dataclass(frozen=True)
class CountedPerson:
    name: str
    building: str
    tshirt_size: str
    room: str = ""  # empty: placed at Building level only
    role: str = ""  # display text: a solved Role, or the Organizer role(s)


def without_absent(
    comp: Competition, result: SolveResult, manual: ManualRoles
) -> Tuple[Competition, SolveResult, ManualRoles]:
    """The roster as it counts for the export: the Helpers flagged Can't attend
    left out of the Competition, the Assignments and the Manual role entries,
    so an absent person never appears in a sheet or a total."""
    absent = {h.id for h in comp.helpers if h.cant_attend}
    if not absent:
        return comp, result, manual
    return (
        comp.attending(),
        replace(result, assignments=[a for a in result.assignments if a.helper_id not in absent]),
        ManualRoles(
            structural=[e for e in manual.structural if e.helper_id not in absent],
            overlay=[e for e in manual.overlay if e.helper_id not in absent],
        ),
    )


def counted_people(comp: Competition, result: SolveResult, manual: ManualRoles) -> list[CountedPerson]:
    """Every person to count, each exactly once, in the Building they are
    placed in. Buildings are not filtered here: callers keep only the
    Buildings they show."""
    comp, result, manual = without_absent(comp, result, manual)
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
            CountedPerson(
                name=a.helper_name,
                building=a.building,
                tshirt_size=size_of(a.helper_id),
                room=a.room,
                role=a.role.value,
            ),
        )

    # Organizer-role entries per person, in entry order. An entry with no
    # Building places nobody.
    entries_by_person: dict[tuple, list[StructuralAssignment]] = {}
    first_entry_name: dict[tuple, str] = {}
    for entry in manual.structural:
        if not entry.building:
            continue
        if entry.helper_id is not None:
            key = ("id", entry.helper_id)
        else:
            typed_name = (entry.helper_name or "").strip()
            if not typed_name:
                continue
            key = ("name", normalize_name(typed_name))
        entries_by_person.setdefault(key, []).append(entry)
        first_entry_name.setdefault(key, manual_assignment_name(entry.helper_id, entry.helper_name, name_by_id))

    for key, entries in entries_by_person.items():
        person = people.get(key)
        if person is None:
            # Only an Organizer: placed where their first entry says.
            building = entries[0].building
            size = size_of(key[1]) if key[0] == "id" else UNKNOWN_TSHIRT_SIZE
            person = CountedPerson(name=first_entry_name[key], building=building, tshirt_size=size)
        here = [e for e in entries if e.building == person.building]
        if not here:
            continue  # their solved Building wins; these roles are elsewhere
        roles = list(dict.fromkeys(e.role.value for e in here))
        room = person.room or next((e.room for e in here if e.room), "")
        people[key] = replace(person, room=room, role=", ".join(roles))

    return list(people.values())
