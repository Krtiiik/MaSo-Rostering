"""Recognizing the same individual across Seasons (see ``CONTEXT.md``: Person,
Returning helper).

There is no Person registry. Every Helper record in a stored Season carries a
never-reused ``person_id``; two records sharing one are the same Person. A
Person's e-mails and normalized names are therefore *derived*: the union over
its records in every stored Season (including the open one), so removing a
Season, or emptying it with "Start over", forgets exactly what only that state
knew.

Matching rules implemented here:

- **Confident match**: an identical normalized e-mail (trimmed, lower-cased)
  links a row to a Person automatically, whatever the name. It is matched
  against *every* e-mail accumulated for a Person in any stored Season, and
  when several Persons have recorded that e-mail the one from the most recent
  Season wins.
- **Uncertain match**: an identical normalized name with no e-mail match is
  only *proposed* (``uncertain_candidates``); nothing is linked until the user
  confirms it, and a rejected pairing is never proposed again.
- Anything else is a new Person. Phone numbers are never a key, and there is no
  fuzzy or nickname matching.

Everything here works on plain data (no I/O), so it is shared by whatever
loads the stored Seasons and whatever loads an export against them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from rostering.domain import normalize_email, normalize_name
from rostering.persistence.season_label import label_sort_key


def new_person_id() -> str:
    """A fresh, never-reused Person id (random, like a Season id — so an id
    freed by deleting a Season can never come back for someone else)."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class PersonRecord:
    """One Helper (or Organizer) record of one stored Season, reduced to what
    recognition needs. ``helper_id`` is the record's id within its Season and
    ``kind``: a Helper and an Organizer of one Season may share an id."""

    person_id: str
    season_id: str
    season_label: str
    helper_id: int
    name: str
    email: Optional[str]  # normalized
    phone: Optional[str] = None  # as typed; a display hint, never a key
    # Person ids the user said this record is *not* (remembered so the pairing
    # is never proposed again), and whether the user picked this record's
    # Person themselves (Link on the review list, or a manual link), which
    # settles the record for good.
    rejected: frozenset[str] = frozenset()
    link_confirmed: bool = False
    kind: str = "helper"  # "helper" or "organizer"

    @property
    def name_key(self) -> str:
        return normalize_name(self.name)

    @property
    def recency(self) -> tuple[tuple[int, int], int]:
        """Orders appearances in time: the Season first, then the Helper id
        within it."""
        return label_sort_key(self.season_label), self.helper_id


def ensure_person_ids(state: dict[str, Any]) -> bool:
    """Give every Helper record of a saved state that lacks a ``person_id`` a
    fresh one (states saved before Persons existed have none). Returns whether
    anything changed, so the caller can persist it and the ids stay stable."""
    changed = False
    for record in (*state.get("helpers", []), *state.get("organizers", [])):
        if not record.get("person_id"):
            record["person_id"] = new_person_id()
            changed = True
    return changed


def records_from_state(season: dict[str, str], state: dict[str, Any]) -> list[PersonRecord]:
    """The recognition records of one stored Season's state (``season`` is its
    ``{"id", "label"}``): its Helpers and its Organizers, both Persons alike. A
    record with no ``person_id`` yet is skipped: it has no identity to be
    matched to."""
    records = []
    for kind, key in (("helper", "helpers"), ("organizer", "organizers")):
        for record in state.get(key, []):
            if not record.get("person_id"):
                continue
            records.append(
                PersonRecord(
                    person_id=record["person_id"],
                    season_id=season["id"],
                    season_label=season["label"],
                    helper_id=int(record["id"]),
                    name=record.get("name", ""),
                    email=normalize_email(record.get("email")),
                    phone=(record.get("phone") or "").strip() or None,
                    rejected=frozenset(record.get("rejected_person_ids") or ()),
                    link_confirmed=bool(record.get("link_confirmed")),
                    kind=kind,
                )
            )
    return records


