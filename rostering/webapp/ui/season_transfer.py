"""Export and import of Seasons, from the sidebar's Seasons panel.

Export is a tick-list of the stored Seasons (all ticked) and a switch for the
saved Versions; the file is handed to the browser as a download. Import reads
the chosen .zip in full first and shows each Season of it: a new one is ticked
to be added, an identical one is left alone, and one that meets a stored Season
(the same Season id, or the same label under another id) lists the differences
and must be given a choice — Replace, Keep both (under a new label) or Skip —
before Import is enabled. The mutations do the work (``mutations.export_seasons``,
``preview_import``, ``import_seasons``); this module only asks and reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from nicegui import events, ui

from rostering.czech import count_helpers, plural
from rostering.webapp import labels, mutations
from rostering.webapp.ui import dialogs
from rostering.webapp.ui.session import UiSession

_CHOICES = {"replace": "Nahradit", "keep_both": "Ponechat obě", "skip": "Přeskočit"}
_STATUS_TEXT = {
    "new": "Nový ročník",
    "same_id": "Už v aplikaci je (liší se)",
    "label_clash": "Stejné označení, jiný ročník",
    "identical": "Beze změn",
}


def _send(data: bytes, filename: str) -> None:
    """Hand the file to the browser as a download."""
    ui.download.content(data, filename, "application/zip")


# --------------------------------------------------------------------- export
async def export_dialog(session: UiSession) -> None:
    seasons = mutations.list_seasons(session.workspace)
    if not seasons:
        ui.notify("Zatím nemáte žádný uložený ročník, který by šel exportovat.", type="warning")
        return
    ticked = {season["id"]: True for season in seasons}
    with dialogs.page_dialog(auto_delete=False, client=session.client) as dialog, ui.card().classes(
        "min-w-[24rem] max-w-[40rem]"
    ):
        ui.label("Export ročníků").classes("text-lg font-bold")
        ui.markdown(
            "Vyberte ročníky, které se uloží do jednoho souboru **.zip**. Soubor obsahuje osobní údaje "
            "pomocníků a organizátorů — zacházejte s ním stejně opatrně jako s daty aplikace."
        )
        ok: Optional[ui.button] = None

        def toggled(season_id: str, value: bool) -> None:
            ticked[season_id] = value
            if ok is not None:
                ok.set_enabled(any(ticked.values()))

        for season in seasons:
            ui.checkbox(
                f"{season['label']} · {count_helpers(season['helper_count'])}",
                value=True,
                on_change=lambda e, sid=season["id"]: toggled(sid, e.value),
            ).mark("export-season")
        versions = ui.checkbox("Zahrnout uložené verze", value=True).mark("export-versions")
        ui.label("Bez verzí je soubor menší — hodí se jako výchozí data pro nového kolegu.").classes(
            "text-sm text-gray-600"
        )
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button(dialogs.CANCEL, on_click=lambda: dialog.submit(None)).props("flat")
            ok = ui.button("Exportovat", icon="download", on_click=lambda: dialog.submit(True)).props(
                "color=primary"
            ).mark("export-ok")
    chosen = await dialog
    dialogs.discard(dialog)
    if not chosen:
        return
    ids = [season_id for season_id, on in ticked.items() if on]
    try:
        data = mutations.export_seasons(session.workspace, ids, include_versions=bool(versions.value))
    except mutations.RosteringError as exc:
        ui.notify(str(exc), type="negative", multi_line=True)
        return
    _send(data, f"rostering-export-{datetime.now():%Y-%m-%d}.zip")
    ui.notify(f"Exportováno: {len(ids)} {plural(len(ids), 'ročník', 'ročníky', 'ročníků')}.", type="positive")


# --------------------------------------------------------------------- import
@dataclass
class _Row:
    """The organizer's answer for one Season of the file."""

    season: dict[str, Any]
    take: bool = True  # a new Season: add it
    choice: Optional[str] = None  # a conflicting Season: replace / keep_both / skip
    label: str = ""  # keep_both: the label of the copy
    widgets: dict[str, Any] = field(default_factory=dict)

    @property
    def conflicts(self) -> bool:
        return self.season["status"] in ("same_id", "label_clash")

    def ready(self) -> bool:
        if not self.conflicts:
            return True
        if self.choice is None:
            return False
        return self.choice != "keep_both" or bool(self.label.strip())

    def decision(self) -> dict[str, Any]:
        status = self.season["status"]
        if status == "new":
            return {"action": "add" if self.take else "skip"}
        if status == "identical":
            return {"action": "skip"}
        decision: dict[str, Any] = {"action": self.choice}
        if self.choice == "keep_both":
            decision["label"] = self.label.strip()
        return decision


def decisions_for(rows: list[_Row]) -> dict[str, dict[str, Any]]:
    return {row.season["id"]: row.decision() for row in rows}


async def import_file(session: UiSession, e: events.UploadEventArguments) -> None:
    """The chosen .zip: preview it, ask what to do with each Season, import."""
    content = await e.file.read()
    e.sender.reset()
    try:
        preview = mutations.preview_import(session.workspace, content)
    except mutations.RosteringError as exc:
        ui.notify(str(exc), type="negative", multi_line=True)
        return
    if not preview["seasons"]:
        ui.notify("Soubor neobsahuje žádný ročník.", type="warning")
        return
    decisions = await _ask(session, preview)
    if decisions is None:
        return
    try:
        report = mutations.import_seasons(session.workspace, content, decisions)
    except mutations.RosteringError as exc:
        ui.notify(str(exc), type="negative", multi_line=True)
        return
    if report["open_season_changed"]:
        session.workspace_replaced(mutations.get_state(session.workspace))
    else:
        session.refresh()
    ui.notify(_summary(report), type="positive", multi_line=True)


