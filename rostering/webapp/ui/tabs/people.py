"""Tab 1: the people of the Season. Upload the raw survey export (which creates
the Season when none is open), then every Organizer and Helper in a searchable,
sortable table. A click on a row opens that person's sheet beside the table
(``person_sheet``), where everything about them is edited; Can't attend is
toggled right in the row. What waits on a decision after an upload (matches to
review, the Tag-import offer, ...) is in the "K vyřízení" panel."""
from __future__ import annotations

from html import escape
from typing import Optional

from nicegui import events, ui

from rostering.domain import UNKNOWN_TSHIRT_SIZE
from rostering.webapp import labels, mutations
from rostering.webapp.ui import dialogs, fix_focus, pills
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.tabs import person_sheet
from rostering.webapp.ui.tabs.person_sheet import PersonSheet

_TAGS_SLOT = r"""
<q-td :props="props"><span v-html="props.value"></span></q-td>
"""
_CANT_ATTEND_SLOT = r"""
<q-td :props="props" @click.stop>
  <q-checkbox dense :model-value="props.value"
    @update:model-value="v => $parent.$emit('cant_attend', {id: props.row.id, value: v})" />
</q-td>
"""
_FRIENDS_SLOT = r"""
<q-td :props="props">
  <q-btn v-if="props.row.unresolved" dense flat no-caps color="warning" :label="props.value"
    @click.stop="$parent.$emit('open_friends', {id: props.row.id})" />
  <span v-else>{{ props.value }}</span>
</q-td>
"""
_NAME_SLOT = r"""
<q-td :props="props">
  <q-icon v-if="props.row.focus" name="play_arrow" color="primary" class="q-mr-xs" />
  <q-icon v-if="props.row.unresolved" name="warning" color="warning" class="q-mr-xs">
    <q-tooltip>Žádosti o kamarády čekají na přiřazení</q-tooltip>
  </q-icon>
  <span :class="props.row.cant_attend ? 'text-grey-6 line-through' : ''">{{ props.value }}</span>
</q-td>
"""


def _col(name: str, label: str, *, sortable: bool = True, align: str = "left") -> dict:
    return {"name": name, "label": label, "field": name, "sortable": sortable, "align": align}


def _tags_html(person_pills: Optional[dict]) -> str:
    if not person_pills:
        return "—"
    return pills.pills_html(person_pills["direct"], person_pills["implied"]) or "—"


