"""Solve, Place new registrants and Clear roster: the confirmations in front of
them and the modal a Solve runs in.

A full Solve replaces every Assignment that isn't locked, so it asks first when
that would throw hand work away and stays silent when nothing would be lost.
Shared by the Roster tab's Solve and the "Save & solve" of the Buildings and
Solver tabs. The solver runs in a worker thread (``run.io_bound``) inside a
persistent "Solving…" dialog the user cannot close, so nothing can be changed
under it; a failure keeps the dialog open with the message and a Close button.
Locks a Solve had to drop (their Room or Building was removed) are announced
once it is done."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from nicegui import run, ui

from rostering.czech import plural
from rostering.webapp import labels, mutations
from rostering.webapp.ui import dialogs
from rostering.webapp.ui.session import UiSession

_log = logging.getLogger(__name__)

SOLVING_TITLE = "Sestavuji rozdělení…"
PLACING_TITLE = "Zařazuji…"


async def run_in_modal(title: str, work: Callable[[], Any]) -> Optional[Any]:
    """Run blocking ``work`` off the event loop under an undismissible dialog.
    Returns its result, or ``None`` after showing the failure."""
    with ui.dialog().props("persistent") as dialog, ui.card().classes("min-w-[22rem] items-center"):
        ui.label(title).classes("text-lg font-bold")
        spinner = ui.spinner(size="lg")
        message = ui.label("Může to chvíli trvat, čekejte prosím.").classes("text-sm text-gray-600")
    dialog.open()
    try:
        result = await run.io_bound(work)
    except mutations.RosteringError as exc:
        error = str(exc)
    except Exception as exc:  # anything else must not leave the modal stuck
        _log.exception("Solve failed")
        error = f"Neočekávaná chyba: {exc}"
    else:
        dialog.close()
        dialog.delete()
        return result
    spinner.delete()
    message.text = error
    message.classes(replace="text-negative")
    with message.parent_slot.parent:
        ui.button("Zavřít", on_click=dialog.close)
    await dialog
    dialog.delete()
    return None


def _announce_dropped_locks(state: dict) -> None:
    for line in state.get("diagnostics", {}).get("dropped_locks") or []:
        ui.notify(line, type="warning", icon="lock_open", multi_line=True, timeout=0, close_button="OK")


async def solve(session: UiSession, *, open_roster: bool = False) -> bool:
    """A full Solve of the saved Season, confirmed first when it would replace
    unlocked Assignments. ``open_roster`` shows the Roster tab afterwards."""
    count = mutations.unlocked_assignments_replaced(session.state)
    if count and not await dialogs.confirm(
        dialogs.ConfirmSpec(
            title="Nahradit neuzamčená přiřazení?",
            ok_label="Sestavit rozdělení",
            intro=plural(
                count,
                "Jedno neuzamčené přiřazení bude nahrazeno.",
                f"{count} neuzamčená přiřazení budou nahrazena.",
                f"{count} neuzamčených přiřazení bude nahrazeno.",
            ),
            danger=False,
        )
    ):
        return False
    solved = await run_in_modal(SOLVING_TITLE, lambda: mutations.solve(session.workspace))
    if solved is None:
        return False
    if open_roster:
        session.active_tab = labels.TAB_ROSTER
    session.apply(solved)
    _announce_dropped_locks(solved)
    return True


async def place_new(session: UiSession) -> None:
    """Place only the unassigned Helpers; everyone placed stays exactly where
    they are, so no confirmation is needed."""
    newcomers = len(mutations.unplaced_helpers(session.state))
    placed = await run_in_modal(PLACING_TITLE, lambda: mutations.place_new_registrants(session.workspace))
    if placed is None:
        return
    session.apply(placed)
    _announce_dropped_locks(placed)
    noun = plural(newcomers, "nového zájemce", "nové zájemce", "nových zájemců")
    ui.notify(f"Zařazeno: {newcomers} {noun}; všichni ostatní zůstali, kde byli.", type="positive")


async def clear_roster(session: UiSession) -> None:
    count = len(session.state["assignments"])
    locked = mutations.locked_count(session.state)
    intro = f"Všechna přiřazení ({count}) budou odstraněna a výsledek řešení se vynuluje."
    if locked:
        intro += f" Včetně uzamčených: {locked}."
    if await dialogs.confirm(
        dialogs.ConfirmSpec(
            title="Vymazat rozdělení pomocníků?",
            ok_label="Vymazat rozdělení",
            intro=intro,
            caption="Pomocníci, štítky a manuální role zůstanou.",
        )
    ):
        await session.act(lambda: mutations.clear_roster(session.workspace))
