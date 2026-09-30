"""The confirmation in front of a full Solve, and the note it leaves behind.

A full Solve replaces every Assignment that isn't locked, so it asks first when
that would throw hand work away ("N unlocked Assignments will be replaced") and
stays silent when nothing would be lost (no Assignments yet, or all locked).
Shared by the Roster tab's Solve button and the Buildings tab's "Save &
solve". A Solve that had to drop locks (their Room or Building was removed)
leaves a one-shot note for the Roster tab to show."""
from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from rostering.streamlit_app import mutations

_NOTE_KEY = "_solve_note"


@st.dialog("Replace unlocked Assignments?")
def _confirm(count: int, run: Callable[[], None]) -> None:
    noun = "Assignment" if count == 1 else "Assignments"
    st.write(f"{count} unlocked {noun} will be replaced.")
    cols = st.columns(2)
    if cols[0].button("Solve", type="primary", key="solve_confirm_go"):
        run()
    if cols[1].button("Cancel", key="solve_confirm_cancel"):
        st.rerun()


def request_solve(state: dict[str, Any], run: Callable[[], None]) -> None:
    """Run the Solve ``run`` now, or after the user confirms when it would
    replace unlocked Assignments in ``state``."""
    count = mutations.unlocked_assignments_replaced(state)
    if count:
        _confirm(count, run)
    else:
        run()


@st.dialog("Clear the roster?")
def _confirm_clear(count: int, locked: int, run: Callable[[], None]) -> None:
    noun = "Assignment" if count == 1 else "Assignments"
    st.write(f"All {count} {noun} will be removed and the solver result reset.")
    if locked:
        st.write(f"This includes {locked} locked.")
    st.caption("Helpers, Tags and Manual roles are kept.")
    cols = st.columns(2)
    if cols[0].button("Clear roster", type="primary", key="clear_roster_confirm_go"):
        run()
    if cols[1].button("Cancel", key="clear_roster_confirm_cancel"):
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
