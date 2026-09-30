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
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence

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
    # Tag constraints: names of Buildings / Roles (``Role.name``) the Tag's
    # Helpers may go to only (allow) or may not go to (deny). Room is not an
    # axis. An empty list states nothing.
    building_allow: tuple[str, ...] = ()
    building_deny: tuple[str, ...] = ()
    role_allow: tuple[str, ...] = ()
    role_deny: tuple[str, ...] = ()


def tag_from_dict(data: dict) -> Tag:
    return Tag(
        id=int(data["id"]),
        name=data["name"],
        colour=data.get("colour") or PALETTE[0],
        note=data.get("note") or "",
        parent_id=data.get("parent_id"),
        # Absent from Tags saved before Tag constraints existed.
        building_allow=tuple(data.get("building_allow") or ()),
        building_deny=tuple(data.get("building_deny") or ()),
        role_allow=tuple(data.get("role_allow") or ()),
        role_deny=tuple(data.get("role_deny") or ()),
    )


def is_hex_colour(value: str) -> bool:
    return _HEX_COLOUR.match(value or "") is not None


def name_key(name: str) -> str:
    """The form in which Tag names are compared for uniqueness."""
    return (name or "").strip().casefold()


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
    before the Tags that imply it, siblings alphabetical."""
    tags = list(tags)
    ids = {t.id for t in tags}
    by_parent: dict[Optional[int], list[Tag]] = {}
    for tag in tags:
        # A Tag whose parent is missing is shown as a root rather than lost.
        by_parent.setdefault(tag.parent_id if tag.parent_id in ids else None, []).append(tag)
    for siblings in by_parent.values():
        siblings.sort(key=lambda t: name_key(t.name))
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

BUILDING = "building"
ROLE = "role"
AXES = (BUILDING, ROLE)
# (singular, plural) accusative, as in "povoluje jen budovu" / "zakazuje budovy".
_NOUNS = {BUILDING: ("budovu", "budovy"), ROLE: ("roli", "role")}


@dataclass(frozen=True)
class Restriction:
    """One applicable Tag's live list on one axis. ``kind`` is ``"allow"`` (the
    Helper may go only to ``values``) or ``"deny"`` (never to ``values``);
    ``values`` are the universe's own spellings of the entries that name
    something in it, so an entry naming nothing (a Building the Season no
    longer has) is left out -- inert."""

    tag: Tag
    kind: str
    values: tuple[str, ...]


def same_value(axis: str, entry: str, value: str) -> bool:
    """Whether a constraint entry names ``value``. Buildings are matched the
    way Building preferences are (the survey and the Season configs spell them
    differently); Roles by name."""
    if axis == BUILDING:
        from rostering.ingest.mapping import building_keys  # deferred: mapping imports domain

        return not building_keys(entry).isdisjoint(building_keys(value))
    return entry == value


def entry_in_universe(axis: str, entry: str, universe: Iterable[str]) -> bool:
    return any(same_value(axis, entry, value) for value in universe)


def restrictions(tags: Iterable[Tag], direct: Iterable[int], axis: str, universe: Sequence[str]) -> list[Restriction]:
    """The live restrictions on ``axis`` from every Tag that applies to a Helper
    carrying ``direct`` (their own Tags plus every ancestor), in effective-Tag
    order. A list with no entry naming anything in ``universe`` states nothing,
    so an allow-list of absent entries never narrows."""
    tags = list(tags)
    by_id = {t.id: t for t in tags}
    found: list[Restriction] = []
    for tag_id in effective_tag_ids(tags, direct):
        tag = by_id[tag_id]
        for kind in ("allow", "deny"):
            entries = getattr(tag, f"{axis}_{kind}")
            live = tuple(v for v in universe if any(same_value(axis, e, v) for e in entries))
            if live:
                found.append(Restriction(tag, kind, live))
    return found


def blocking(found: Iterable[Restriction], value: str) -> list[Restriction]:
    """The restrictions that keep ``value`` out: an allow-list not naming it or
    a deny-list naming it. Any single one is enough, which is what makes
    allow-lists intersect and a deny always win."""
    return [r for r in found if (r.kind == "allow") != (value in r.values)]


def allowed_values(tags: Iterable[Tag], direct: Iterable[int], axis: str, universe: Sequence[str]) -> list[str]:
    """A Helper's allowed set on one axis: the intersection of every applicable
    Tag's allow-list (a Tag with none does not narrow) minus every applicable
    deny-list, in ``universe`` order."""
    found = restrictions(tags, direct, axis, universe)
    return [v for v in universe if not blocking(found, v)]


def describe_restriction(r: Restriction, axis: str, display: Callable[[str], str] = str) -> str:
    """``Štítek 8.M, povoluje jen budovu Karlín`` / ``Štítek GCHD, zakazuje role A, B``."""
    many = len(r.values) > 1
    noun = _NOUNS[axis][1 if many else 0]
    verb = "povoluje jen" if r.kind == "allow" else "zakazuje"
    return f"Štítek {r.tag.name}, {verb} {noun} {', '.join(display(v) for v in r.values)}"


def dead_ends(
    tags: Iterable[Tag],
    direct_by_helper: Mapping[int, Iterable[int]],
    universes: Mapping[str, Sequence[str]],
) -> set[tuple[int, str]]:
    """The ``(helper id, axis)`` pairs whose allowed set is empty: a Helper with
    nowhere to go. An axis with an empty universe (no Building configured) has
    nothing to strand anyone from and is skipped."""
    tags = list(tags)
    stranded: set[tuple[int, str]] = set()
    for helper_id, direct in direct_by_helper.items():
        direct = list(direct)
        if not direct:
            continue
        for axis, universe in universes.items():
            if universe and not allowed_values(tags, direct, axis, universe):
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
