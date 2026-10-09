"""Tab 2: the Season's Tags — the Tag tree on the left, and on the right the
selected Tag's form (name, colour, parent, note, Building/Role constraints), who
carries it (Helpers and Organizers alike, ticked in a table) and its delete. A
person's own Tags are also picked in their sheet on the People tab."""
from __future__ import annotations

from typing import Optional

from nicegui import ui

from rostering import tags as tag_tree
from rostering.czech import count_helpers, plural
from rostering.domain import Role
from rostering.webapp import mutations
from rostering.webapp.ui import dialogs, fix_focus, pills, tag_import
from rostering.webapp.ui.session import UiSession

_NEW = "new"
_NOT_IN_SEASON = " — není v tomto ročníku"


def _delete_lines(state: dict, tag: dict) -> list[str]:
    impact = mutations.tag_delete_impact(state, tag["id"])
    parent = next((t["name"] for t in state["tags"] if t["id"] == tag["parent_id"]), None)
    lines = []
    if impact["helpers"]:
        lines.append(f"Odebráno pomocníkům ({len(impact['helpers'])}): " + ", ".join(impact["helpers"]))
    if impact["organizers"]:
        lines.append(f"Odebráno organizátorům ({len(impact['organizers'])}): " + ", ".join(impact["organizers"]))
    if impact["children"]:
        lines.append(
            "Podřízené štítky "
            + ", ".join(impact["children"])
            + (f" se přesunou pod {parent}" if parent else " se stanou štítky nejvyšší úrovně")
        )
    return lines


