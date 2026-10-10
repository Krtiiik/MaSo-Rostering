"""Tags (see CONTEXT.md "Tag"): pure functions of a Tag tree and of the Tags
assigned to a Helper directly.

A Tag has at most one parent it implies, so the Tags form a forest. A Helper's
*effective* Tags are the ones assigned to them directly plus every ancestor of
those, computed here on demand and never stored on the Helper — editing the tree
therefore updates everyone at once. Nothing in this module touches state or
storage: callers hand it the Tag definitions and the direct assignments.

Tag constraints (see CONTEXT.md "Tag constraint") live here too, as one shared
pure function of the Tag tree and a Helper's direct Tags: the solver, the live
Broken-rule checker and the edit-time validation all judge through
``restrictions`` / ``blocking`` / ``allowed_values``, so they cannot drift.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional, Sequence

from rostering.domain import Role
from rostering.placement_rules import BE, BUILDING, ROLE, ROOM, Rule

# Distinct, readable-on-white defaults handed to new Tags in turn.
PALETTE: tuple[str, ...] = (
    "#3366cc",
    "#dc3912",
    "#109618",
    "#ff9900",
    "#990099",
    "#0099c6",
    "#dd4477",
    "#66aa00",
    "#b82e2e",
    "#316395",
)
_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Tag:
    id: int
    name: str
    colour: str
    note: str = ""
    # The one Tag this Tag implies, or None for a root.
    parent_id: Optional[int] = None
    # Tag constraints: the same rules a Forced friends group states. ``be`` rules
    # ("must / must not be in Building or Room ...", "must / must not have role
    # ...") apply to each carrier on their own; ``share`` rules bind all the
    # carriers together (see ``forced_friends.tag_groups``). Empty states nothing.
    rules: tuple[Rule, ...] = ()


# Tag constraints before they were rules: (field, axis, must).
_LEGACY_FIELDS = (
    ("building_allow", BUILDING, True),
    ("building_deny", BUILDING, False),
    ("role_allow", ROLE, True),
    ("role_deny", ROLE, False),
)


def legacy_rules(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A Tag saved with the four allow/deny lists carried the same constraints
    as ``be`` rules: an allow-list is "must be in / have", a deny-list "must not"."""
    found: list[dict[str, Any]] = []
    for field, axis, must in _LEGACY_FIELDS:
        entries = [str(e).strip() for e in record.get(field) or [] if str(e or "").strip()]
        if axis == ROLE:
            entries = [e for e in entries if e in Role.__members__]
        if entries:
            found.append({"kind": BE, "must": must, "axis": axis, "values": entries})
    return found


def record_rules(record: Mapping[str, Any]) -> tuple[Rule, ...]:
    """The rules of a saved Tag record, whichever shape it was saved in."""
    raw = record["rules"] if "rules" in record else legacy_rules(record)
    return tuple(Rule.from_dict(r) for r in raw or [])


def migrate_state(state: dict[str, Any]) -> bool:
    """Rewrite the Tags of a saved ``state`` that predate rules (the four
    allow/deny lists) into ``rules``, in place. Returns whether anything changed."""
    changed = False
    for record in state.get("tags") or []:
        if "rules" not in record:
            record["rules"] = legacy_rules(record)
            for field, _axis, _must in _LEGACY_FIELDS:
                record.pop(field, None)
            changed = True
    return changed


def tag_from_dict(data: dict) -> Tag:
    return Tag(
        id=int(data["id"]),
        name=data["name"],
        colour=data.get("colour") or PALETTE[0],
        note=data.get("note") or "",
        parent_id=data.get("parent_id"),
        rules=record_rules(data),
    )


def is_hex_colour(value: str) -> bool:
    return _HEX_COLOUR.match(value or "") is not None


def name_key(name: str) -> str:
    """The form in which Tag names are compared for uniqueness."""
    return (name or "").strip().casefold()


def sort_key(name: str) -> tuple:
    """Natural ordering for Tag names: a run of digits compares as a number, so
    "2. M" comes before "11. M" (plain text order would put "11" first). Case
    is ignored; equal-looking names fall back to the plain comparison key."""
    key = name_key(name)
    # re.split with a group alternates text, number, text, ... so the tuples
    # always compare str with str and int with int.
    parts = tuple(int(p) if i % 2 else p for i, p in enumerate(re.split(r"(\d+)", key)))
    return parts, key


def ancestors(tags: Iterable[Tag], tag_id: int) -> list[int]:
    """The Tags ``tag_id`` implies, nearest first (its parent, then the
    parent's parent, ...). Empty for a root. A malformed loop is cut rather
    than followed forever."""
    parent_of = {t.id: t.parent_id for t in tags}
    chain: list[int] = []
    current = parent_of.get(tag_id)
    while current is not None and current in parent_of and current not in chain and current != tag_id:
        chain.append(current)
        current = parent_of[current]
    return chain


