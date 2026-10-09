"""Tab 4: the Buildings, their Rooms and how many Helpers each Role must have in
each (the minimums). One card per Building holds a Role × Room matrix edited in
place; the layout is a draft on the session until saved (Save, or Save & solve),
and an "unsaved changes" chip says when the draft differs from the Season."""
from __future__ import annotations

import copy
from typing import Optional

from nicegui import events, ui

from rostering.czech import plural
from rostering.domain import Role
from rostering.persistence import config_store
from rostering.webapp import mutations
from rostering.webapp.ui import dialogs, fix_focus, solving
from rostering.webapp.ui.session import UiSession

_ROLE_LABELS = {r.name: r.value for r in Role}
_ROLE_ORDER = [r.name for r in Role]


def layout_key(buildings: list[dict]) -> list:
    """A building layout reduced to what it means: names and every Role's
    count (an absent capacity counts as 0, as the draft's fields show it)."""

    def caps(capacities: dict) -> dict[str, int]:
        return {r: int((capacities.get(r) or {}).get("minimum") or 0) for r in _ROLE_ORDER}

    return [
        (
            b["name"],
            caps(b.get("capacities") or {}),
            [(r["name"], caps(r.get("capacities") or {})) for r in b.get("rooms") or []],
        )
        for b in buildings
    ]


def has_unsaved_changes(state: dict, buildings: list[dict], sheet_pending: Optional[dict] = None) -> bool:
    """Whether the drafted layout differs from what the open Season has saved, or
    a sheet's leaders and merges are waiting to be saved with it."""
    return sheet_pending is not None or layout_key(buildings) != layout_key(state["config"])


