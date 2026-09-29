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
- Anything else is a new Person. Phone numbers are never a key, and there is no
  fuzzy or nickname matching; proposing same-name candidates for the user to
  confirm belongs to the review list, not to this module.

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
    """One Helper record of one stored Season, reduced to what recognition
    needs."""

    person_id: str
    season_id: str
    season_label: str
    helper_id: int
    name: str
    email: Optional[str]  # normalized

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
    for helper in state.get("helpers", []):
        if not helper.get("person_id"):
            helper["person_id"] = new_person_id()
            changed = True
    return changed


def records_from_state(season: dict[str, str], state: dict[str, Any]) -> list[PersonRecord]:
    """The recognition records of one stored Season's state (``season`` is its
    ``{"id", "label"}``). A Helper record with no ``person_id`` yet is skipped:
    it has no identity to be matched to."""
    records = []
    for helper in state.get("helpers", []):
        if not helper.get("person_id"):
            continue
        records.append(
            PersonRecord(
                person_id=helper["person_id"],
                season_id=season["id"],
                season_label=season["label"],
                helper_id=int(helper["id"]),
                name=helper.get("name", ""),
                email=normalize_email(helper.get("email")),
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