def descendants(tags: Iterable[Tag], tag_id: int) -> list[int]:
    """Every Tag that implies ``tag_id``, directly or through others."""
    tags = list(tags)
    found: list[int] = []
    frontier = [tag_id]
    while frontier:
        parent = frontier.pop()
        for child in tags:
            if child.parent_id == parent and child.id not in found and child.id != tag_id:
                found.append(child.id)
                frontier.append(child.id)
    return found


def can_be_parent(tags: Iterable[Tag], tag_id: int, parent_id: Optional[int]) -> bool:
    """Whether ``parent_id`` may become the parent of ``tag_id``: never the Tag
    itself or one of its descendants, which would make it its own ancestor."""
    tags = list(tags)
    return parent_id is None or (parent_id != tag_id and parent_id not in descendants(tags, tag_id))


def effective_tag_ids(tags: Iterable[Tag], direct: Iterable[int]) -> list[int]:
    """The direct Tags followed by every Tag they imply, each once (the direct
    ones in the order given, the implied ones nearest ancestor first)."""
    tags = list(tags)
    known = {t.id for t in tags}
    result = [t for t in dict.fromkeys(direct) if t in known]
    for tag_id in list(result):
        for ancestor in ancestors(tags, tag_id):
            if ancestor not in result:
                result.append(ancestor)
    return result


def implied_tag_ids(tags: Iterable[Tag], direct: Iterable[int]) -> list[int]:
    """The effective Tags that are not direct ones."""
    tags = list(tags)
    direct_ids = [t for t in dict.fromkeys(direct) if t in {tag.id for tag in tags}]
    return [t for t in effective_tag_ids(tags, direct_ids) if t not in direct_ids]


def via_tag_id(tags: Iterable[Tag], direct: Iterable[int], tag_id: int) -> Optional[int]:
    """Which of the direct Tags implies ``tag_id`` (the first one, in the order
    given, whose ancestors include it), or None when ``tag_id`` is itself direct
    or not carried at all."""
    tags = list(tags)
    direct = list(direct)
    if tag_id in direct:
        return None
    return next((d for d in direct if tag_id in ancestors(tags, d)), None)


ALL_OF = "all"
ANY_OF = "any"


def matches_filter(tags: Iterable[Tag], direct: Iterable[int], wanted: Iterable[int], mode: str = ALL_OF) -> bool:
    """Whether a Helper carrying ``direct`` passes a Tag filter (the roster
    grid's): inherited Tags count, so a Helper with "8.M" matches "GCHD". With
    ``mode`` all-of every wanted Tag must be carried, with any-of at least one.
    An empty filter matches everyone, and a wanted Tag that no longer exists is
    ignored rather than making the filter unsatisfiable."""
    if mode not in (ALL_OF, ANY_OF):
        raise ValueError(f"Unknown Tag filter mode: {mode!r}")
    tags = list(tags)
    known = {t.id for t in tags}
    wanted_ids = [t for t in dict.fromkeys(wanted) if t in known]
    if not wanted_ids:
        return True
    carried = set(effective_tag_ids(tags, direct))
    return all(t in carried for t in wanted_ids) if mode == ALL_OF else any(t in carried for t in wanted_ids)


def tree_order(tags: Iterable[Tag]) -> list[tuple[Tag, int]]:
    """The Tags depth-first as ``(tag, depth)``: roots first, every Tag right
    before the Tags that imply it, siblings in natural order (see ``sort_key``)."""
    tags = list(tags)
    ids = {t.id for t in tags}
    by_parent: dict[Optional[int], list[Tag]] = {}
    for tag in tags:
        # A Tag whose parent is missing is shown as a root rather than lost.
        by_parent.setdefault(tag.parent_id if tag.parent_id in ids else None, []).append(tag)
    for siblings in by_parent.values():
        siblings.sort(key=lambda t: sort_key(t.name))
    ordered: list[tuple[Tag, int]] = []
    seen: set[int] = set()

    def walk(parent: Optional[int], depth: int) -> None:
        for tag in by_parent.get(parent, []):
            if tag.id in seen:
                continue
            seen.add(tag.id)
            ordered.append((tag, depth))
            walk(tag.id, depth + 1)

    walk(None, 0)
    return ordered


# -- Tag constraints -------------------------------------------------------------

AXES = (BUILDING, ROOM, ROLE)


@dataclass(frozen=True)
class Restriction:
    """One applicable ``be`` rule of one Tag, over its live values: the
    universe's own spellings of the entries that name something in it, so an
    entry naming nothing (a Building the Season no longer has) is left out --
    inert. A "must" rule lets the Helper go only to ``values`` (``kind``
    ``"allow"``), a "must not" rule never to them (``"deny"``)."""

    tag: Tag
    rule: Rule

    @property
    def kind(self) -> str:
        return "allow" if self.rule.must else "deny"

    @property
    def values(self) -> tuple:
        return self.rule.values


