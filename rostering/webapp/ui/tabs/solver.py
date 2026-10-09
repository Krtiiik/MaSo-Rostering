"""Tab 5: the solver's parameters — the weights, the Role cost table, the time
limit and how friend requests are scored. Edited as a draft on the session until
saved (Save, or Save & solve), with an "unsaved changes" chip."""
from __future__ import annotations

from typing import Any, Optional

from nicegui import ui

from rostering.persistence.serialize import solver_config_from_dict, solver_config_to_dict
from rostering.solver.model import MAX_ROLE_COST, SolverConfig
from rostering.webapp import mutations
from rostering.webapp.ui import solving
from rostering.webapp.ui.session import UiSession

# The five Preference costs in the order the rows are shown: (RoleCosts field, label).
_PREFERENCE_COST_FIELDS = [
    ("ano", "Ano"),
    ("klidne", "Klidně"),
    ("nevadi", "Nevadí"),
    ("spise_ne", "Spíš ne"),
    ("ne", "Ne"),
]
# Záloha is not a Preference option, so its cost sits outside the rated rows.
_ZALOHA_COST_FIELD = ("zaloha", "Záloha")
_MODES = {
    "pairwise": "Po dvojicích (každé přání se hodnotí zvlášť)",
    "mutual": "Jen vzájemná (oba se musí navzájem uvést)",
}


def _normalized(config: dict) -> dict:
    """Read through the loader, so a config saved before the Role cost table
    existed (or with keys missing) shows the solver defaults filled in."""
    return solver_config_to_dict(solver_config_from_dict(config))


