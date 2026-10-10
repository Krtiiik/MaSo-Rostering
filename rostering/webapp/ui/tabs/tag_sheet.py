"""The Tag sheet: the selected Tag's form (name, colour, parent, note, its rules --
the same rule list a Forced friends group has, minus sharing), who carries it (Helpers and Organizers alike, ticked
in a table) and its delete, in a panel that slides in from the right while the
Tags table stays visible behind it (a click on another row switches the sheet to
that Tag). It is open exactly while ``SeasonView.selected_tag`` is a Tag id (an
existing Tag) or ``"new"`` (the create form) and the Tags tab is showing; a
"Go fix" hand-off opens it by setting the selection."""
from __future__ import annotations

import json
from typing import Optional

from nicegui import ui

from rostering import tags as tag_tree
from rostering.webapp import forced_groups, labels, mutations
from rostering.webapp.ui import dialogs, fix_focus
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.tabs.rule_editor import RuleEditor

NEW = "new"
_RULES_HELP = (
    "Pravidla platí pro každého, kdo štítek nese (i odvozeně). Všechna musí platit zároveň; u „být v“ a „mít "
    "roli“ stačí jedna z vybraných hodnot. „Musí“ člověka omezuje jen na vybrané, „nesmí“ vždy vyhrává. "
    "„Musí sdílet“ platí pro všechny nositele štítku dohromady (jako u vynucené skupinky). "
    "Nastavení, po kterém by někdo neměl žádnou povolenou budovu, místnost ani roli, se odmítne."
)


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
        # Opens on Quasar's own palette of preset colours; the spectrum stays one tab away.
        self._picker.q_color.props("default-view=palette")
        self._paint()

    def _set(self, value: str) -> None:
        self.value = value
        self._paint()

    def _paint(self) -> None:
        self._button.style(f"background-color: {self.value} !important; border: 1px solid rgba(0,0,0,.3)")


