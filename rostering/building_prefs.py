"""Matching a Helper's Building preference to the Season's configured Buildings.

The survey names a Building one way ("Malá Strana", "Impakt + Troja"), the
Season's layout another ("Mala Strana", "Impakt" and "Troja" as two Buildings), and
the solver, the roster grid and the person sheet only recognise a preference that
names a configured Building. Pure functions of the Season's state: a stored
preference is rewritten to the configured names it denotes (:func:`reconcile`), and
one that denotes none is listed (:func:`unresolved`) for the user to match by hand;
that decision is kept in ``state["building_matches"]`` (survey name -> configured
names), so a re-upload or a later layout change reuses it."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from rostering.domain import normalize_name
from rostering.ingest.mapping import building_keys

# A name shorter than this is too likely to sit inside an unrelated one by chance.
_MIN_SUBSTRING = 3


def match_buildings(preference: str, names: Iterable[str]) -> list[str]:
    """The configured Buildings ``names`` that the survey's ``preference`` denotes,
    in the order given. The first rule that matches anything decides: the same name
    ignoring case, diacritics and spacing; a shared alias (``building_keys``, so
    "Křižíkova" is "Karlín" and "Troja" is part of "Impakt + Troja"); one name
    inside the other. Empty when none does."""
    names = list(names)
    norm = normalize_name(preference)
    if not norm:
        return []
    exact = [n for n in names if normalize_name(n) == norm]
    if exact:
        return exact
    wanted = building_keys(preference)
    aliased = [n for n in names if not building_keys(n).isdisjoint(wanted)]
    if aliased:
        return aliased
    return [
        n
        for n in names
        if min(len(norm), len(normalize_name(n))) >= _MIN_SUBSTRING
        and (normalize_name(n) in norm or norm in normalize_name(n))
    ]


def resolve_preferences(
    preferences: Iterable[str], names: list[str], decisions: Optional[dict[str, list[str]]] = None
) -> list[str]:
    """``preferences`` rewritten to configured Building names, sorted. A name that is
    already configured stays; otherwise the user's decision for it (if it still
    names configured Buildings), else the automatic match; one that matches nothing
    stays as it is. With no Buildings configured there is nothing to match against,
    so the set is returned untouched."""
    if not names:
        return sorted(set(preferences))
    decisions = decisions or {}
    resolved: set[str] = set()
    for preference in preferences:
        if preference in names:
            resolved.add(preference)
            continue
        decided = [n for n in decisions.get(preference, []) if n in names]
        resolved.update(decided or match_buildings(preference, names) or [preference])
    return sorted(resolved)


def reconcile(state: dict[str, Any]) -> bool:
    """Rewrite every Helper's Building preference to the configured names it
    denotes (see :func:`resolve_preferences`). Idempotent; True when a record
    changed."""
    names = [b["name"] for b in state.get("config") or []]
    decisions = state.get("building_matches") or {}
    changed = False
    for record in state.get("helpers") or []:
        current = record.get("building_preferences") or []
        resolved = resolve_preferences(current, names, decisions)
        if resolved != sorted(current):
            record["building_preferences"] = resolved
            changed = True
    return changed


def unresolved(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The survey's Building names that denote no configured Building, each as
    ``{"name", "helpers"}`` (the names of the Helpers who gave it), most-asked first.
    Empty while no Building is configured: there is nothing to match against."""
    names = {b["name"] for b in state.get("config") or []}
    if not names:
        return []
    asked: dict[str, list[str]] = {}
    for record in state.get("helpers") or []:
        for preference in record.get("building_preferences") or []:
            if preference not in names:
                asked.setdefault(preference, []).append(record["name"])
    return [
        {"name": name, "helpers": helpers}
        for name, helpers in sorted(asked.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
