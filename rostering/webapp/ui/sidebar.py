"""The left drawer: every stored Season (Open, Rename, Delete, New Season) and
the open Season's named Versions (save, Restore, Delete)."""
from __future__ import annotations

from nicegui import ui

from rostering.czech import count_helpers
from rostering.webapp import labels, mutations
from rostering.webapp.ui import dialogs
from rostering.webapp.ui.session import UiSession


class Sidebar:
    def __init__(self, session: UiSession) -> None:
        self.session = session
        session.on_change(self.render.refresh)

    @ui.refreshable_method
    def render(self) -> None:
        with ui.column().classes("w-full gap-2"):
            self._seasons()
            ui.separator().classes("my-2")
            self._versions()

    # ------------------------------------------------------------------ Seasons
    def _seasons(self) -> None:
        s = self.session
        with ui.row().classes("w-full items-center"):
            ui.label("Ročníky").classes("text-base font-bold grow")
            ui.button(
                "Nový ročník",
                icon="add",
                on_click=lambda: s.act(lambda: mutations.new_season(s.workspace), replaced=True),
            ).props("flat dense no-caps")
        seasons = mutations.list_seasons(s.workspace)
        if not seasons:
            ui.label("Zatím žádné uložené ročníky.").classes("text-sm text-gray-500")
            return
        for season in seasons:
            with ui.card().tight().classes("w-full" + (" border-primary border-2" if season["open"] else "")):
                with ui.row().classes("w-full items-center no-wrap px-3 py-2 gap-1"):
                    with ui.column().classes("gap-0 grow"):
                        ui.label(season["label"]).classes("font-bold")
                        state_label = "otevřený" if season["open"] else "uložený"
                        ui.label(f"{count_helpers(season['helper_count'])} · {state_label}").classes(
                            "text-xs text-gray-500"
                        )
                    if not season["open"]:
                        ui.button(
                            "Otevřít",
                            on_click=lambda sid=season["id"]: s.act(
                                lambda: mutations.open_season(s.workspace, sid), replaced=True
                            ),
                        ).props("flat dense no-caps")
                    with ui.button(icon="more_vert").props("flat dense round"):
                        with ui.menu():
                            ui.menu_item("Přejmenovat", on_click=lambda se=season: self._rename(se))
                            # Delete is never offered on the open Season.
                            if not season["open"]:
                                ui.menu_item("Smazat", on_click=lambda se=season: self._delete(se))

    async def _rename(self, season: dict) -> None:
        label = await dialogs.ask_text(
            "Přejmenovat ročník",
            labels.SEASON_LABEL_FIELD,
            value=season["label"],
            hint=labels.SEASON_LABEL_HELP,
            ok_label="Uložit označení",
        )
        if label is None:
            return
        await self.session.act(lambda: mutations.rename_season(self.session.workspace, season["id"], label))

    async def _delete(self, season: dict) -> None:
        if await dialogs.confirm(
            dialogs.ConfirmSpec(
                title="Smazat ročník",
                ok_label="Smazat ročník",
                intro=(
                    f"Smazat **{season['label']}** ({count_helpers(season['helper_count'])})? Nelze vrátit zpět. "
                    "Ztratíte tento ročník jako zdroj pro import štítků a každou osobu, kterou znáte jen z něj; "
                    "smažou se s ním i všechny jeho uložené verze."
                ),
            )
        ):
            await self.session.act(lambda: mutations.delete_season(self.session.workspace, season["id"]))

    # ------------------------------------------------------------------ Versions
    def _versions(self) -> None:
        s = self.session
        ui.label("Verze").classes("text-base font-bold")
        if mutations.get_open_season(s.workspace) is None:
            ui.label("Verze patří k ročníku — nejdřív nahrajte odpovědi, tím se ročník vytvoří.").classes(
                "text-sm text-gray-500"
            )
            return

        async def save() -> None:
            name = (field.value or "").strip()
            if not name:
                return
            if await s.act(lambda: mutations.save_version(s.workspace, name), success=f"Verze „{name}“ uložena."):
                field.value = ""

        with ui.row().classes("w-full items-center no-wrap gap-1"):
            field = ui.input(placeholder="Název verze…").props("dense").classes("grow").mark("version-name")
            field.on("keydown.enter", save)
            ui.button(icon="save", on_click=save).props("flat dense round").tooltip(
                "Uložit aktuální stav jako verzi"
            )

        versions = mutations.list_versions(s.workspace)
        if not versions:
            ui.label("Zatím žádné uložené verze.").classes("text-sm text-gray-500")
            return
        with ui.list().props("dense separator").classes("w-full"):
            for v in versions:
                with ui.item():
                    with ui.item_section():
                        ui.item_label(v["name"])
                        ui.item_label(v["created_at"] or "").props("caption")
                    with ui.item_section().props("side"):
                        with ui.row().classes("gap-0"):
                            ui.button(icon="restore", on_click=lambda ver=v: self._restore(ver)).props(
                                "flat dense round"
                            ).tooltip("Obnovit").mark("restore-version")
                            ui.button(icon="delete", on_click=lambda ver=v: self._delete_version(ver)).props(
                                "flat dense round"
                            ).tooltip("Smazat")

    async def _restore(self, version: dict) -> None:
        if not await dialogs.confirm(
            dialogs.ConfirmSpec(
                title="Obnovit verzi",
                ok_label="Obnovit",
                intro=(
                    f"Obnovit **{version['name']}**? Vše, co ročník obsahuje, se vrátí do stavu té verze: "
                    "propojení osob, odmítnutá spojení, štítky, vynucené skupinky kamarádů a přiřazení (spolu s "
                    "pomocníky, budovami a všemi dalšími úpravami provedenými od té doby). "
                    "Označení ročníku se nevrací."
                ),
            )
        ):
            return
        s = self.session
        try:
            restored = mutations.restore_version(s.workspace, version["slug"])
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative")
            return
        s.workspace_replaced(restored, keep_view=True)
        ui.notify(f"Obnovena verze „{version['name']}“.", type="positive")

    async def _delete_version(self, version: dict) -> None:
        if await dialogs.confirm(
            dialogs.ConfirmSpec(
                title="Smazat verzi",
                ok_label="Smazat",
                intro=f"Smazat uloženou verzi **{version['name']}**? Nelze vrátit zpět.",
            )
        ):
            await self.session.act(lambda: mutations.delete_version(self.session.workspace, version["slug"]))