class BuildingsTab:
    def __init__(self, session: UiSession) -> None:
        self.session = session

    @property
    def draft(self) -> list[dict]:
        view = self.session.view
        if view.buildings_draft is None:
            view.buildings_draft = copy.deepcopy(self.session.state["config"])
        return view.buildings_draft

    def render(self) -> None:
        s = self.session
        ui.label(
            "Určete budovy, jejich místnosti a kolik pomocníků v každé roli musí každá z nich v tomto ročníku mít."
        )
        fix = fix_focus.render_callout(s, "buildings")
        buildings = self.draft
        for bi, building in enumerate(buildings):
            self._building(buildings, bi, fix.building if fix else None)
        ui.button("Přidat budovu", icon="add", on_click=self._add_building).props("flat").mark("add-building")
        self._footer()

    def _changed(self) -> None:
        self._unsaved.refresh()

    def _structure_changed(self) -> None:
        self.session.refresh()

    # ------------------------------------------------------------------ one Building
    def _building(self, buildings: list[dict], bi: int, fix_building: Optional[str]) -> None:
        building = buildings[bi]
        rooms: list[dict] = building["rooms"]
        focused = fix_building is not None and fix_building == building["name"]
        with ui.card().classes("w-full" + (" ring-2 ring-primary" if focused else "")):
            with ui.row().classes("w-full items-center no-wrap"):
                if focused:
                    ui.icon("play_arrow", color="primary")
                name = ui.input("Název budovy", value=building["name"]).classes("w-72")

                def rename(e, b=building) -> None:
                    b["name"] = e.value or ""
                    self._changed()

                name.on_value_change(rename)
                ui.space()
                ui.button("Přidat místnost", icon="add", on_click=lambda: self._add_room(rooms)).props("flat dense")
                ui.button("Odebrat budovu", icon="delete", on_click=lambda: self._remove(buildings, bi)).props(
                    "flat dense color=negative"
                )
            with ui.element("div").classes("w-full overflow-x-auto"):
                columns = len(rooms) + 2
                with ui.grid(columns=f"10rem repeat({columns - 1}, minmax(7rem, 9rem))").classes("gap-1 items-center"):
                    ui.label("")
                    ui.label(f"{building['name'] or 'Budova'} (celkem)").classes("font-bold text-sm")
                    for ri, room in enumerate(rooms):
                        with ui.row().classes("no-wrap items-center gap-0"):
                            room_name = ui.input(value=room["name"]).props("dense").classes("grow")

                            def rename_room(e, r=room) -> None:
                                r["name"] = e.value or ""
                                self._changed()

                            room_name.on_value_change(rename_room)
                            ui.button(icon="close", on_click=lambda ri=ri: self._remove(rooms, ri)).props(
                                "flat dense round size=sm"
                            ).tooltip("Odebrat místnost")
                    for role_name in _ROLE_ORDER:
                        ui.label(_ROLE_LABELS[role_name])
                        self._count(building.setdefault("capacities", {}), role_name)
                        for room in rooms:
                            self._count(room.setdefault("capacities", {}), role_name)

    def _count(self, capacities: dict, role_name: str) -> None:
        cap = capacities.get(role_name) or {"minimum": 0}

        def changed(e) -> None:
            capacities[role_name] = {"minimum": max(0, int(e.value or 0))}
            self._changed()

        ui.number(value=int(cap.get("minimum") or 0), min=0, step=1, precision=0, on_change=changed).props(
            "dense outlined"
        )

    # ------------------------------------------------------------------ structure
    def _add_building(self) -> None:
        buildings = self.draft
        taken = {b["name"] for b in buildings}
        number = len(buildings) + 1
        while f"Budova {number}" in taken:
            number += 1
        # Named afterwards in the Building's own name field.
        buildings.append({"name": f"Budova {number}", "rooms": [], "capacities": {}})
        self._structure_changed()

    def _add_room(self, rooms: list[dict]) -> None:
        rooms.append({"name": f"Místnost {len(rooms) + 1}", "capacities": {}})
        self._structure_changed()

    def _remove(self, items: list, index: int) -> None:
        items.pop(index)
        self._structure_changed()

    # ------------------------------------------------------------------ footer
    @ui.refreshable_method
    def _unsaved(self) -> None:
        if has_unsaved_changes(self.session.state, self.draft, self.session.view.sheet_pending):
            ui.chip("Neuložené změny", icon="warning", color="warning").props("outline").mark("unsaved").tooltip(
                "Rozložení zde se uloží, až kliknete na Uložit konfiguraci (nebo Uložit a sestavit rozdělení). "
                "Znovunačtení stránky je zahodí."
            )

    def _footer(self) -> None:
        s = self.session
        with ui.row().classes("sticky bottom-0 w-full items-center gap-2 bg-white border-t py-2 z-10"):
            ui.button("Uložit konfiguraci", on_click=self._save).props("outline").mark("buildings-save")
            solve = ui.button("Uložit a sestavit rozdělení", on_click=self._save_and_solve).props("color=primary").mark("save-and-solve")
            if not s.state["helpers"]:
                solve.disable()
                ui.label("Nejdřív nahrajte odpovědi pomocníků.").classes("text-sm text-gray-500")
            self._import_button()
            ui.button("Obnovit výchozí budovy", on_click=self._reset).props("flat").mark("buildings-reset").tooltip(
                "Nahradí rozložení zde výchozím, které je součástí aplikace. Uloží se až kliknutím na Uložit konfiguraci."
            )
            self._unsaved()

    async def _put(self) -> Optional[dict]:
        """Save the draft to the open Season (a copy, so later edits to the draft
        never reach the saved state through a shared reference). A layout read from
        a sheet is saved together with its leaders and merges, which replace the
        Season's own after a confirmation."""
        s = self.session
        pending = s.view.sheet_pending
        if pending is None:
            try:
                saved = mutations.put_config(s.workspace, copy.deepcopy(self.draft))
            except mutations.RosteringError as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
                return None
            s.apply(saved)
            return saved
        notes: list[str] = []
        saved = await s.act(
            lambda confirmed: mutations.put_config_from_sheet(
                s.workspace, copy.deepcopy(self.draft), pending, confirmed=confirmed, warnings=notes
            ),
            confirm=dialogs.ConfirmSpec(
                title="Nahradit vedoucí a sloučené buňky?",
                ok_label="Nahradit a uložit",
                intro="Uložením načtené tabulky se **nahradí** obsazení rolí Vedoucí budovy, Pravá ruka, "
                "Vedoucí místností a Technická podpora i sloučené buňky v mřížce:",
                caption="Organizátory to nesmaže, jen jim zruší zařazení, které tabulka nepotvrdí.",
            ),
        )
        if saved is None:
            return None
        s.view.sheet_pending = None
        for line in notes:
            ui.notify(line, type="warning", multi_line=True)
        return saved

    async def _save(self) -> None:
        if await self._put() is not None:
            ui.notify("Konfigurace uložena.", type="positive")

    async def _save_and_solve(self) -> None:
        # Saved first, so the confirmation counts against the new layout (a
        # removed Room drops its locks). Removing a Room that holds a lock is
        # never blocked or prompted here.
        if await self._put() is not None:
            await solving.solve(self.session, open_roster=True)

    def _import_button(self) -> None:
        """A button that opens the file picker of a hidden Quasar uploader."""
        uploader = ui.upload(on_upload=self._uploaded, auto_upload=True, max_files=1).props('accept=".xlsx"').classes(
            "hidden"
        ).mark("buildings-sheet-upload")
        ui.button("Načíst z Excelu", icon="upload_file", on_click=lambda: uploader.run_method("pickFiles")).props(
            "flat"
        ).mark("buildings-sheet-import").tooltip(
            "Nahradí rozložení zde tabulkou „Pomocníci v místnostech“ (.xlsx): budovy a místnosti podle sloučených "
            "buněk záhlaví, počty podle barevných buněk (šedé a prázdné pomocníka nepotřebují). Načte i organizátory "
            "v rolích vedoucích (podle jména, musí už být v ročníku) a sloučené buňky, i ty přes více rolí. "
            "Uloží se až kliknutím na Uložit konfiguraci."
        )

    async def _uploaded(self, e: events.UploadEventArguments) -> None:
        content = await e.file.read()
        e.sender.reset()
        try:
            buildings, pending, warnings = mutations.read_building_sheet(self.session.workspace, content)
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return
        self.session.view.buildings_draft = buildings
        self.session.view.sheet_pending = pending
        self._structure_changed()
        rooms = sum(len(b["rooms"]) for b in buildings)
        leaders = len(pending["slots"])
        ui.notify(
            f"Načteno: {len(buildings)} {plural(len(buildings), 'budova', 'budovy', 'budov')}, "
            f"{rooms} {plural(rooms, 'místnost', 'místnosti', 'místností')}, "
            f"{leaders} {plural(leaders, 'zařazení organizátora', 'zařazení organizátorů', 'zařazení organizátorů')}. "
            "Uložte konfiguraci, aby se použilo.",
            type="positive",
        )
        for line in warnings:
            ui.notify(line, type="warning", multi_line=True)

    def _reset(self) -> None:
        """Replace the draft with the bundled default; nothing is saved."""
        self.session.view.buildings_draft = config_store.load_bundled_config()
        self.session.view.sheet_pending = None
        self._structure_changed()
