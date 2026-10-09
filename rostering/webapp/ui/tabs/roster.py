"""Tab 6: the roster — the drag-and-drop grid (see ``rostering.webapp.ui.grid``)
under a toolbar with Solve, Place new registrants, Export, the lock controls, the
Overlays and the Tag filter, and a badge opening the Broken rules beside the grid.

A drop is never refused, whatever it breaks; a notification names what that drop
newly broke (minimums excepted). Moving a Helper out of the Room an Additional
role of theirs is scoped to asks first. A manual role's cell edit goes to
``set_slot_holders`` for a leadership slot (it takes tracked Organizers) and to
``put_manual_roles`` for an Additional role (a typed name is matched to an
attending Helper or kept as text)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from nicegui import ui

from rostering import tags as tag_tree
from rostering.czech import plural
from rostering.domain import BrokenRule
from rostering.webapp import mutations
from rostering.webapp.reveal import reveal_in_file_manager
from rostering.webapp.ui import dialogs, fix_focus, solving
from rostering.webapp.ui.grid import RosterGrid
from rostering.webapp.ui.grid import data as grid_data
from rostering.webapp.ui.grid.card import HelperCard
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.tabs.person_sheet import PersonSheet

# How the Broken rules name each rule family, in tier order. A family not listed
# (registered later through rostering.solver.rules) falls back to its own name.
FAMILY_LABELS = {
    "minimums": "Počty v místnostech a budovách",
    "tag_restrictions": "Omezení štítků",
    "forced_friends": "Vynucené skupinky kamarádů",
    "equipment": "Vybavení",
}
# A family with more broken instances than this collapses into an expandable
# summary, so the list never becomes a wall of text.
COLLAPSE_ABOVE = 10
_MODE_LABELS = {tag_tree.ALL_OF: "Všechny", tag_tree.ANY_OF: "Kterýkoli"}
_OVERLAYS_HELP = (
    "Kamarádi: zvýrazní přání být s kamarádem. Štítky: obarví blok každého člověka podle jeho štítků. "
    "Spokojenost s rolí: svislý okraj vlevo, zelený = role mu nevadí nebo ji chce, červený = spíš ne nebo ne. "
    "Spokojenost s budovou: vodorovný okraj nahoře, zelený = je v některé z přijatelných budov, červený = není."
)


class RosterTab:
    def __init__(self, session: UiSession, sheet: PersonSheet) -> None:
        self.session = session
        self.sheet = sheet
        self.card = HelperCard(self._toggle_lock, lambda helper_id: self.sheet.show("helper", helper_id))
        self.broken_open = False
        self.grid: Optional[RosterGrid] = None

    # ------------------------------------------------------------------ page
    def render(self) -> None:
        s = self.session
        state = s.state
        if not grid_data.flatten_rooms(state["config"]):
            ui.label("Nejdřív nastavte alespoň jednu budovu s místností.")
            return
        self._warnings()
        self._toolbar()
        self._export_note()
        self.grid = RosterGrid().classes("w-full").mark("roster-grid")
        self.grid.on("helper_drop", lambda e: self._drop(e.args))
        self.grid.on("organizer_drop", lambda e: self._organizer_drop(e.args))
        self.grid.on("manual_set", lambda e: self._manual_set(e.args))
        self.grid.on("cell_merge", lambda e: self._cell_merge(e.args))
        self.grid.on("lock", lambda e: self._toggle_lock(int(e.args["helper_id"]), bool(e.args["locked"])))
        self.grid.on("card", lambda e: self.card.toggle(self.grid.view, e.args))
        self.grid.on("card_close", lambda: self.card.close())
        self._draw_grid()
        self.card.attach(self.grid.view)
        self._broken_sheet()

    def _draw_grid(self) -> None:
        if self.grid is None:
            return
        v = self.session.view
        self.grid.show(self.session.state, v.grid_overlays, v.grid_tag_filter, v.grid_tag_mode)

    def _warnings(self) -> None:
        state = self.session.state
        stale = mutations.stale_reasons(state)
        if stale:
            _banner(
                "**Rozdělení pomocníků je neaktuální:** "
                + "; ".join(stale)
                + ". Sestavte rozdělení znovu; do té doby je export zablokovaný."
            )
        unplaced = mutations.unplaced_reason(state)
        if unplaced:
            _banner(
                f"**{unplaced}.** Přetáhněte je do mřížky z oblasti Nezařazení, použijte Zařadit nové registrované "
                "(všichni zařazení zůstanou na místě), nebo sestavte rozdělení; export je zablokovaný, dokud nejsou "
                "všichni zařazeni."
            )

    # ------------------------------------------------------------------ toolbar
    def _toolbar(self) -> None:
        s = self.session
        state = s.state
        locked = mutations.locked_count(state)
        assignments = state["assignments"]
        unplaced = mutations.unplaced_reason(state)
        blockers = mutations.export_blockers(state)
        broken = mutations.broken_rules(state)
        with ui.card().classes("w-full sticky top-0 z-20 py-2"):
            with ui.row().classes("w-full items-center gap-2"):
                solve_label = (
                    f"Sestavit rozdělení (zachová uzamčených: {locked})"
                    if locked
                    else ("Sestavit znovu" if assignments else "Sestavit rozdělení")
                )
                ui.button(solve_label, icon="auto_fix_high", on_click=lambda: solving.solve(s)).props("color=primary").mark("solve")
                place = ui.button("Zařadit nové registrované", icon="person_add", on_click=lambda: solving.place_new(s))
                place.props("outline").tooltip(
                    "Zařadí jen nezařazené pomocníky; všichni už zařazení zůstanou přesně tam, kde jsou."
                )
                if not unplaced:
                    place.disable()
                export = ui.button("Export do Excelu", icon="download", on_click=self._export).props("outline")
                if not assignments or blockers:
                    export.disable()
                if assignments and blockers:
                    export.tooltip("Export je zablokovaný: " + "; ".join(blockers))
                elif assignments:
                    export.tooltip("Uloží rozdělení do složky sezóny (přepíše předchozí export).")
                ui.chip(f"{locked} uzamčeno", icon="lock").props("outline")
                with ui.button(icon="more_vert").props("flat round"):
                    with ui.menu():
                        lock_all = ui.menu_item(
                            "Uzamknout všechny zařazené",
                            on_click=lambda: s.act(lambda: mutations.lock_all_placed(s.workspace)),
                        )
                        lock_all.set_enabled(bool(assignments) and locked != len(assignments))
                        clear_locks = ui.menu_item(
                            "Zrušit všechny zámky", on_click=lambda: s.act(lambda: mutations.clear_all_locks(s.workspace))
                        )
                        clear_locks.set_enabled(bool(locked))
                        ui.separator()
                        clear = ui.menu_item("Vymazat rozdělení", on_click=lambda: solving.clear_roster(s))
                        clear.set_enabled(bool(assignments))
                ui.space()
                if broken:
                    count = len(broken)
                    noun = plural(count, "porušené pravidlo", "porušená pravidla", "porušených pravidel")
                    ui.button(f"{count} {noun}", icon="warning", on_click=self._open_broken).props(
                        "color=negative outline"
                    )
                elif assignments:
                    ui.label("✓ Žádná porušená pravidla").classes("text-sm text-positive")
            self._overlay_controls()

    def _overlay_controls(self) -> None:
        """The Overlays chips and, while the Tags overlay is on, the Tag filter
        (it only ever dims, never hides)."""
        s = self.session
        view = s.view
        with ui.row().classes("w-full items-center gap-1"):
            ui.label("Zobrazení:").classes("text-sm text-gray-600").tooltip(_OVERLAYS_HELP)
            for key, label in grid_data.OVERLAYS.items():
                ui.chip(
                    label,
                    selectable=True,
                    selected=key in view.grid_overlays,
                    on_selection_change=lambda e, k=key: self._set_overlay(k, e.sender.selected),
                ).props("outline color=primary")
        if grid_data.TAGS_OVERLAY not in view.grid_overlays:
            return
        tags = s.state.get("tags") or []
        known = {t["id"] for t in tags}
        # A Tag deleted since the filter was chosen.
        view.grid_tag_filter = [t for t in view.grid_tag_filter if t in known]
        names = {t["id"]: t["name"] for t in tags}
        ordered = [t.id for t, _ in tag_tree.tree_order([tag_tree.tag_from_dict(t) for t in tags])]
        # Its own row under the chips, not beside them.
        with ui.row().classes("w-full items-center gap-1"):
            picker = ui.select(
                {tid: names[tid] for tid in ordered},
                multiple=True,
                label="Filtrovat podle štítků",
                value=list(view.grid_tag_filter),
                on_change=lambda e: self._set_filter(list(e.value or []), view.grid_tag_mode),
            ).props("dense use-chips").classes("min-w-[16rem]")
            picker.tooltip("Pomocníci a organizátoři, kteří neodpovídají, se ztlumí, nikdy nezmizí. Odvozené štítky se počítají.")
            radio = ui.radio(
                _MODE_LABELS,
                value=view.grid_tag_mode,
                on_change=lambda e: self._set_filter(view.grid_tag_filter, e.value),
            ).props("inline dense")
            if not tags:
                picker.disable()
                radio.disable()
                picker.props('label="Zatím žádné štítky"')

    def _set_overlay(self, key: str, on: bool) -> None:
        view = self.session.view
        chosen = set(view.grid_overlays) | {key} if on else set(view.grid_overlays) - {key}
        view.grid_overlays = [k for k in grid_data.OVERLAYS if k in chosen]
        if key == grid_data.TAGS_OVERLAY:
            self.session.refresh()  # shows or hides the Tag filter
        else:
            self._draw_grid()

    def _set_filter(self, tag_ids: list[int], mode: str) -> None:
        view = self.session.view
        view.grid_tag_filter, view.grid_tag_mode = tag_ids, mode
        self._draw_grid()

    # ------------------------------------------------------------------ export
    def _export(self) -> None:
        s = self.session
        try:
            path = mutations.save_export_to_season(s.workspace)
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return
        s.view.export_path = str(path)
        s.refresh()

    def _export_note(self) -> None:
        """Where the last export went, with a button revealing it in the file
        manager; shown while that file is still the open Season's export."""
        s = self.session
        saved = s.view.export_path
        if not saved:
            return
        path = Path(saved)
        if not path.is_file() or path.parent != s.workspace.open_season_dir():
            s.view.export_path = None
            return
        with ui.row().classes("w-full items-center no-wrap gap-2 rounded bg-green-50 px-3 py-2"):
            ui.icon("check_circle", color="positive")
            ui.label(f"Rozdělení uloženo do {path}").classes("grow")
            ui.button("Zobrazit ve složce", on_click=lambda: reveal_in_file_manager(path)).props("flat dense")

    # ------------------------------------------------------------------ Broken rules
    def _open_broken(self) -> None:
        self.broken_open = True
        self.broken_dialog.open()

    def _broken_sheet(self) -> None:
        """The Broken rules beside the grid: one line per broken rule instance,
        grouped by family in the order the rules bend, each with "Opravit" (Go fix)
        where the rule has a place to be fixed."""
        broken = mutations.broken_rules(self.session.state)
        with ui.dialog().props("position=right seamless full-height") as dialog:
            dialog.on_value_change(lambda e: setattr(self, "broken_open", bool(e.value)))
            with ui.card().classes("h-full overflow-auto").style("width: min(32rem, 95vw); max-width: min(32rem, 95vw)"):
                with ui.row().classes("w-full items-center no-wrap"):
                    count = len(broken)
                    title = (
                        f"{count} " + plural(count, "porušené pravidlo", "porušená pravidla", "porušených pravidel")
                        if broken
                        else "Žádná porušená pravidla"
                    )
                    ui.label(title).classes("text-lg font-bold grow")
                    ui.button(icon="close", on_click=dialog.close).props("flat round dense")
                by_family: dict[str, list[BrokenRule]] = {}
                for rule in broken:
                    by_family.setdefault(rule.family, []).append(rule)
                for family, instances in by_family.items():
                    label = FAMILY_LABELS.get(family, family)
                    if len(instances) > COLLAPSE_ABOVE:
                        with ui.expansion(f"{label}: porušeno {len(instances)}").classes("w-full"):
                            for rule in instances:
                                self._broken_line(rule, dialog)
                    else:
                        ui.label(label).classes("text-sm text-gray-600 mt-2")
                        for rule in instances:
                            self._broken_line(rule, dialog)
        self.broken_dialog = dialog
        if self.broken_open and broken:
            dialog.open()

    def _broken_line(self, rule: BrokenRule, dialog: ui.dialog) -> None:
        with ui.row().classes("w-full items-start no-wrap gap-2"):
            ui.label(f"• {rule.line}").classes("grow text-sm")
            if fix_focus.can_go_fix(rule):

                def go(r: BrokenRule = rule) -> None:
                    self.broken_open = False
                    dialog.close()
                    fix_focus.go_fix(self.session, r)

                ui.button("Opravit", on_click=go).props("flat dense color=primary")

    # ------------------------------------------------------------------ grid events
    async def _drop(self, args: dict) -> None:
        """Place the dropped Helper. Moving them out of the Room an Additional
        role of theirs is scoped to takes them out of it, so that asks first."""
        s = self.session
        before = s.state
        name = next((h["name"] for h in before["helpers"] if h["id"] == args["helper_id"]), "pomocník")
        moved = await s.act(
            lambda confirmed: mutations.move_helper(
                s.workspace, args["helper_id"], args["building"], args["room"], args["role"], confirmed=confirmed
            ),
            confirm=dialogs.ConfirmSpec(
                title="Odebrat pomocníka z manuální role?",
                ok_label="Přesunout a odebrat",
                intro=f"Přesunutím pomocníka **{name}** do jiné místnosti se odebere z:",
                caption="Nelze vrátit zpět; do role je třeba ho případně znovu zapsat.",
            ),
        )
        if moved is None:
            self._draw_grid()  # put the chip back where it is saved
            return
        for line in mutations.move_toast_lines(before, s.state):
            ui.notify(line, type="warning", icon="warning", multi_line=True)

    async def _organizer_drop(self, args: dict) -> None:
        s = self.session
        source = args.get("source")
        await s.act(
            lambda: mutations.move_organizer(
                s.workspace,
                args["organizer_id"],
                args["key"],
                args["building"],
                args.get("room"),
                {"role": source["key"], "building": source["building"], "room": source.get("room")} if source else None,
            )
        )

    async def _manual_set(self, args: dict) -> None:
        s = self.session
        key, building, room, names = args["key"], args.get("building"), args.get("room"), list(args.get("names") or [])
        if key in grid_data.STRUCTURAL_ROLE_NAMES:
            # A leadership slot takes a tracked Organizer: picked by name or
            # created on the spot; the placement follows.
            await s.act(lambda: mutations.set_slot_holders(s.workspace, key, building, room, names))
        else:
            next_manual = grid_data.apply_overlay_set(s.state, key, building, room, names)
            await s.act(lambda: mutations.put_manual_roles(s.workspace, next_manual))

    async def _cell_merge(self, args: dict) -> None:
        s = self.session
        await s.act(
            lambda: mutations.set_cell_merges(s.workspace, args["key"], args["building"], args["pairs"], bool(args["merged"]))
        )

    async def _toggle_lock(self, helper_id: int, locked: bool) -> None:
        # Never blocks and never touches the Broken-rule check.
        s = self.session
        await s.act(lambda: mutations.set_lock(s.workspace, helper_id, locked))


def _banner(markdown: str) -> None:
    with ui.row().classes("w-full items-start no-wrap gap-2 rounded bg-amber-50 px-3 py-2"):
        ui.icon("warning", color="warning")
        ui.markdown(markdown)
