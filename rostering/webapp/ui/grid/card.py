"""The details card a click on a Helper's chip opens: Building preference, Role
ratings as stars, friend requests coloured like the grid's highlights (green:
same Room, red: not, purple: asked for by someone else), Tags, the Forced
friends groups that bind them and, for a placed Helper, Lock/Unlock. "Upravit"
opens the same person sheet as a click on their row in the People tab. It sits
next to the click, flipped so it stays on screen; another click on the same
chip, Escape, a press elsewhere or starting a drag closes it. One card at a
time."""
from __future__ import annotations

from typing import Callable, Optional

from nicegui import ui

from rostering.webapp.ui import pills
from rostering.webapp.ui.grid import data

CARD_WIDTH = 260
# The real height varies with the content; this estimate only decides whether
# to flip above the cursor.
CARD_HEIGHT_ESTIMATE = 380
CURSOR_OFFSET = 14
VIEWPORT_MARGIN = 8


def card_position(x: float, y: float, width: float, height: float) -> tuple[float, float]:
    """(top, left) anchoring a corner of the card at the click, flipped on either
    axis where it would leave the viewport."""
    left = x + CURSOR_OFFSET
    if left + CARD_WIDTH + VIEWPORT_MARGIN > width:
        left = x - CURSOR_OFFSET - CARD_WIDTH
    top = y + CURSOR_OFFSET
    if top + CARD_HEIGHT_ESTIMATE + VIEWPORT_MARGIN > height:
        top = y - CURSOR_OFFSET - CARD_HEIGHT_ESTIMATE
    return max(VIEWPORT_MARGIN, top), max(VIEWPORT_MARGIN, left)


def _stars(level: int) -> str:
    return "★" * level + "☆" * max(0, 5 - level)


class HelperCard:
    """Keeps which card is open across redraws of the Roster tab: :meth:`attach`
    places it in the page being built and draws it from the current view."""

    def __init__(
        self, on_toggle_lock: Callable[[int, bool], object], on_edit: Callable[[int], object]
    ) -> None:
        self._on_toggle_lock = on_toggle_lock
        self._on_edit = on_edit
        self.helper_id: Optional[int] = None
        self._position: tuple[float, float] = (0, 0)
        self.container: Optional[ui.element] = None

    def attach(self, view: Optional[data.GridView]) -> None:
        self.container = ui.element("div")
        self.show(view)

    def toggle(self, view: data.GridView, args: dict) -> None:
        """Open the card for the clicked chip, or close it on the same one."""
        helper_id = int(args["helper_id"])
        if helper_id == self.helper_id:
            self.close()
            return
        self.helper_id = helper_id
        self._position = card_position(args["x"], args["y"], args["width"], args["height"])
        self.show(view)

    def close(self) -> None:
        self.helper_id = None
        if self.container is not None:
            self.container.clear()

    def show(self, view: Optional[data.GridView]) -> None:
        """(Re)draw the open card from ``view`` (after the grid changed)."""
        if self.container is None:
            return
        self.container.clear()
        if self.helper_id is None or view is None:
            return
        info = data.card_data(view, self.helper_id)
        if info is None:
            self.helper_id = None
            return
        top, left = self._position
        helper_id = self.helper_id
        with self.container:
            with ui.element("div").classes("helper-card").style(f"top:{top}px; left:{left}px"):
                ui.label(info["name"]).classes("font-bold mb-1")
                ui.button("Upravit", icon="edit", on_click=lambda: self._edit(helper_id)).props(
                    "dense outline size=sm"
                ).classes("w-full mb-1").mark("card-edit").tooltip(
                    "Otevře stejný panel osoby jako kliknutí na řádek na záložce Lidé"
                )
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

    def _edit(self, helper_id: int) -> None:
        """Hand over to the person sheet; the card has done its job."""
        self.close()
        self._on_edit(helper_id)
