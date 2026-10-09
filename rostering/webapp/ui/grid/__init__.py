"""The roster grid: the drag-and-drop {Building, Room} × Role table of the
Roster tab, with the manual roles as extra rows in the same table.

``data`` builds the view model from the Season's state (pure, tested directly),
``render`` turns it into HTML, and :class:`RosterGrid` shows it in the page with
``roster_grid.js`` turning drags, clicks and typed names into events. No build
step: the JavaScript is a plain ES module NiceGUI serves as is."""
from __future__ import annotations

from typing import Optional

from nicegui import ui

from rostering.webapp.ui.grid import data, render


class RosterGrid(ui.element, component="roster_grid.js"):
    """The grid element; ``.on(event, handler)`` for its events (see the module
    docstring of ``roster_grid.js``)."""

    def __init__(self) -> None:
        super().__init__()
        ui.add_css(render.CSS)
        self._props["html"] = ""
        self._props["friends-on"] = False
        self.view: Optional[data.GridView] = None

    def show(self, state: dict, overlays: list[str], filter_tags: list[int], filter_mode: str) -> data.GridView:
        """Draw the grid for ``state`` with the given Overlays and Tag filter."""
        view = data.build_view(state, overlays, filter_tags, filter_mode)
        self.view = view
        self._props["html"] = render.render(view, state.get("cell_merges", {}))
        self._props["friends-on"] = view.friends_on
        self.update()
        return view
