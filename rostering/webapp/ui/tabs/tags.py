"""Tab 2: the Season's Tags — the Tag tree as a searchable table (indented in tree
order, with how many Helpers and Organizers carry each Tag). A click on a row
opens that Tag's sheet beside the table (``tag_sheet``), where its form, its
carriers and its delete are; "Nový štítek" opens the same sheet empty. Nothing is
edited on the tab itself. A person's own Tags are also picked in their sheet on
the People tab."""
from __future__ import annotations

from nicegui import ui

from rostering import tags as tag_tree
from rostering.webapp import mutations
from rostering.webapp.ui import fix_focus, pills, tag_import
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.tabs.tag_sheet import NEW

_NAME_SLOT = r"""
<q-td :props="props">
  <q-icon v-if="props.row.focus" name="play_arrow" color="primary" class="q-mr-xs" />
  <span v-html="props.row.html"></span>
</q-td>
"""


def _col(name: str, label: str, *, align: str = "left") -> dict:
    return {"name": name, "label": label, "field": name, "sortable": False, "align": align}


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
        self.session.refresh()

    def _table(self, state: dict) -> None:
        s = self.session
        tags = [tag_tree.tag_from_dict(t) for t in state["tags"]]
        names = {t.id: t.name for t in tags}
        notes = {t["id"]: t.get("note") or "" for t in state["tags"]}
        counts = mutations.tag_helper_counts(state)
        organizer_counts = mutations.tag_organizer_counts(state)
        fix = fix_focus.current(s, "tags")
        rows = [
            {
                "id": tag.id,
                "name": tag.name,  # plain text, so the search matches the name
                "html": f'<span style="margin-left:{depth * 1.25}rem">{"↳ " if depth else ""}'
                f"{pills.pill_html(tag.name, tag.colour)}</span>",
                "focus": fix is not None and fix.tag_id == tag.id,
                "parent": names.get(tag.parent_id, "—") if tag.parent_id is not None else "—",
                "helpers": counts[tag.id],
                "organizers": organizer_counts[tag.id],
                "note": notes[tag.id],
            }
            for tag, depth in tag_tree.tree_order(tags)
        ]
        with ui.row().classes("w-full items-center mt-4"):
            ui.label(f"Štítky ({len(rows)})").classes("text-lg font-bold grow")
            search = ui.input(placeholder="Hledat…").props("dense clearable").classes("w-64")
            ui.button("Nový štítek", icon="add", on_click=lambda: self._select(NEW)).props("flat").mark("add-tag")
            ui.button("Import z dřívějšího ročníku", icon="download", on_click=lambda: tag_import.open_import(s, "tags")).props(
                "flat"
            )
            ui.button("Zestárnout třídu", icon="arrow_upward", on_click=lambda: tag_import.open_promotion(s)).props("flat")
        table = ui.table(
            rows=rows,
            columns=[
                _col("name", "Štítek"),
                _col("parent", "Odvozuje"),
                _col("helpers", "Pomocníci", align="center"),
                _col("organizers", "Organizátoři", align="center"),
                _col("note", "Poznámka"),
            ],
            row_key="id",
            pagination={"rowsPerPage": 0},
        ).classes("w-full cursor-pointer").props("flat bordered dense hide-bottom").mark("tag-table")
        table.bind_filter_from(search, "value")
        table.add_slot("body-cell-name", _NAME_SLOT)
        table.on("rowClick", lambda e: self._select(e.args[1]["id"]))
        if not rows:
            ui.label("Zatím žádné štítky.").classes("text-sm text-gray-500")
        else:
            ui.label(
                "Počty zahrnují i ty, kdo štítek nesou jen odvozeně přes podřízený štítek."
            ).classes("text-xs text-gray-500")
