"""Tags (see CONTEXT.md "Tag"): pure functions of a Tag tree and of the Tags
assigned to a Helper directly.

A Tag has at most one parent it implies, so the Tags form a forest. A Helper's
*effective* Tags are the ones assigned to them directly plus every ancestor of
those, computed here on demand and never stored on the Helper — editing the tree
therefore updates everyone at once. Nothing in this module touches state or
storage: callers hand it the Tag definitions and the direct assignments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

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


def tag_from_dict(data: dict) -> Tag:
    return Tag(
        id=int(data["id"]),
        name=data["name"],
        colour=data.get("colour") or PALETTE[0],
        note=data.get("note") or "",
        parent_id=data.get("parent_id"),
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
