"""The confirmation in front of a full Solve, the dialog it runs in, and the
note it leaves behind.

A full Solve replaces every Assignment that isn't locked, so it asks first when
that would throw hand work away ("N unlocked Assignments will be replaced") and
stays silent when nothing would be lost (no Assignments yet, or all locked).
Shared by the Roster tab's Solve button and the "Save & solve" of the Buildings
and Solver tabs. A Solve that had to drop locks (their Room or Building was removed)
leaves a one-shot note for the Roster tab to show.

A Solve (or Place new registrants) blocks the script for as long as the solver
runs, and any widget touched meanwhile would queue a rerun that throws the
result off the screen. So the work never runs at the click: ``request_*`` queues
it and reruns, and ``run_pending`` (called once at the end of ``app.py``) runs
it inside an undismissible "Solving…" dialog that only the finished work closes.
The work callables raise ``RosteringError`` on failure; the dialog then shows
the message with a Close button."""
from __future__ import annotations

import logging
from typing import Any, Callable

import streamlit as st

from rostering.czech import plural
from rostering.webapp import labels, mutations
from rostering.streamlit_app import session

_NOTE_KEY = "_solve_note"
_PENDING_KEY = "_solve_pending"
_ERROR_KEY = "_solve_error"

_SOLVING_TITLE = "Sestavuji rozdělení…"
_PLACING_TITLE = "Zařazuji…"

_log = logging.getLogger(__name__)


@st.dialog("Nahradit neuzamčená přiřazení?")
def _confirm(count: int, run: Callable[[], None]) -> None:
    st.write(
        plural(
            count,
            "Jedno neuzamčené přiřazení bude nahrazeno.",
            f"{count} neuzamčená přiřazení budou nahrazena.",
            f"{count} neuzamčených přiřazení bude nahrazeno.",
        )
    )
    cols = st.columns(2)
    if cols[0].button("Sestavit rozdělení", type="primary", key="solve_confirm_go"):
        _queue(_SOLVING_TITLE, run)
    if cols[1].button("Zrušit", key="solve_confirm_cancel"):
        st.rerun()


def request_solve(state: dict[str, Any], run: Callable[[], None]) -> None:
    """Run the Solve ``run`` now, or after the user confirms when it would
    replace unlocked Assignments in ``state``."""
    count = mutations.unlocked_assignments_replaced(state)
    if count:
        _confirm(count, run)
    else:
        _queue(_SOLVING_TITLE, run)


def request_place(run: Callable[[], None]) -> None:
    """Run the Place new registrants ``run`` in the solving dialog (it needs no
    confirmation: nothing placed can be lost)."""
    _queue(_PLACING_TITLE, run)


def run_solve() -> None:
    """A full Solve of the saved Season, stored as the session's state."""
    solved = mutations.solve(session.get_workspace())
    session.set_state(solved)
    remember_dropped_locks(solved)


def solve_and_open_roster() -> None:
    """Run a full Solve on the saved Season, then show the Roster tab. Shared by
    the "Save & solve" buttons of the Buildings and Solver tabs."""
    run_solve()
    session.switch_tab(labels.TAB_ROSTER)


def _queue(title: str, work: Callable[[], None]) -> None:
    """Queue ``work`` for ``run_pending`` and rerun, which also closes a
    confirmation dialog (Streamlit allows one dialog per run)."""
    st.session_state[_PENDING_KEY] = (title, work)
    st.rerun()


def run_pending() -> None:
    """Run the queued Solve, if any, in an undismissible dialog."""
    pending = st.session_state.pop(_PENDING_KEY, None)
    if pending is None:
        return
    title, work = pending
    st.session_state.pop(_ERROR_KEY, None)
    st.dialog(title, dismissible=False)(_run_dialog)(title, work)


def _run_dialog(title: str, work: Callable[[], None]) -> None:
    """The dialog body: the work under a spinner, then a rerun that closes it.
    A failure keeps it open with the message and a Close button, so a failed
    Solve never leaves the page locked. (The Close click reruns only this
    function, hence the message lives in session state.)"""
    if _ERROR_KEY not in st.session_state:
        with st.spinner("Může to chvíli trvat, čekejte prosím."):
            try:
                work()
            except mutations.RosteringError as exc:
                st.session_state[_ERROR_KEY] = str(exc)
            except Exception as exc:  # anything else must not leave the modal stuck
                _log.exception("Solve failed")
                st.session_state[_ERROR_KEY] = f"Neočekávaná chyba: {exc}"
        if _ERROR_KEY not in st.session_state:
            st.rerun()
    st.error(st.session_state[_ERROR_KEY])
    if st.button("Zavřít", key="solve_error_close"):
        st.session_state.pop(_ERROR_KEY, None)
        st.rerun()


@st.dialog("Vymazat rozdělení pomocníků?")
def _confirm_clear(count: int, locked: int, run: Callable[[], None]) -> None:
    st.write(f"Všechna přiřazení ({count}) budou odstraněna a výsledek řešení se vynuluje.")
    if locked:
        st.write(f"Včetně uzamčených: {locked}.")
    st.caption("Pomocníci, štítky a manuální role zůstanou.")
    cols = st.columns(2)
    if cols[0].button("Vymazat rozdělení", type="primary", key="clear_roster_confirm_go"):
        run()
    if cols[1].button("Zrušit", key="clear_roster_confirm_cancel"):
        st.rerun()


def request_clear(state: dict[str, Any], run: Callable[[], None]) -> None:
    """Run the roster clear ``run`` after the user confirms: it discards every
    Assignment, locked ones too."""
    _confirm_clear(len(state["assignments"]), mutations.locked_count(state), run)


def remember_dropped_locks(state: dict[str, Any]) -> None:
    """Queue the "N locks dropped: ..." line(s) of the Solve that produced
    ``state`` for the Roster tab to show once."""
    lines = state.get("diagnostics", {}).get("dropped_locks") or []
    if lines:
        st.session_state[_NOTE_KEY] = list(lines)


def show_dropped_locks() -> None:
    """Show (and forget) the queued dropped-lock note."""
    for line in st.session_state.pop(_NOTE_KEY, []):
        st.warning(line, icon="🔓")