def same_value(axis: str, entry: Any, value: Any) -> bool:
    """Whether a rule entry names ``value``. Buildings are matched the way
    Building preferences are (the survey and the Season configs spell them
    differently), a Room by its Building so and its name; Roles by name."""
    if axis == BUILDING:
        from rostering.ingest.mapping import building_keys  # deferred: mapping imports domain

        return not building_keys(entry).isdisjoint(building_keys(value))
    if axis == ROOM:
        return same_value(BUILDING, entry[0], value[0]) and entry[1] == value[1]
    return entry == value


def entry_in_universe(axis: str, entry: Any, universe: Iterable[Any]) -> bool:
    return any(same_value(axis, entry, value) for value in universe)


def restrictions(tags: Iterable[Tag], direct: Iterable[int], axis: str, universe: Sequence[Any]) -> list[Restriction]:
    """The live restrictions on ``axis`` from every Tag that applies to a Helper
    carrying ``direct`` (their own Tags plus every ancestor), in effective-Tag
    order. A rule with no entry naming anything in ``universe`` states nothing,
    so a "must" of absent entries never narrows."""
    tags = list(tags)
    by_id = {t.id: t for t in tags}
    found: list[Restriction] = []
    for tag_id in effective_tag_ids(tags, direct):
        tag = by_id[tag_id]
        for rule in tag.rules:
            if rule.kind != BE or rule.axis != axis:
                continue
            live = tuple(v for v in universe if any(same_value(axis, e, v) for e in rule.values))
            if live:
                found.append(Restriction(tag, replace(rule, values=live)))
    return found


def blocking(found: Iterable[Restriction], value: Any) -> list[Restriction]:
    """The restrictions that keep ``value`` out: a "must" not naming it or a
    "must not" naming it. Any single one is enough, which is what makes "must"
    rules intersect and a "must not" always win."""
    return [r for r in found if r.rule.must != (value in r.values)]


def allowed_values(tags: Iterable[Tag], direct: Iterable[int], axis: str, universe: Sequence[Any]) -> list[Any]:
    """A Helper's allowed set on one axis: the intersection of every applicable
    "must" rule (a Tag with none does not narrow) minus every applicable "must
    not", in ``universe`` order."""
    found = restrictions(tags, direct, axis, universe)
    return [v for v in universe if not blocking(found, v)]


def allowed_rooms(
    tags: Iterable[Tag], direct: Iterable[int], buildings: Sequence[str], rooms: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The ``(Building, Room)`` pairs a Helper may be in: the Rooms their Room
    rules allow, inside the Buildings their Building rules allow."""
    tags, direct = list(tags), list(direct)
    in_buildings = set(allowed_values(tags, direct, BUILDING, buildings))
    in_rooms = set(allowed_values(tags, direct, ROOM, rooms))
    return [r for r in rooms if r in in_rooms and r[0] in in_buildings]


def describe_restriction(r: Restriction) -> str:
    """``Štítek 8.M, musí být v budově Karlín`` / ``Štítek GCHD, nesmí mít roli A ani B``."""
    return f"Štítek {r.tag.name}, {r.rule.text()}"


def dead_ends(
    tags: Iterable[Tag],
    direct_by_helper: Mapping[int, Iterable[int]],
    universes: Mapping[str, Sequence[Any]],
) -> set[tuple[int, str]]:
    """The ``(helper id, axis)`` pairs whose allowed set is empty: a Helper with
    nowhere to go. An axis with an empty universe (no Building configured) has
    nothing to strand anyone from and is skipped. The Room axis is judged only
    for a Helper with a Room rule, and not again when no Building is allowed."""
    tags = list(tags)
    stranded: set[tuple[int, str]] = set()
    for helper_id, direct in direct_by_helper.items():
        direct = list(direct)
        if not direct:
            continue
        for axis in AXES:
            universe = universes.get(axis)
            if not universe:
                continue
            if axis == ROOM:
                if (helper_id, BUILDING) in stranded or not restrictions(tags, direct, ROOM, universe):
                    continue
                buildings = universes.get(BUILDING) or sorted({b for b, _room in universe})
                allowed = allowed_rooms(tags, direct, buildings, universe)
            else:
                allowed = allowed_values(tags, direct, axis, universe)
            if not allowed:
                stranded.add((helper_id, axis))
    return stranded


# School-class Tags (see CONTEXT.md "Class promotion"): one or more digits, a dot,
# an optional single space, then letters (Czech ones included) -- "8.M", "8. M",
# "10.M". The spacing is kept when the number moves.
_CLASS_NAME = re.compile(r"(\d+)\.( ?)([^\W\d_]+)")


def is_class_name(name: str) -> bool:
    """Whether ``name`` is a school-class Tag name."""
    return _CLASS_NAME.fullmatch(name or "") is not None


def promoted_class_name(name: str, years: int) -> Optional[str]:
    """A class Tag name with its number ``years`` higher and everything else as
    it was (there is no top year), or None if ``name`` is not a class name."""
    match = _CLASS_NAME.fullmatch(name or "")
    if match is None:
        return None
    number, space, letters = match.groups()
    return f"{int(number) + years}.{space}{letters}"