class TagSheet:
    """The page's single Tag sheet."""

    def __init__(self, session: UiSession) -> None:
        self.session = session
        self._signature: Optional[str] = None
        with ui.dialog().props("position=right seamless full-height") as self.dialog:
            self.card = ui.card().classes("w-[40rem] max-w-[95vw] h-full overflow-auto p-0 gap-0 no-wrap").style(
                "max-width: min(40rem, 95vw)"
            )
        # Closed by Escape: the selection goes with it.
        self.dialog.on_value_change(self._dialog_toggled)
        session.on_change(self.sync, on="tab")  # shown on the Tags step only

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        """Close the sheet and drop the selection."""
        self.session.view.selected_tag = None
        self.dialog.close()
        self._signature = None
        self.session.refresh_view()

    def _dialog_toggled(self, e) -> None:
        if not e.value and self.session.view.selected_tag is not None:
            self.session.view.selected_tag = None
            self._signature = None
            self.session.refresh_view()

    def _target(self) -> tuple[Optional[object], Optional[dict]]:
        """The selection to show: (``NEW`` | Tag id | None, the Tag's record)."""
        s = self.session
        if s.active_tab != labels.TAB_TAGS or mutations.get_open_season(s.workspace) is None:
            return None, None
        selected = s.view.selected_tag
        if selected == NEW:
            return NEW, None
        tag = next((t for t in s.state["tags"] if t["id"] == selected), None)
        if tag is None:
            s.view.selected_tag = None
            return None, None
        return selected, tag

    def sync(self) -> None:
        """Open, rebuild or close the sheet to match the selection. Rebuilt only
        when what it shows changed, so typing in the form survives unrelated
        redraws."""
        selected, tag = self._target()
        if selected is None:
            self._signature = None
            if self.dialog.value:
                self.dialog.close()
            return
        signature = json.dumps(self._signature_of(selected, tag), sort_keys=True, default=str)
        if self.dialog.value and signature == self._signature:
            return
        self._signature = signature
        self._build(tag)
        self.dialog.open()

    def _signature_of(self, selected, tag: Optional[dict]) -> dict:
        state = self.session.state
        fix = fix_focus.current(self.session, "tags")
        return {
            "selected": selected,
            "tag": tag,
            "tags": [(t["id"], t["name"], t["parent_id"]) for t in state["tags"]],
            "config": [b["name"] for b in state["config"]],
            "helpers": [(h["id"], h["name"]) for h in state["helpers"]],
            "organizers": [(o["id"], o["name"]) for o in state["organizers"]],
            "carriers": mutations.tag_carriers(state, tag["id"]) if tag else None,
            "organizer_carriers": mutations.tag_organizer_carriers(state, tag["id"]) if tag else None,
            "origins": mutations.tag_origin_labels(state, tag["id"]) if tag else None,
            "fix": (fix.helper_id, fix.organizer_id) if fix else None,
        }

    def _build(self, tag: Optional[dict]) -> None:
        state = self.session.state
        self.card.clear()
        with self.card:
            # The top bar stays pinned while the rest of the sheet scrolls under it.
            with ui.row().classes("sticky top-0 z-10 w-full items-center no-wrap bg-white border-b px-4 py-2"):
                with ui.column().classes("gap-0 grow"):
                    ui.label("Štítek").classes("text-xs text-gray-500 uppercase")
                    ui.label("Nový štítek" if tag is None else tag["name"]).classes("text-xl font-bold")
                if tag is not None:
                    ui.button("Smazat štítek", icon="delete", on_click=lambda: self._delete(tag)).props(
                        "flat color=negative dense"
                    )
                ui.button(icon="close", on_click=self.close).props("flat round dense")
            with ui.column().classes("w-full gap-4 p-4"):
                self._form(state, tag)
                if tag is not None:
                    fix = fix_focus.current(self.session, "tags")
                    self._people(state, tag, fix.helper_id if fix else None, fix.organizer_id if fix else None)

    # ------------------------------------------------------------------ form
    def _form(self, state: dict, tag: Optional[dict]) -> None:
        s = self.session
        names = {t["id"]: t["name"] for t in state["tags"]}
        definitions = [tag_tree.tag_from_dict(t) for t in state["tags"]]
        parent_options: dict = {None: "— žádný —"}
        for t, _ in tag_tree.tree_order(definitions):
            if tag is None or tag_tree.can_be_parent(definitions, tag["id"], t.id):
                parent_options[t.id] = names[t.id]
        if tag is not None and tag.get("origins"):
            ui.label("Importováno z: " + ", ".join(mutations.tag_origin_labels(state, tag["id"])) + ".").classes(
                "text-sm text-gray-600"
            )
        name = ui.input("Název", value=tag["name"] if tag else "").classes("w-full").mark("tag-name")
        with ui.row().classes("w-full gap-4 no-wrap"):
            colour = _ColourSwatch(
                tag["colour"] if tag else tag_tree.PALETTE[len(state["tags"]) % len(tag_tree.PALETTE)]
            )
            current_parent = tag["parent_id"] if tag and tag["parent_id"] in parent_options else None
            parent = ui.select(parent_options, label="Odvozuje (nadřazený štítek)", value=current_parent).classes(
                "grow"
            ).tooltip("Každý, kdo má tento štítek, nese i nadřazený štítek a jeho nadřazené.")
        note = ui.textarea("Poznámka", value=tag["note"] if tag else "").classes("w-full").props("autogrow")
        editor = self._rule_section(state, tag)

        async def submit() -> None:
            rules = editor.rules()
            if tag is None:
                new_state = await s.act(
                    lambda: mutations.add_tag(
                        s.workspace, name.value, colour=colour.value, note=note.value, parent_id=parent.value, rules=rules
                    ),
                    success=f"Vytvořeno: {(name.value or '').strip()}.",
                )
                if new_state is not None:
                    s.view.selected_tag = new_state["tags"][-1]["id"]
                    s.refresh()
            else:
                await s.act(
                    lambda: mutations.update_tag(
                        s.workspace,
                        tag["id"],
                        name=name.value,
                        colour=colour.value,
                        note=note.value,
                        parent_id=parent.value,
                        rules=rules,
                    ),
                    success=f"Změny uloženy: {(name.value or '').strip()}.",
                )

        ui.button("Vytvořit štítek" if tag is None else "Uložit změny", on_click=submit).props("color=primary").mark(
            "tag-save"
        )

    def _rule_section(self, state: dict, tag: Optional[dict]) -> RuleEditor:
        """The Tag's rules in the same editor a Forced friends group uses. A place
        a rule names that the Season's layout lacks stays in the list (it is inert:
        the solver and the checker ignore it), noted below, so saving the form does
        not silently drop it."""
        ui.label("Pravidla: kdo štítek nese").classes("text-sm mt-2 font-bold")
        ui.label(_RULES_HELP).classes("text-xs text-gray-600")
        editor = RuleEditor(state["config"], tag["rules"] if tag else [], allow_share=True, new_op="be_must")
        editor.build()
        for note in forced_groups.missing_places(state, tag_tree.record_rules(tag) if tag else []):
            with ui.row().classes("items-center gap-1 text-orange-800"):
                ui.icon("warning", size="xs")
                ui.label(note).classes("text-sm")
        return editor

    async def _delete(self, tag: dict) -> None:
        s = self.session
        lines = _delete_lines(s.state, tag)
        intro = f"Smazáním štítku **{tag['name']}** se změní:" if lines else f"Smazat štítek **{tag['name']}**?"
        if not await dialogs.confirm(
            dialogs.ConfirmSpec(title="Smazat štítek?", ok_label="Smazat štítek", intro=intro, lines=tuple(lines)),
            client=s.client,
        ):
            return
        if await s.act(lambda: mutations.delete_tag(s.workspace, tag["id"], confirmed=True), success=f"Smazáno: {tag['name']}.") is not None:
            self.close()

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

        ui.separator()
        with ui.row().classes("w-full items-center"):
            ui.label(f"Kdo štítek nese ({len(carriers) + len(organizer_carriers)})").classes("text-lg font-bold grow")
            search = ui.input(placeholder="Hledat…").props("dense clearable").classes("w-44")
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
