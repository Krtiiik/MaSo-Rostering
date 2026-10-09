"""The details card a click on a chip opens. A Helper's: Building preference, Role
ratings as stars, friend requests coloured like the grid's highlights (green:
same Room, red: not, purple: asked for by someone else), Tags, the Forced
friends groups that bind them and, for a placed Helper, Lock/Unlock. An
Organizer's is smaller: where they are placed, their contact details and
T-shirt size, Tags and the Helpers who asked to be with them. "Upravit" opens
the same person sheet as a click on their row in the People tab. It sits next to
the click, flipped so it stays on screen; another click on the same chip,
Escape, a press elsewhere or starting a drag closes it. One card at a time."""
from __future__ import annotations

from typing import Callable, Optional

from nicegui import ui

from rostering.webapp.ui import pills
from rostering.webapp.ui.grid import data

CARD_WIDTH = 260
# The real height varies with the content; this estimate only decides whether
# to flip above the cursor (the flipped card is anchored by its bottom edge).
CARD_HEIGHT_ESTIMATE = 380
CURSOR_OFFSET = 14
VIEWPORT_MARGIN = 8

HELPER = "helper"
ORGANIZER = "organizer"


def card_position(x: float, y: float, width: float, height: float) -> str:
    """CSS placing a corner of the card at the click, flipped on either axis where
    it would leave the viewport. Flipped above, the card is anchored by its bottom
    edge, so it hugs the click whatever its real height is."""
    left = x + CURSOR_OFFSET
    if left + CARD_WIDTH + VIEWPORT_MARGIN > width:
        left = x - CURSOR_OFFSET - CARD_WIDTH
    left = max(VIEWPORT_MARGIN, left)
    if y + CURSOR_OFFSET + CARD_HEIGHT_ESTIMATE + VIEWPORT_MARGIN > height:
        bottom = max(VIEWPORT_MARGIN, height - (y - CURSOR_OFFSET))
        room = height - bottom - VIEWPORT_MARGIN
        return f"bottom:{bottom}px; left:{left}px; max-height:{room}px; overflow-y:auto"
    return f"top:{y + CURSOR_OFFSET}px; left:{left}px"


def _stars(level: int) -> str:
    return "★" * level + "☆" * max(0, 5 - level)


class HelperCard:
    """Keeps which card is open across redraws of the Roster tab: :meth:`attach`
    places it in the page being built and draws it from the current view. The
    open card is a ``(kind, id)``: a Helper's or an Organizer's."""

    def __init__(
        self, on_toggle_lock: Callable[[int, bool], object], on_edit: Callable[[str, int], object]
    ) -> None:
        self._on_toggle_lock = on_toggle_lock
        self._on_edit = on_edit
        self.open: Optional[tuple[str, int]] = None
        self._position = ""
        self.container: Optional[ui.element] = None

    def attach(self, view: Optional[data.GridView]) -> None:
        self.container = ui.element("div")
        self.show(view)

    def toggle(self, view: data.GridView, args: dict) -> None:
        """Open the card for the clicked chip, or close it on the same one."""
        who = (ORGANIZER, int(args["organizer_id"])) if "organizer_id" in args else (HELPER, int(args["helper_id"]))
        if who == self.open:
            self.close()
            return
        self.open = who
        self._position = card_position(args["x"], args["y"], args["width"], args["height"])
        self.show(view)

    def close(self) -> None:
        self.open = None
        if self.container is not None:
            self.container.clear()

    def show(self, view: Optional[data.GridView]) -> None:
        """(Re)draw the open card from ``view`` (after the grid changed)."""
        if self.container is None:
            return
        self.container.clear()
        if self.open is None or view is None:
            return
        kind, person_id = self.open
        info = (data.organizer_card_data if kind == ORGANIZER else data.card_data)(view, person_id)
        if info is None:
            self.open = None
            return
        with self.container:
            with ui.element("div").classes("helper-card").style(self._position):
                ui.label(info["name"]).classes("font-bold mb-1")
                ui.button("Upravit", icon="edit", on_click=lambda: self._edit(kind, person_id)).props(
                    "dense outline size=sm"
                ).classes("w-full mb-1").mark("card-edit").tooltip(
                    "Otevře stejný panel osoby jako kliknutí na řádek na záložce Lidé"
                )
                if kind == ORGANIZER:
                    self._organizer_body(info)
                else:
                    self._helper_body(info, person_id)

    def _organizer_body(self, info: dict) -> None:
        ui.label("Zařazení").classes("helper-card-label mt-2")
        if info["slots"]:
            for line in info["slots"]:
                ui.label(line)
        else:
            ui.label(info["placement"] or "Nezařazen/a").classes("" if info["placement"] else "italic opacity-60")
        for label, value in (("Telefon", info["phone"]), ("E-mail", info["email"]), ("Tričko", info["tshirt_size"])):
            if value:
                ui.label(label).classes("helper-card-label mt-2")
                ui.label(value)
        if info["requested_by"]:
            ui.label("Přání být s ním/ní").classes("helper-card-label mt-2")
            for name in info["requested_by"]:
                ui.label(name).classes("friend-requested-by")
        tags = info["tags"]
        if tags and (tags["direct"] or tags["implied"]):
            ui.label("Štítky").classes("helper-card-label mt-2")
            ui.html(pills.pills_html(tags["direct"], tags["implied"]))

    def _helper_body(self, info: dict, helper_id: int) -> None:
        if info["placed"]:
            ui.button(
                "Odemknout" if info["locked"] else "Zamknout",
                icon="lock_open" if info["locked"] else "lock",
                on_click=lambda: self._on_toggle_lock(helper_id, not info["locked"]),
            ).props("dense outline size=sm").classes("w-full").tooltip(
                "Celé sestavení rozdělení uzamčené přiřazení zachová (přepíná se i ctrl/cmd-kliknutím na "
                "štítek pomocníka)"
            )
        ui.label("Preferované budovy").classes("helper-card-label mt-2")
        ui.label(", ".join(info["building_preferences"]) or "Žádná preference")
        ui.label("Preference rolí").classes("helper-card-label mt-2")
        with ui.grid(columns="1fr auto").classes("w-full gap-x-2 gap-y-0"):
            for label, pref in info["roles"]:
                ui.label(label)
                if pref:
                    ui.label(_stars(pref["level"])).classes("stars").tooltip(pref["label"])
                else:
                    ui.label("nehodnoceno").classes("italic opacity-60")
        if info["shared"] or info["different"] or info["requested_by"]:
            ui.label("Přání být s kamarádem").classes("helper-card-label mt-2")
            for name in info["shared"]:
                ui.label(name).classes("friend-shared")
            for name in info["different"]:
                ui.label(name).classes("friend-different")
            for name in info["requested_by"]:
                ui.label(f"{name} (chce být s ním/ní)").classes("friend-requested-by")
        if info["forced_groups"]:
            ui.label("Vynucené skupinky kamarádů").classes("helper-card-label mt-2")
            for line in info["forced_groups"]:
                ui.label(f"🔗 {line}")
        tags = info["tags"]
        if tags["direct"] or tags["implied"]:
            ui.label("Štítky").classes("helper-card-label mt-2")
            ui.html(pills.pills_html(tags["direct"], tags["implied"]))

    def _edit(self, kind: str, person_id: int) -> None:
        """Hand over to the person sheet; the card has done its job."""
        self.close()
        self._on_edit(kind, person_id)
