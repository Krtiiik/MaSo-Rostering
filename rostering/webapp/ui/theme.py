"""Light / dark appearance. Quasar restyles its own components under
``body.body--dark``; this module covers what the app colours itself: the page
background and the Tailwind utility classes used across the tabs (overridden for
dark mode here, once, rather than at every use). The roster grid has its own
variables in ``grid.render.CSS``.

The choice (follow the system, light, dark) is kept per browser in
``localStorage``; with nothing stored the page follows the system.
"""
from __future__ import annotations

from nicegui import ui

STORAGE_KEY = "rostering-theme"

# Modes in the order the header button cycles through them: value of
# ``ui.dark_mode`` (None = follow the system), icon, tooltip.
MODES: dict[str, tuple[bool | None, str, str]] = {
    "auto": (None, "brightness_auto", "Vzhled: podle systému"),
    "light": (False, "light_mode", "Vzhled: světlý"),
    "dark": (True, "dark_mode", "Vzhled: tmavý"),
}

CSS = """
body { background: #f7f7f9; }
body.body--dark { background: #121212; }
.nicegui-content { padding: 0; }
.body--dark .bg-white { background-color: #1d1d1d !important; }
.body--dark .text-black { color: #fff !important; }
.body--dark .text-gray-400 { color: #8a8d93 !important; }
.body--dark .text-gray-500, .body--dark .text-grey-6 { color: #a3a6ad !important; }
.body--dark .text-gray-600, .body--dark .text-grey-7 { color: #b4b7bd !important; }
.body--dark .bg-green-50 { background-color: #1c3324 !important; }
.body--dark .bg-amber-50 { background-color: #3a2f12 !important; }
.body--dark .bg-blue-50 { background-color: #1b2c40 !important; }
.body--dark .text-orange-700, .body--dark .text-orange-800 { color: #ffb066 !important; }
"""


class ThemeToggle:
    """The header button: system → light → dark → system. Call :meth:`restore`
    once the browser is connected to apply what this browser chose earlier."""

    def __init__(self) -> None:
        self._dark = ui.dark_mode(None)
        self._mode = "auto"
        self.button = (
            ui.button(icon=MODES[self._mode][1], on_click=self._next)
            .props("flat round")
            .mark("theme-toggle")
        )
        with self.button:
            self._tooltip = ui.tooltip(MODES[self._mode][2])

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        self._mode = mode
        value, icon, tip = MODES[mode]
        self._dark.value = value
        self.button.props(f"icon={icon}")
        self._tooltip.text = tip

    async def restore(self) -> None:
        stored = await ui.run_javascript(f"localStorage.getItem({STORAGE_KEY!r})")
        if stored in MODES:
            self.set_mode(stored)

    def _next(self) -> None:
        names = list(MODES)
        self.set_mode(names[(names.index(self._mode) + 1) % len(names)])
        ui.run_javascript(f"localStorage.setItem({STORAGE_KEY!r}, {self._mode!r})")