class _ColourSwatch:
    """The Tag's colour as a swatch of that colour; a click opens the picker.
    There is no text field, so `value` is always a hex colour."""

    def __init__(self, value: str) -> None:
        self.value = value
        with ui.column().classes("gap-1"):
            ui.label("Barva").classes("text-xs text-gray-600")
            self._button = ui.button().props("unelevated dense").classes("w-14 h-10").tooltip("Změnit barvu")
            with self._button:
                self._picker = ui.color_picker(on_pick=lambda e: self._set(e.color))
        self._picker.set_color(value)
        self._paint()

    def _set(self, value: str) -> None:
        self.value = value
        self._paint()

    def _paint(self) -> None:
        self._button.style(f"background-color: {self.value} !important; border: 1px solid rgba(0,0,0,.3)")


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
            "ten nadřazený (a jeho nadřazené), počítáno průběžně. Štítky patří k tomuto ročníku."
        ).classes("text-sm text-gray-600")
        # A "Go fix" from a Broken rule: says what to fix here, for as long as it
        # is still broken (the Tag itself was preselected by the hand-off).
        fix = fix_focus.render_callout(s, "tags")
        tag_import.render_summary(s, "tags")
        with ui.row().classes("gap-2"):
            ui.button("Import z dřívějšího ročníku", icon="download", on_click=lambda: tag_import.open_import(s, "tags")).props(
                "flat"
            )
            ui.button("Zestárnout třídu", icon="arrow_upward", on_click=lambda: tag_import.open_promotion(s)).props("flat")

        selected = s.view.selected_tag
        tag = next((t for t in state["tags"] if t["id"] == selected), None)
        if selected != _NEW and tag is None:
            s.view.selected_tag = selected = None
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.card().classes("w-[26rem] shrink-0"):
                self._tree(state, selected)
            with ui.column().classes("grow gap-4 min-w-0"):
                if selected == _NEW:
                    self._form(state, None)
                elif tag is not None:
                    self._form(state, tag)
                    self._people(state, tag, fix.helper_id if fix else None, fix.organizer_id if fix else None)
                else:
                    ui.label("Vyberte štítek, abyste ho upravili nebo viděli, kdo ho nese, nebo vytvořte nový.").classes(
                        "text-gray-600"
                    )

    def _select(self, tag_id) -> None:
        self.session.view.selected_tag = tag_id
        self.session.refresh()

    # ------------------------------------------------------------------ tree
    def _tree(self, state: dict, selected) -> None:
        tags = [tag_tree.tag_from_dict(t) for t in state["tags"]]
        counts = mutations.tag_helper_counts(state)
        organizer_counts = mutations.tag_organizer_counts(state)
        with ui.row().classes("w-full items-center"):
            ui.label("Strom štítků").classes("font-bold grow")
            ui.button("Nový štítek", icon="add", on_click=lambda: self._select(_NEW)).props("color=primary dense")
        if not tags:
            ui.label("Zatím žádné štítky.").classes("text-sm text-gray-500")
            return
        with ui.list().props("dense").classes("w-full"):
            for tag, depth in tag_tree.tree_order(tags):
                count = count_helpers(counts[tag.id])
                if organizer_counts[tag.id]:
                    n = organizer_counts[tag.id]
                    count += f" + {n} " + plural(n, "organizátor", "organizátoři", "organizátorů")
                item = ui.item(on_click=lambda tid=tag.id: self._select(tid)).mark(f"tag-{tag.id}").classes(
                    "rounded" + (" bg-blue-50" if tag.id == selected else "")
                )
                with item:
                    with ui.item_section():
                        ui.html(
                            f'<div style="margin-left:{depth * 1.25}rem">{"↳ " if depth else ""}'
                            f"{pills.pill_html(tag.name, tag.colour)}</div>"
                        )
                    with ui.item_section().props("side"):
                        ui.label(count).classes("text-xs text-gray-500")

    # ------------------------------------------------------------------ form
    def _form(self, state: dict, tag: Optional[dict]) -> None:
        s = self.session
        names = {t["id"]: t["name"] for t in state["tags"]}
        definitions = [tag_tree.tag_from_dict(t) for t in state["tags"]]
        parent_options: dict = {None: "— žádný —"}
        for t, _ in tag_tree.tree_order(definitions):
            if tag is None or tag_tree.can_be_parent(definitions, tag["id"], t.id):
                parent_options[t.id] = names[t.id]
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center"):
                ui.label("Nový štítek" if tag is None else f"Upravit {tag['name']}").classes("text-lg font-bold grow")
                if tag is not None:
                    ui.button("Smazat štítek", icon="delete", on_click=lambda: self._delete(tag)).props(
                        "flat color=negative dense"
                    )
            if tag is not None and tag.get("origins"):
                ui.label("Importováno z: " + ", ".join(mutations.tag_origin_labels(state, tag["id"])) + ".").classes(
                    "text-sm text-gray-600"
                )
            name = ui.input("Název", value=tag["name"] if tag else "").classes("w-full")
            with ui.row().classes("w-full gap-4 no-wrap"):
                colour = _ColourSwatch(
                    tag["colour"] if tag else tag_tree.PALETTE[len(state["tags"]) % len(tag_tree.PALETTE)]
                )
                current_parent = tag["parent_id"] if tag and tag["parent_id"] in parent_options else None
                parent = ui.select(parent_options, label="Odvozuje (nadřazený štítek)", value=current_parent).classes(
                    "grow"
                ).tooltip("Každý, kdo má tento štítek, nese i nadřazený štítek a jeho nadřazené.")
            note = ui.textarea("Poznámka", value=tag["note"] if tag else "").classes("w-full").props("autogrow")
            constraints = self._constraint_pickers(state, tag)

            async def submit() -> None:
                values = {k: list(v.value or []) for k, v in constraints.items()}
                if tag is None:
                    new_state = await s.act(
                        lambda: mutations.add_tag(
                            s.workspace, name.value, colour=colour.value, note=note.value, parent_id=parent.value, **values
                        ),
                        success=f"Vytvořeno: {(name.value or '').strip()}.",
                    )
                    if new_state is not None:
                        self._select(new_state["tags"][-1]["id"])
                else:
                    await s.act(
                        lambda: mutations.update_tag(
                            s.workspace,
                            tag["id"],
                            name=name.value,
                            colour=colour.value,
                            note=note.value,
                            parent_id=parent.value,
                            **values,
                        ),
                        success=f"Změny uloženy: {(name.value or '').strip()}.",
                    )

            ui.button("Vytvořit štítek" if tag is None else "Uložit změny", on_click=submit).props("color=primary")

    def _constraint_pickers(self, state: dict, tag: Optional[dict]) -> dict[str, ui.select]:
        """The four Building/Role allow- and deny-list pickers, chosen from the
        Season's configuration. An entry the Season no longer has stays listed,
        marked "not in this Season" (it is inert: the solver and the checker
        ignore it), so saving the form does not silently drop it."""
        entries = mutations.tag_constraint_entries(state, tag["id"]) if tag else {}
        buildings = [b["name"] for b in state["config"]]
        roles = [role.name for role in Role]
        ui.label(
            "Kam smějí pomocníci s tímto štítkem. Seznam povolených je omezuje jen na něj (štítek bez něj nic "
            "nezužuje); seznam zakázaných vždy vyhrává. Nastavení, po kterém by pomocník neměl žádnou povolenou "
            "budovu ani roli, se odmítne."
        ).classes("text-sm text-gray-600")
        pickers: dict[str, ui.select] = {}
        with ui.grid(columns=2).classes("w-full gap-x-4"):
            for field, label, axis_options in [
                ("building_allow", "Povolit jen budovy", buildings),
                ("building_deny", "Zakázat budovy", buildings),
                ("role_allow", "Povolit jen role", roles),
                ("role_deny", "Zakázat role", roles),
            ]:
                current = entries.get(field, [])
                inert = {e["name"] for e in current if not e["in_season"]}
                values = [*axis_options, *(e["name"] for e in current if e["name"] not in axis_options)]
                options = {
                    v: (Role[v].value if field.startswith("role") and v in Role.__members__ else v)
                    + (_NOT_IN_SEASON if v in inert else "")
                    for v in values
                }
                pickers[field] = ui.select(
                    options, multiple=True, label=label, value=[e["name"] for e in current]
                ).props("use-chips" + ("" if options else ' hint="Nejdřív nastavte budovu"'))
        return pickers

    async def _delete(self, tag: dict) -> None:
        s = self.session
        lines = _delete_lines(s.state, tag)
        intro = f"Smazáním štítku **{tag['name']}** se změní:" if lines else f"Smazat štítek **{tag['name']}**?"
        if not await dialogs.confirm(
            dialogs.ConfirmSpec(title="Smazat štítek?", ok_label="Smazat štítek", intro=intro, lines=tuple(lines)),
            client=self.session.client,
        ):
            return
        if await s.act(lambda: mutations.delete_tag(s.workspace, tag["id"], confirmed=True), success=f"Smazáno: {tag['name']}.") is not None:
            self._select(None)

    # ------------------------------------------------------------------ carriers
    def _people(self, state: dict, tag: dict, fixing_helper_id: Optional[int], fixing_organizer_id: Optional[int]) -> None:
        """Every Helper and Organizer, ticked when they carry the Tag directly. A
        person who carries it only through a child Tag is unticked and marked with
        that Tag; ticking them gives them the Tag directly."""
        s = self.session
        names = {t["id"]: t["name"] for t in state["tags"]}
        carriers = {c["helper_id"]: c for c in mutations.tag_carriers(state, tag["id"])}
        organizer_carriers = {c["organizer_id"]: c for c in mutations.tag_organizer_carriers(state, tag["id"])}
        rows = []
        for h in state["helpers"]:
            via = carriers.get(h["id"], {}).get("via")
            rows.append(
                {
                    "key": f"h{h['id']}",
                    "name": ("⚠ " if h["id"] == fixing_helper_id else "") + h["name"],
                    "kind": "pomocník",
                    "via": f"přes {names[via]}" if via is not None else "",
                }
            )
        for o in state["organizers"]:
            via = organizer_carriers.get(o["id"], {}).get("via")
            rows.append(
                {
                    "key": f"o{o['id']}",
                    "name": ("⚠ " if o["id"] == fixing_organizer_id else "") + o["name"],
                    "kind": "organizátor",
                    "via": f"přes {names[via]}" if via is not None else "",
                }
            )
        rows.sort(key=lambda r: r["name"].lower().lstrip("⚠ "))
        current = {f"h{i}" for i, c in carriers.items() if c["via"] is None}
        current |= {f"o{i}" for i, c in organizer_carriers.items() if c["via"] is None}

        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center"):
                ui.label(f"Kdo štítek nese ({len(carriers) + len(organizer_carriers)})").classes("text-lg font-bold grow")
                search = ui.input(placeholder="Hledat…").props("dense clearable").classes("w-56")
                save = ui.button("Uložit změny").props("color=primary").mark("tag-carriers-save")
            if not rows:
                ui.label("Zatím nejsou žádní pomocníci ani organizátoři.").classes("text-sm text-gray-500")
                return
            table = ui.table(
                rows=rows,
                columns=[
                    {"name": "name", "label": "Jméno", "field": "name", "align": "left", "sortable": True},
                    {"name": "kind", "label": "", "field": "kind", "align": "left"},
                    {"name": "via", "label": "Nese odvozeně", "field": "via", "align": "left"},
                ],
                row_key="key",
                selection="multiple",
                pagination={"rowsPerPage": 0},
            ).props("flat dense hide-bottom virtual-scroll").classes("w-full max-h-[32rem]").mark("tag-carriers")
            table.bind_filter_from(search, "value")
            table.selected = [r for r in rows if r["key"] in current]

            def picked() -> tuple[list[str], list[str]]:
                chosen = {r["key"] for r in table.selected}
                return sorted(chosen - current), sorted(current - chosen)

            def update_button() -> None:
                to_add, to_remove = picked()
                parts = ([f"přidat {len(to_add)}"] if to_add else []) + ([f"odebrat {len(to_remove)}"] if to_remove else [])
                save.text = f"Uložit změny ({', '.join(parts)})" if parts else "Uložit změny"
                save.set_enabled(bool(parts))

            table.on_select(lambda: update_button())
            update_button()

            async def run_save() -> None:
                to_add, to_remove = picked()

                def apply() -> dict:
                    # Additions first: they can be refused, and then nothing has changed yet.
                    new_state = s.state
                    if to_add:
                        new_state = mutations.add_tag_to_helpers(
                            s.workspace,
                            tag["id"],
                            [int(k[1:]) for k in to_add if k[0] == "h"],
                            [int(k[1:]) for k in to_add if k[0] == "o"],
                        )
                    for key in to_remove:
                        remove = mutations.remove_tag_from_helper if key[0] == "h" else mutations.remove_tag_from_organizer
                        new_state = remove(s.workspace, tag["id"], int(key[1:]))
                    return new_state

                await s.act(apply, success="Uloženo.")

            save.on_click(run_save)
