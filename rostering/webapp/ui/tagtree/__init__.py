"""The Tags tab's tree: the Season's Tag tree as an indented, collapsible list
with drag-and-drop, like a file explorer. A Tag dragged onto another becomes a
child of it (the dragged Tag then *implies* the target); dragged onto the empty
space under the list it becomes a root. ``build_rows`` makes the rows from the
state (pure, tested directly) and :class:`TagTree` shows them through
``tag_tree.js``, which only reports what the user did (``tag_select``,
``tag_move``, ``tag_toggle``); whether a move is allowed is decided by
``mutations.update_tag``. Siblings stay alphabetical (``tags.tree_order``), so a
drop never picks a position. No build step: the JavaScript is a plain ES module
NiceGUI serves as is."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from nicegui import ui

from rostering import tags as tag_tree
from rostering.webapp import mutations
from rostering.webapp.ui import pills

CSS = """
.tag-tree { border: 1px solid rgba(0,0,0,.12); border-radius: 4px; min-height: 8rem; padding-bottom: 3rem; user-select: none; }
.tag-tree.drop-root { background: rgba(25,118,210,.08); outline: 2px dashed rgba(25,118,210,.5); outline-offset: -2px; }
.tag-tree-row { display: grid; grid-template-columns: minmax(12rem, 2fr) 6.5rem 6.5rem minmax(8rem, 3fr); align-items: center;
  column-gap: .5rem; padding: 2px 8px; min-height: 2rem; border-bottom: 1px solid rgba(0,0,0,.05); }
.tag-tree-head { font-size: .75rem; font-weight: 600; color: rgba(0,0,0,.6); background: rgba(0,0,0,.03); cursor: default; }
.tag-tree-row[data-id] { cursor: pointer; }
.tag-tree-row[data-id]:hover { background: rgba(0,0,0,.04); }
.tag-tree-row.selected { background: rgba(25,118,210,.12); }
.tag-tree-row.dragging { opacity: .4; }
.tag-tree-row.drop-into { background: rgba(25,118,210,.2); outline: 2px solid #1976d2; outline-offset: -2px; }
.tag-tree-row .c { text-align: center; }
.tag-tree-row .note { color: rgba(0,0,0,.6); font-size: .85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag-tree-name { display: flex; align-items: center; min-width: 0; }
.tag-tree-chevron { width: 1.5rem; flex: none; display: inline-flex; justify-content: center; }
.tag-tree-empty { padding: 1rem; color: rgba(0,0,0,.5); font-size: .875rem; }
"""


def build_rows(state: dict[str, Any], focus_tag_id: Optional[int] = None) -> list[dict]:
    """The Tags in tree order as the rows the component draws: ``id``,
    ``parent_id`` (None for a root, also for a Tag whose parent is gone), ``depth``,
    ``name`` (plain text, for the search), ``style`` (the pill's CSS), the counts
    of Helpers and Organizers carrying it (inherited ones included), ``note``,
    ``has_children`` and ``focus`` (the Tag a "Go fix" points at)."""
    tags = [tag_tree.tag_from_dict(t) for t in state["tags"]]
    ids = {t.id for t in tags}
    notes = {t["id"]: t.get("note") or "" for t in state["tags"]}
    counts = mutations.tag_helper_counts(state)
    organizer_counts = mutations.tag_organizer_counts(state)
    parents = {t.id: (t.parent_id if t.parent_id in ids else None) for t in tags}
    with_children = {p for p in parents.values() if p is not None}
    return [
        {
            "id": tag.id,
            "parent_id": parents[tag.id],
            "depth": depth,
            "name": tag.name,
            "style": pills.pill_style(tag.colour),
            "helpers": counts[tag.id],
            "organizers": organizer_counts[tag.id],
            "note": notes[tag.id],
            "has_children": tag.id in with_children,
            "focus": focus_tag_id == tag.id,
        }
        for tag, depth in tag_tree.tree_order(tags)
    ]


def ancestor_ids(rows: Iterable[dict], tag_id: Optional[int]) -> list[int]:
    """The ids above ``tag_id`` in ``rows`` (its parent, then that one's parent, ...)."""
    parent_of = {r["id"]: r["parent_id"] for r in rows}
    found: list[int] = []
    current = parent_of.get(tag_id)
    while current is not None and current not in found:
        found.append(current)
        current = parent_of.get(current)
    return found


class TagTree(ui.element, component="tag_tree.js"):
    """The tree element; ``.on("tag_select" | "tag_move" | "tag_toggle", handler)``
    (see the head of ``tag_tree.js`` for the event arguments)."""

    def __init__(self, rows: list[dict], *, selected: Any = None, collapsed: Iterable[int] = (), query: str = "") -> None:
        super().__init__()
        # Once per page: the Tags tab builds a new tree on every redraw.
        if not getattr(self.client, "_tag_tree_css", False):
            ui.add_css(CSS)
            self.client._tag_tree_css = True  # type: ignore[attr-defined]
        self._props["rows"] = rows
        self._props["selected"] = selected
        self._props["collapsed"] = sorted(collapsed)
        self._props["query"] = query

    def set_query(self, query: str) -> None:
        self._props["query"] = query
        self.update()