class SolverTab:
    def __init__(self, session: UiSession) -> None:
        self.session = session

    @property
    def draft(self) -> dict:
        view = self.session.view
        if view.solver_draft is None:
            view.solver_draft = _normalized(self.session.state["solver_config"])
        return view.solver_draft

    def render(self) -> None:
        draft = self.draft
        ui.label("Jak rozřazování váží preference budovy, přání kamarádů a preference rolí a jak dlouho smí hledat.")
        weights = draft["weights"]
        with ui.card().classes("w-full max-w-[48rem]"):
            ui.label("Váhy").classes("text-lg font-bold")
            with ui.row().classes("w-full gap-4 no-wrap"):
                self._number(weights, "building_mismatch", "Váha nesplněné preference budovy").classes("grow")
                self._number(weights, "friend_unsatisfied", "Váha nesplněného přání kamaráda").classes("grow")

        with ui.card().classes("w-full max-w-[48rem]"):
            ui.label("Ceny rolí").classes("text-lg font-bold")
            ui.label(
                "Kolik stojí zařazení pomocníka do role podle toho, jak ji ohodnotil (prázdná odpověď se počítá jako "
                "Nevadí; Záloha nemá hodnocení, má proto vlastní cenu). Jednotka škáluje všechny ceny; zvyšte ji, aby "
                f"preference rolí vážily víc než budova a přání kamarádů. Každá cena je 0 až {MAX_ROLE_COST}."
            ).classes("text-sm text-gray-600")
            self._number(weights, "role_cost_unit", "Jednotka cen rolí", minimum=0).classes("w-56").mark("cost-unit")
            role_costs = draft["role_costs"]
            with ui.grid(columns="9rem 6rem 1fr 3rem").classes("w-full items-center gap-x-3 gap-y-1"):
                for position, (field, label) in enumerate(_PREFERENCE_COST_FIELDS):
                    self._cost_row(role_costs, field, label, stars=len(_PREFERENCE_COST_FIELDS) - position)
                self._cost_row(role_costs, *_ZALOHA_COST_FIELD)
            ui.button("Obnovit výchozí ceny rolí", on_click=self._restore_role_cost_defaults).props("flat").mark("restore-costs")

        with ui.card().classes("w-full max-w-[48rem]"):
            ui.label("Hledání a kamarádi").classes("text-lg font-bold")
            self._number(draft, "time_limit_seconds", "Časový limit (sekundy)", minimum=1).classes("w-56").tooltip(
                "Jak dlouho smí sestavování hledat. Skončí-li bez nalezeného rozdělení, zvyšte limit a sestavte znovu."
            )
            friend_scoring = draft["friend_scoring"]
            ui.select(
                _MODES,
                label="Způsob hodnocení kamarádů",
                value=friend_scoring["mode"],
                on_change=lambda e: self._set(friend_scoring, "mode", e.value),
            ).classes("w-[28rem]")
            ui.checkbox(
                "Symetricky (vzájemná dvojice se hodnotí jako jedno přání, ne dvě)",
                value=friend_scoring["symmetric"],
                on_change=lambda e: self._set(friend_scoring, "symmetric", bool(e.value)),
            )
        self._footer()

    # ------------------------------------------------------------------ fields
    def _set(self, target: dict, key: str, value: Any) -> None:
        target[key] = value
        self._unsaved.refresh()

    def _number(self, target: dict, key: str, label: str, minimum: Optional[int] = None) -> ui.number:
        return ui.number(
            label,
            value=int(target.get(key) or 0),
            min=minimum,
            step=1,
            precision=0,
            on_change=lambda e: self._set(target, key, int(e.value or 0)),
        )

    def _cost_row(self, role_costs: dict, field: str, label: str, stars: int = 0) -> None:
        """One cost: its label (and stars, for a Preference), a 0 to
        ``MAX_ROLE_COST`` slider and the value."""
        ui.label(label).classes("font-bold")
        if stars:
            ui.html(
                f'<span style="color:#f59e0b">{"★" * stars}</span>'
                f'<span style="color:#bbb">{"☆" * (len(_PREFERENCE_COST_FIELDS) - stars)}</span>'
            )
        else:
            ui.label("")
        # A cost saved above the slider's range is shown (and saved again) at the top.
        value = min(int(role_costs[field]), MAX_ROLE_COST)
        role_costs[field] = value
        slider = ui.slider(
            min=0, max=MAX_ROLE_COST, step=1, value=value, on_change=lambda e: self._set(role_costs, field, int(e.value))
        ).mark(f"cost-{field}")
        ui.label().bind_text_from(slider, "value", lambda v: str(int(v)))

    def _restore_role_cost_defaults(self) -> None:
        defaults = solver_config_to_dict(SolverConfig())
        draft = self.draft
        draft["weights"]["role_cost_unit"] = defaults["weights"]["role_cost_unit"]
        draft["role_costs"] = dict(defaults["role_costs"])
        self.session.refresh()

    # ------------------------------------------------------------------ footer
    @ui.refreshable_method
    def _unsaved(self) -> None:
        if _normalized(self.draft) != _normalized(self.session.state["solver_config"]):
            ui.chip("Neuložené změny", icon="warning", color="warning").props("outline").mark("unsaved")

    def _footer(self) -> None:
        s = self.session
        with ui.row().classes("sticky bottom-0 w-full items-center gap-2 bg-white border-t py-2 z-10"):
            ui.button("Uložit parametry", on_click=self._save).props("outline")
            solve = ui.button("Uložit a sestavit rozdělení", on_click=self._save_and_solve).props("color=primary")
            if not s.state["helpers"]:
                solve.disable()
                ui.label("Nejdřív nahrajte odpovědi pomocníků.").classes("text-sm text-gray-500")
            self._unsaved()

    def _put(self) -> Optional[dict]:
        try:
            saved = mutations.put_solver_config(self.session.workspace, self.draft)
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return None
        self.session.apply(saved)
        return saved

    def _save(self) -> None:
        if self._put() is not None:
            ui.notify("Parametry rozřazování uloženy.", type="positive")

    async def _save_and_solve(self) -> None:
        if self._put() is not None:
            await solving.solve(self.session, open_roster=True)
