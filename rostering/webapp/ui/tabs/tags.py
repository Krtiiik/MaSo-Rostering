"""Tab 2: the Season's Tags — the Tag tree as a searchable, collapsible,
drag-and-drop tree (``ui/tagtree``, with how many Helpers and Organizers carry
each Tag). Dragging a Tag onto another makes it that Tag's child, onto the empty
space a root. A click on a row opens that Tag's sheet beside the tree
(``tag_sheet``), where its form, its carriers and its delete are; "Nový štítek"
opens the same sheet empty. A person's own Tags are also picked in their sheet on
the People tab."""
from __future__ import annotations

from nicegui import ui

from rostering.webapp import mutations
from rostering.webapp.ui import fix_focus, tag_import, tagtree as tag_tree
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.tabs.tag_sheet import NEW

class TagsTab:
    def __init__(self, session: UiSession) -> None:
        self.session = session

    def render(self) -> None:
        s = self.session
        if mutations.get_open_season(s.workspace) is None:
            ui.label("Než přidáte štítky, otevřete ročník (nebo nahráním odpovědí nějaký vytvořte).")
            return
        state = s.state
        ui.label(
            "Štítek označuje pomocníky; může odvozovat jeden nadřazený štítek, takže každý, kdo ho nese, nese i "
            "ten nadřazený (a jeho nadřazené), počítáno průběžně. Štítky patří k tomuto ročníku. Kliknutím na štítek "
            "ho upravíte a uvidíte, kdo ho nese."
        ).classes("text-sm text-gray-600")
        # A "Go fix" from a Broken rule: says what to fix here, for as long as it
        # is still broken (the Tag itself was preselected by the hand-off, which
        # opens its sheet).
        fix_focus.render_callout(s, "tags")
        tag_import.render_summary(s, "tags")
        self._table(state)

    def _select(self, tag_id) -> None:
        self.session.view.selected_tag = tag_id
        self.session.refresh_view()

    def _table(self, state: dict) -> None:
        s = self.session
        fix = fix_focus.current(s, "tags")
        rows = tag_tree.build_rows(state, fix.tag_id if fix else None)
        # A Tag being selected or fixed must be in sight, so its branches are open.
        for shown in (s.view.selected_tag, fix.tag_id if fix else None):
            s.view.tags_collapsed -= set(tag_tree.ancestor_ids(rows, shown))
        with ui.row().classes("w-full items-center mt-4"):
            ui.label(f"Štítky ({len(rows)})").classes("text-lg font-bold grow")
            search = ui.input(placeholder="Hledat…", value=s.view.tags_search).props("dense clearable").classes("w-64")
            ui.button("Nový štítek", icon="add", on_click=lambda: self._select(NEW)).props("flat").mark("add-tag")
            ui.button("Import z dřívějšího ročníku", icon="download", on_click=lambda: tag_import.open_import(s, "tags")).props(
                "flat"
            )
            ui.button("Zestárnout třídu", icon="arrow_upward", on_click=lambda: tag_import.open_promotion(s)).props("flat")
        tree = tag_tree.TagTree(
            rows, selected=s.view.selected_tag, collapsed=s.view.tags_collapsed, query=s.view.tags_search
        ).classes("w-full").mark("tag-tree")
        tree.on("tag_select", lambda e: self._select(e.args["id"]))
        tree.on("tag_move", self._move)
        tree.on("tag_toggle", self._toggle)

        def searched(e) -> None:
            s.view.tags_search = e.value or ""
            tree.set_query(s.view.tags_search)

        search.on_value_change(searched)
        ui.label(
            "Přetažením štítku na jiný ho zařadíte pod něj (ten nadřazený pak odvozuje); přetažením na prázdné místo "
            "pod stromem z něj uděláte štítek nejvyšší úrovně. Podřízené štítky se řadí podle abecedy. Počty zahrnují "
            "i ty, kdo štítek nesou jen odvozeně přes podřízený štítek."
        ).classes("text-xs text-gray-500")

    def _toggle(self, e) -> None:
        collapsed = self.session.view.tags_collapsed
        (collapsed.add if e.args["collapsed"] else collapsed.discard)(e.args["id"])

    async def _move(self, e) -> None:
        """A drop: the dragged Tag now implies the Tag it was dropped on (or none).
        ``update_tag`` refuses what would make a Tag its own ancestor or strand
        someone; the refusal is shown and the tree stays as it was."""
        s = self.session
        tag_id, parent_id = e.args["id"], e.args["parent_id"]
        names = {t["id"]: t["name"] for t in s.state["tags"]}
        if tag_id not in names:
            return
        where = f"pod {names[parent_id]}" if parent_id is not None else "na nejvyšší úroveň"
        if parent_id is not None:
            s.view.tags_collapsed.discard(parent_id)  # show where it went
        await s.act(
            lambda: mutations.update_tag(s.workspace, tag_id, parent_id=parent_id),
            success=f"Přesunuto: {names[tag_id]} {where}.",
        )
