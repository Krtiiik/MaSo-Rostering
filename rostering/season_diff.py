"""What importing a Season would change in a stored one: the list of differences
shown before the organizer picks Replace, Keep both or Skip.

Pure functions of two saved states (plus the two sets of Version slugs); no I/O.
The comparison runs from the stored Season ("local") to the incoming one, so
``added`` is what Replace would bring, ``removed`` what it would take away and
``changed`` what it would overwrite.

The result is a list of categories, in a fixed order, each
``{"key", "added", "removed", "changed"}``: ``added`` and ``removed`` are display
names, ``changed`` is ``{"label", "fields"}`` entries naming the persisted
(English) fields that differ. A category with nothing in it is left out, so an
empty list means the Seasons are identical. The screens translate ``key`` and the
field names.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

# Fields of a Helper / Organizer record that have a category of their own.
_FLAG_FIELDS = ("cant_attend",)


def diff_seasons(
    local: dict[str, Any],
    incoming: dict[str, Any],
    local_versions: Iterable[str],
    incoming_versions: Iterable[str],
) -> list[dict[str, Any]]:
    """The differences between a stored Season's state and an incoming one."""
    categories = [
        _records("helpers", local, incoming, exclude=_FLAG_FIELDS),
        _records("organizers", local, incoming, exclude=_FLAG_FIELDS),
        _assignments(local, incoming),
        _locks(local, incoming),
        _flags(local, incoming),
        _records("tags", local, incoming),
        _records("forced_groups", local, incoming),
        _layout(local, incoming),
        _whole("manual_roles", "manual_roles", local, incoming),
        _merges(local, incoming),
        _whole("solver_config", "solver_config", local, incoming),
        _versions(local_versions, incoming_versions),
    ]
    return [c for c in categories if c["added"] or c["removed"] or c["changed"]]


def _category(key: str, added=(), removed=(), changed=()) -> dict[str, Any]:
    return {"key": key, "added": list(added), "removed": list(removed), "changed": list(changed)}


def _by_id(records: Iterable[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    return {r["id"]: r for r in records if isinstance(r, dict) and "id" in r}


def _name(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("helper_name") or record.get("id"))


def _differing_fields(a: dict[str, Any], b: dict[str, Any], exclude: Iterable[str] = ()) -> list[str]:
    skipped = {"id", *exclude}
    return sorted(k for k in (a.keys() | b.keys()) - skipped if a.get(k) != b.get(k))


def _compare(
    key: str,
    before: dict[Any, dict[str, Any]],
    after: dict[Any, dict[str, Any]],
    fields: Callable[[dict[str, Any], dict[str, Any]], list[str]],
    label: Callable[[dict[str, Any]], str] = _name,
) -> dict[str, Any]:
    added = [label(after[i]) for i in after.keys() - before.keys()]
    removed = [label(before[i]) for i in before.keys() - after.keys()]
    changed = []
    for i in before.keys() & after.keys():
        differing = fields(before[i], after[i])
        if differing:
            changed.append({"label": label(after[i]), "fields": differing})
    return _category(key, sorted(added), sorted(removed), sorted(changed, key=lambda c: c["label"]))


def _records(
    key: str, local: dict[str, Any], incoming: dict[str, Any], exclude: Iterable[str] = ()
) -> dict[str, Any]:
    return _compare(
        key,
        _by_id(local.get(key, [])),
        _by_id(incoming.get(key, [])),
        lambda a, b: _differing_fields(a, b, exclude),
    )


def _assignments_by_helper(state: dict[str, Any]) -> dict[Any, dict[str, Any]]:
    return {a["helper_id"]: {**a, "id": a["helper_id"]} for a in state.get("assignments", []) if "helper_id" in a}


def _assignments(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    return _compare(
        "assignments",
        _assignments_by_helper(local),
        _assignments_by_helper(incoming),
        lambda a, b: _differing_fields(a, b, exclude=("helper_name", "locked")),
    )


def _locks(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    before, after = _assignments_by_helper(local), _assignments_by_helper(incoming)
    changed = [
        {"label": _name(after[i]), "fields": ["locked"]}
        for i in before.keys() & after.keys()
        if bool(before[i].get("locked")) != bool(after[i].get("locked"))
    ]
    return _category("locks", changed=sorted(changed, key=lambda c: c["label"]))


def _flags(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    changed = []
    for key in ("helpers", "organizers"):
        before, after = _by_id(local.get(key, [])), _by_id(incoming.get(key, []))
        for i in before.keys() & after.keys():
            fields = [f for f in _FLAG_FIELDS if bool(before[i].get(f)) != bool(after[i].get(f))]
            if fields:
                changed.append({"label": _name(after[i]), "fields": fields})
    return _category("flags", changed=sorted(changed, key=lambda c: c["label"]))


def _layout_entries(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every Building ("B") and Room ("B / R1") of a state's layout, with the
    fields to compare (a Building's own, without its Rooms)."""
    entries: dict[str, dict[str, Any]] = {}
    for building in state.get("config", []):
        name = building.get("name")
        entries[str(name)] = {k: v for k, v in building.items() if k not in ("name", "rooms")}
        for room in building.get("rooms", []):
            entries[f"{name} / {room.get('name')}"] = {k: v for k, v in room.items() if k != "name"}
    return entries


def _layout(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    before, after = _layout_entries(local), _layout_entries(incoming)
    return _compare(
        "layout",
        {k: {"id": k, **v} for k, v in before.items()},
        {k: {"id": k, **v} for k, v in after.items()},
        lambda a, b: _differing_fields(a, b),
        label=lambda record: str(record["id"]),
    )


def _whole(key: str, field: str, local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """A part of the state reported as one piece: it differs or it does not."""
    if local.get(field) == incoming.get(field):
        return _category(key)
    return _category(key, changed=[{"label": field, "fields": []}])


def _merges(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    changed = [
        {"label": field, "fields": []}
        for field in ("cell_merges", "row_merges")
        if local.get(field) != incoming.get(field)
    ]
    return _category("merges", changed=changed)


def _versions(local: Iterable[str], incoming: Iterable[str]) -> dict[str, Any]:
    before, after = set(local), set(incoming)
    return _category("versions", added=sorted(after - before), removed=sorted(before - after))
