"""Test shorthand for Tag rules: the four allow/deny lists a Tag's constraints used
to be (``building_allow=["A"]`` is the rule "must be in building A", ``role_deny``
"must not have role ..."), turned into the ``rules`` the mutation layer takes.

``add_tag`` / ``update_tag`` here wrap the mutations. An ``update_tag`` list
replaces only the rule of that kind (allow or deny) on that axis and leaves the
Tag's other rules alone, which is how the old fields behaved."""
from __future__ import annotations

from typing import Any

from rostering.placement_rules import BE, BUILDING, ROLE, ROOM
from rostering.tags import record_rules
from rostering.webapp import mutations

# keyword -> (axis, must)
SHORTHAND = {
    "building_allow": (BUILDING, True),
    "building_deny": (BUILDING, False),
    "room_allow": (ROOM, True),
    "room_deny": (ROOM, False),
    "role_allow": (ROLE, True),
    "role_deny": (ROLE, False),
}


def rule(axis: str, values, must: bool = True) -> dict[str, Any]:
    return {"kind": BE, "must": must, "axis": axis, "values": list(values)}


def rules_from(**lists) -> list[dict[str, Any]]:
    """``building_allow=["A"], role_deny=["Fotograf"]`` as rule dicts."""
    return [rule(axis, values, must) for key, (axis, must) in SHORTHAND.items() if (values := lists.get(key))]


def _split(kwargs: dict) -> tuple[dict, dict]:
    lists = {k: v for k, v in kwargs.items() if k in SHORTHAND}
    return lists, {k: v for k, v in kwargs.items() if k not in SHORTHAND}


def add_tag(workspace, name, **kwargs) -> dict:
    lists, rest = _split(kwargs)
    return mutations.add_tag(workspace, name, rules=[*rest.pop("rules", []), *rules_from(**lists)], **rest)


def update_tag(workspace, tag_id, **kwargs) -> dict:
    lists, rest = _split(kwargs)
    if lists:
        record = next(t for t in mutations.get_state(workspace)["tags"] if t["id"] == tag_id)
        replaced = {SHORTHAND[k] for k in lists}
        kept = [r.to_dict() for r in record_rules(record) if (r.axis, r.must) not in replaced]
        rest["rules"] = [*kept, *rules_from(**lists)]
    return mutations.update_tag(workspace, tag_id, **rest)


def entries(state, tag_id) -> dict[str, list[dict]]:
    """A Tag's Building and Role rules in the shape of the old four lists:
    ``{"building_allow": [{"name", "in_season"}, ...], ...}``."""
    from rostering import tags as tag_tree

    record = next(t for t in state["tags"] if t["id"] == tag_id)
    universes = mutations._tag_universes(state)
    found = {key: [] for key in SHORTHAND if not key.startswith("room")}
    for r in record_rules(record):
        key = next(k for k, spec in SHORTHAND.items() if spec == (r.axis, r.must))
        if key in found:
            found[key] += [
                {"name": v, "in_season": tag_tree.entry_in_universe(r.axis, v, universes[r.axis])} for v in r.values
            ]
    return found


def domain_rules(**lists):
    """The same shorthand as ``Rule`` objects, for building a domain ``Tag``."""
    from rostering.placement_rules import Rule

    return tuple(Rule.from_dict(d) for d in rules_from(**lists))