def _summary(report: dict[str, Any]) -> str:
    parts = []
    for key, text in (
        ("added", "Přidáno"),
        ("replaced", "Nahrazeno"),
        ("kept_both", "Přidáno jako kopie"),
        ("skipped", "Přeskočeno"),
    ):
        if report[key]:
            parts.append(f"{text}: {', '.join(report[key])}.")
    if not parts:
        parts.append("Nic se nezměnilo.")
    if report["backup"]:
        parts.append(f"Záloha dřívějších ročníků: {report['backup']}")
    return " ".join(parts)


async def _ask(session: UiSession, preview: dict[str, Any]) -> Optional[dict[str, dict[str, Any]]]:
    rows = [_Row(season, label=season.get("suggested_label") or "") for season in preview["seasons"]]
    with dialogs.page_dialog(auto_delete=False, client=session.client) as dialog, ui.card().classes(
        "w-[46rem] max-w-full"
    ):
        ui.label("Import ročníků").classes("text-lg font-bold")
        _file_info(preview)
        ok: Optional[ui.button] = None

        def update() -> None:
            if ok is not None:
                ok.set_enabled(all(row.ready() for row in rows))

        with ui.column().classes("w-full gap-2 max-h-[60vh] overflow-auto"):
            for row in rows:
                _draw_row(row, update)
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button(dialogs.CANCEL, on_click=lambda: dialog.submit(None)).props("flat")
            ok = ui.button("Importovat", icon="upload", on_click=lambda: dialog.submit(decisions_for(rows))).props(
                "color=primary"
            ).mark("import-ok")
        update()
    result = await dialog
    dialogs.discard(dialog)
    return result


def _file_info(preview: dict[str, Any]) -> None:
    when = (preview.get("exported_at") or "")[:10]
    version = preview.get("app_version") or "neznámá"
    ui.label(f"Soubor z {when or 'neznámého data'}, verze aplikace {version}.").classes("text-sm text-gray-600")
    if not preview["includes_versions"]:
        ui.label(
            "Soubor neobsahuje uložené verze — verze nahrazovaných ročníků zůstanou, jak jsou."
        ).classes("text-sm text-gray-600")
    if preview["into_empty"]:
        ui.label("Aplikace zatím nemá žádný ročník: otevře se ten, který byl otevřený při exportu.").classes(
            "text-sm text-gray-600"
        )
    else:
        ui.label("Před importem se uloží záloha dosavadních ročníků do složky backups.").classes(
            "text-sm text-gray-600"
        )


def _draw_row(row: _Row, update) -> None:
    season = row.season
    with ui.card().tight().classes("w-full"):
        with ui.column().classes("w-full gap-1 px-3 py-2"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.label(season["label"]).classes("font-bold")
                ui.label(_STATUS_TEXT[season["status"]]).classes("text-xs text-gray-500 grow")
                versions = season["version_count"]
                counts = f"{count_helpers(season['helper_count'])} · {versions} {plural(versions, 'verze', 'verze', 'verzí')}"
                ui.label(counts).classes("text-xs text-gray-500")
            if season["status"] == "new":
                ui.checkbox(
                    "Importovat",
                    value=True,
                    on_change=lambda e: (setattr(row, "take", e.value), update()),
                ).mark("import-take")
            elif season["status"] == "identical":
                ui.label("Stejný jako uložený ročník — přeskočí se.").classes("text-sm text-gray-600")
            else:
                _draw_conflict(row, update)


def _draw_conflict(row: _Row, update) -> None:
    season = row.season
    local = season["local"]
    if season["status"] == "same_id":
        ui.label(f"V aplikaci je tento ročník už pod označením {local['label']}.").classes("text-sm")
    else:
        ui.label(
            f"V aplikaci je jiný ročník se stejným označením {local['label']}."
        ).classes("text-sm")
    for category in season["diff"]:
        lines = labels.diff_category_lines(category)
        ui.label(f"{labels.diff_category_title(category)}: {_tally(category)}").classes("text-sm")
        with ui.expansion("Podrobnosti").props("dense").classes("w-full text-sm"):
            with ui.column().classes("gap-0"):
                for line in lines:
                    ui.label(line).classes("text-xs")
    new_label = ui.input("Nové označení kopie", value=row.label).props("dense").classes("w-60").mark(
        "import-new-label"
    )
    new_label.set_visibility(False)

    def chose(value: Optional[str]) -> None:
        row.choice = value
        new_label.set_visibility(value == "keep_both")
        update()

    def typed(value: str) -> None:
        row.label = value or ""
        update()

    new_label.on_value_change(lambda e: typed(e.value))
    ui.radio(_CHOICES, value=None, on_change=lambda e: chose(e.value)).props(
        f"inline dense data-label={season['label']}"
    ).mark("import-choice")


def _tally(category: dict[str, Any]) -> str:
    parts = []
    if category["added"]:
        parts.append(f"+{len(category['added'])}")
    if category["removed"]:
        parts.append(f"−{len(category['removed'])}")
    if category["changed"]:
        parts.append(f"~{len(category['changed'])}")
    return " ".join(parts)