def link_persons(emails: Iterable[Optional[str]], known: Iterable[PersonRecord]) -> list[str]:
    """The ``person_id`` for each incoming row, given its normalized e-mail (in
    order), against the records of every stored Season.

    A row whose e-mail was recorded for a Person links to that Person; if
    several Persons recorded it, the most recent appearance wins. A row with no
    match (or no e-mail) gets a fresh Person, except that rows of this same
    batch sharing an e-mail share that fresh Person too."""
    best: dict[str, PersonRecord] = {}
    for record in known:
        if record.email is None:
            continue
        current = best.get(record.email)
        if current is None or record.recency > current.recency:
            best[record.email] = record

    fresh_by_email: dict[str, str] = {}
    person_ids = []
    for email in emails:
        if email is not None and email in best:
            person_ids.append(best[email].person_id)
        elif email is not None:
            person_ids.append(fresh_by_email.setdefault(email, new_person_id()))
        else:
            person_ids.append(new_person_id())
    return person_ids


@dataclass(frozen=True)
class Candidate:
    """One proposal for a Helper: a Person whose record with the same
    normalized name is ``record`` (the most recent such record)."""

    person_id: str
    record: PersonRecord


def uncertain_candidates(
    records: Iterable[PersonRecord], season_id: str, kind: str = "helper"
) -> dict[int, list[Candidate]]:
    """The uncertain matches of one stored Season's Helpers (``season_id``; its
    Organizers with ``kind="organizer"``): record id -> the Persons proposed for
    them, most recent appearance first; records with nothing to review are
    absent. A Helper is proposed a Person known only as an Organizer, and the
    other way round (that is how a returning Organizer is offered a link, never
    promoted); within one Season the two kinds are never proposed to each other.

    A Helper is proposed a Person when a record of that Person has the same
    normalized name, unless the Helper is already *settled*: linked (it shares
    its Person with another record, e.g. by e-mail) or linked by the user's own
    choice — "pick one or none". A pairing the user rejected, from either side,
    is never proposed. Two unsettled Helpers of one Season that match each
    other are listed once, on the later one."""
    records = list(records)
    by_person: dict[str, list[PersonRecord]] = {}
    for record in records:
        by_person.setdefault(record.person_id, []).append(record)
    rejected_pairs = {frozenset((r.person_id, other)) for r in records for other in r.rejected}

    proposals: dict[int, list[Candidate]] = {}
    for helper in records:
        if helper.season_id != season_id or helper.kind != kind or helper.link_confirmed or not helper.name_key:
            continue
        if len(by_person[helper.person_id]) > 1:
            continue
        found: list[Candidate] = []
        for person_id, group in by_person.items():
            if person_id == helper.person_id or frozenset((helper.person_id, person_id)) in rejected_pairs:
                continue
            same_name = [
                r for r in group if r.name_key == helper.name_key and (r.season_id != season_id or r.kind == kind)
            ]
            if not same_name:
                continue
            best = max(same_name, key=lambda r: r.recency)
            pending_in_season = (
                best.season_id == season_id and len(group) == 1 and not best.link_confirmed
            )
            if pending_in_season and best.helper_id > helper.helper_id:
                continue  # listed once, on the later of the two
            found.append(Candidate(person_id, best))
        if found:
            proposals[helper.helper_id] = sorted(found, key=lambda c: c.record.recency, reverse=True)
    return proposals


@dataclass
class Person:
    """A Person as derived from the records that carry their ``person_id``."""

    person_id: str
    name: str  # as spelled in the most recent appearance
    emails: list[str]  # every normalized e-mail seen for them, sorted
    names: list[str]  # every normalized name seen for them, sorted
    seasons: list[str]  # labels of the Seasons that record them, most recent first


def build_persons(records: Iterable[PersonRecord]) -> list[Person]:
    """Group records into Persons: the union of e-mails and normalized names
    over all their records."""
    by_person: dict[str, list[PersonRecord]] = {}
    for record in records:
        by_person.setdefault(record.person_id, []).append(record)
    persons = []
    for person_id, group in by_person.items():
        latest = max(group, key=lambda r: r.recency)
        persons.append(
            Person(
                person_id=person_id,
                name=latest.name,
                emails=sorted({r.email for r in group if r.email}),
                names=sorted({r.name_key for r in group if r.name_key}),
                seasons=sorted({r.season_label for r in group}, key=label_sort_key, reverse=True),
            )
        )
    return sorted(persons, key=lambda p: (p.names[0] if p.names else "", p.person_id))