class PeopleTab:
    def __init__(self, session: UiSession, sheet: PersonSheet) -> None:
        self.session = session
        self.sheet = sheet

    def render(self) -> None:
        s = self.session
        season = mutations.get_open_season(s.workspace)
        self._upload_card(season is None)
        if season is None:
            return
        state = s.state
        fix = None
        if state["helpers"]:
            self._summary()
            fix = fix_focus.render_callout(s, "helpers")
        self._organizers()
        self._helpers(focus_helper_id=fix.helper_id if fix else None)
        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Pokračovat na štítky", on_click=lambda: s.switch_tab(labels.TAB_TAGS)).props(
                "color=primary icon-right=arrow_forward"
            )

    # ------------------------------------------------------------------ upload
    def _upload_card(self, creates_season: bool) -> None:
        with ui.card().classes("w-full"):
            ui.label("Soubor s odpověďmi").classes("font-bold")
            ui.label(
                "Nahrajte export odpovědí z formuláře (.xlsx)."
                + (" Vytvoří se tím nový ročník." if creates_season else " Opakované nahrání aktualizuje pomocníky.")
            ).classes("text-sm text-gray-600")
            ui.upload(on_upload=self._uploaded, auto_upload=True, max_files=1).props(
                'accept=".xlsx" flat bordered label="Vybrat soubor"'
            ).classes("w-full max-w-[28rem]")

    async def _uploaded(self, e: events.UploadEventArguments) -> None:
        s = self.session
        content = await e.file.read()
        filename = e.file.name
        e.sender.reset()
        if mutations.get_open_season(s.workspace) is None:
            await self._create_season(filename, content)
            return
        notification = ui.notification("Nahrávám a zpracovávám…", spinner=True, timeout=None)
        try:
            await s.act(lambda: mutations.upload_responses(s.workspace, content, filename), success="Odpovědi načteny.")
        finally:
            notification.dismiss()

    async def _create_season(self, filename: str, content: bytes) -> None:
        """No Season is open: uploading creates one. Its label is prefilled from
        the export's submission dates, editable, and required."""
        s = self.session
        try:
            suggested = mutations.suggest_season_label(content, filename)
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative")
            return
        intro = (
            "" if suggested is not None else
            "Data odeslání v tomto exportu se nepodařilo přečíst, zadejte proto označení ročníku sami."
        )
        while True:
            label = await dialogs.ask_text(
                "Nový ročník",
                labels.SEASON_LABEL_FIELD,
                value=suggested or "",
                hint="Rok a jaro (leden až červen) nebo podzim (červenec až prosinec); mezi uloženými ročníky jedinečné.",
                ok_label="Vytvořit ročník a načíst odpovědi",
                intro=intro,
            )
            if label is None:
                return
            try:
                state = mutations.upload_responses(s.workspace, content, filename, label=label)
            except mutations.RosteringError as exc:
                hint = (
                    " Zvolte jiné označení, nebo tento ročník otevřete v postranním panelu a nahrajte do něj "
                    "odpovědi znovu."
                )
                ui.notify(str(exc) + (hint if "již existuje" in str(exc) else ""), type="negative", multi_line=True)
                suggested = label
                continue
            s.workspace_replaced(state)
            ui.notify("Ročník vytvořen a odpovědi načteny.", type="positive")
            return

    def _summary(self) -> None:
        s = self.session
        state = s.state
        unresolved = sum(len(h["unresolved_friend_names"]) for h in state["helpers"])
        returning = mutations.get_returning_helpers(s.workspace)
        msg = f"Načteno pomocníků: **{len(state['helpers'])}**."
        absent = sum(1 for h in state["helpers"] if h.get("cant_attend"))
        if absent:
            msg += f" Nemůže se zúčastnit: **{absent}**."
        if returning:
            msg += f" Vracejících se pomocníků (poznaných podle e-mailu z dřívějšího ročníku): **{len(returning)}**."
        if unresolved:
            msg += (
                " Žádosti o kamarády, které je nutné přiřadit (otevřete pomocníka označeného ⚠): "
                f"**{unresolved}**."
            )
        with ui.row().classes("w-full items-start no-wrap gap-2 rounded bg-green-50 px-3 py-2"):
            ui.icon("check_circle", color="positive")
            ui.markdown(msg)
        warnings = state["ingestion_warnings"]
        if warnings:
            with ui.expansion(f"Upozornění při načítání: {len(warnings)}", icon="info").classes("w-full"):
                for warning in warnings:
                    ui.label(f"• {warning}").classes("text-sm")

    # ------------------------------------------------------------------ tables
    def _table(self, kind: str, rows: list[dict], columns: list[dict], title: str, add, extra=None) -> None:
        with ui.row().classes("w-full items-center mt-4"):
            ui.label(title).classes("text-lg font-bold grow")
            search = ui.input(placeholder="Hledat…").props("dense clearable").classes("w-64")
            ui.button("Přidat", icon="add", on_click=add).props("flat").mark(f"add-{kind}")
            if extra is not None:
                extra()
        table = ui.table(rows=rows, columns=columns, row_key="id", pagination={"rowsPerPage": 0}).classes(
            "w-full"
        ).props("flat bordered dense hide-bottom").mark(f"{kind}-table")
        table.bind_filter_from(search, "value")
        table.add_slot("body-cell-name", _NAME_SLOT)
        table.add_slot("body-cell-tags", _TAGS_SLOT)
        table.add_slot("body-cell-cant_attend", _CANT_ATTEND_SLOT)
        if kind == "helper":
            table.add_slot("body-cell-friends", _FRIENDS_SLOT)
        table.classes("cursor-pointer")
        table.on("rowClick", lambda e: self.sheet.show(kind, e.args[1]["id"]))
        table.on("cant_attend", lambda e: self._cant_attend(kind, e.args["id"], bool(e.args["value"])))
        table.on("open_friends", lambda e: self.sheet.show(kind, e.args["id"], person_sheet.FRIENDS_TAB))
        if not rows:
            ui.label("Zatím nikdo.").classes("text-sm text-gray-500")

    async def _cant_attend(self, kind: str, person_id: int, flag: bool) -> None:
        people = self.session.state["organizers" if kind == "organizer" else "helpers"]
        person = next((p for p in people if p["id"] == person_id), None)
        if person is not None:
            await person_sheet.set_cant_attend(self.session, kind, person, flag)

    def _organizers(self) -> None:
        state = self.session.state
        organizers = sorted(state["organizers"], key=lambda o: o["name"].lower())
        organizer_pills = mutations.organizer_tag_pills(state)
        rows = [
            {
                "id": o["id"],
                "name": o["name"],
                "placement": " · ".join(filter(None, [o.get("building"), o.get("room")])) or "—",
                "cant_attend": bool(o.get("cant_attend")),
                "tags": _tags_html(organizer_pills.get(o["id"])),
            }
            for o in organizers
        ]
        columns = [
            _col("name", "Jméno"),
            _col("placement", "Zařazení"),
            _col("cant_attend", "Nemůže se zúčastnit", align="center"),
            _col("tags", "Štítky", sortable=False),
        ]
        self._table(
            "organizer",
            rows,
            columns,
            f"Organizátoři ({len(organizers)})",
            lambda: person_sheet.add_organizer(self.session),
            extra=lambda: ui.button(
                "Přejít k zařazení", on_click=lambda: self.session.switch_tab(labels.TAB_ROSTER)
            ).props("flat color=primary"),
        )

    def _helpers(self, focus_helper_id: Optional[int]) -> None:
        s = self.session
        state = s.state
        helpers = sorted(state["helpers"], key=lambda h: h["name"].lower())
        returning = mutations.get_returning_helpers(s.workspace)
        helper_pills = mutations.grid_tag_pills(state)
        rows = []
        for h in helpers:
            unresolved = len(h["unresolved_friend_names"])
            rows.append(
                {
                    "id": h["id"],
                    "name": h["name"],
                    "focus": h["id"] == focus_helper_id,
                    "unresolved": unresolved,
                    "returning": ", ".join(returning.get(h["id"], [])) or "—",
                    "buildings": ", ".join(h["building_preferences"]) or "libovolná",
                    "equipment": " ".join(
                        filter(None, ["💻" if h["can_bring_notebook"] else "", "📷" if h["can_bring_camera"] else ""])
                    )
                    or "—",
                    "tshirt": h.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE,
                    "friends": f"k přiřazení: {unresolved}"
                    if unresolved
                    else str(mutations.attending_friend_count(state, h)),
                    "cant_attend": bool(h.get("cant_attend")),
                    "tags": _tags_html(helper_pills.get(h["id"])),
                    # Hidden text the search box also matches.
                    "email": escape(h.get("email") or ""),
                }
            )
        columns = [
            _col("name", "Jméno"),
            _col("returning", "Dřívější ročníky"),
            _col("buildings", "Budovy"),
            _col("equipment", "Vybavení", align="center"),
            _col("tshirt", "Tričko", align="center"),
            _col("friends", "Kamarádi", align="center"),
            _col("cant_attend", "Nemůže se zúčastnit", align="center"),
            _col("tags", "Štítky", sortable=False),
        ]
        self._table("helper", rows, columns, f"Pomocníci ({len(helpers)})", lambda: person_sheet.add_helper(s))
        ui.label(
            "Odvozené štítky (které pomocník má jen díky nadřazenému štítku) mají čárkovaný obrys. "
            "Vybavení: 💻 notebook, 📷 fotoaparát."
        ).classes("text-xs text-gray-500")
