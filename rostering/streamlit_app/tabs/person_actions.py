"""The actions on a person in the People tab that may throw away hand work
(Can't attend, delete, promote to Organizer) and so need a confirmation, plus the
one-shot flash message after an edit.

``attempt`` runs an action unconfirmed. When the mutation raises
``ConfirmationRequired`` the request is queued and the page reruns; the
confirmation opens from ``show_pending`` on that rerun (dialogs can't nest, so it
can't open from inside the person dialog) and dismissing it drops the request,
changing nothing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import streamlit as st
from streamlit.errors import StreamlitAPIException

from rostering.streamlit_app import mutations, session

_PENDING = "_pending_person_action"
_FLASH = "_person_flash"

_CANT_ATTEND_CAPTION = (
    "Un-ticking Can't attend later does not restore these. The roster is out of date until the next Solve, "
    "and Export is blocked until then."
)


@dataclass(frozen=True)
class _Action:
    title: str
    intro: str  # "{name}" is filled in
    caption: str
    button: str
    run: Callable[..., dict]  # (workspace, person_id, confirmed) -> new state
    done: str | None  # the flash message, "{name}" filled in; None: stay quiet


_ACTIONS: dict[tuple[str, str], _Action] = {
    ("helper", "cant_attend"): _Action(
        "Mark as Can't attend?",
        "Marking **{name}** as Can't attend clears:",
        _CANT_ATTEND_CAPTION,
        "Mark as Can't attend",
        lambda ws, i, c: mutations.set_cant_attend(ws, i, True, confirmed=c),
        None,
    ),
    ("organizer", "cant_attend"): _Action(
        "Mark as Can't attend?",
        "Marking **{name}** as Can't attend clears:",
        _CANT_ATTEND_CAPTION,
        "Mark as Can't attend",
        lambda ws, i, c: mutations.set_organizer_cant_attend(ws, i, True, confirmed=c),
        None,
    ),
    ("helper", "delete"): _Action(
        "Delete this helper?",
        "Deleting **{name}** clears:",
        "This can't be undone. The roster is out of date until the next Solve, and Export is blocked until then.",
        "Delete helper",
        lambda ws, i, c: mutations.delete_helper(ws, i, confirmed=c),
        "Deleted {name}.",
    ),
    ("organizer", "delete"): _Action(
        "Delete this organizer?",
        "Deleting **{name}** clears:",
        "This can't be undone.",
        "Delete organizer",
        lambda ws, i, c: mutations.delete_organizer(ws, i, confirmed=c),
        "Deleted {name}.",
    ),
    ("helper", "promote"): _Action(
        "Promote this helper to Organizer?",
        "Promoting **{name}** to Organizer clears:",
        "They leave the Helper pool and get no solved Role. The roster is out of date until the next Solve, "
        "and Export is blocked until then.",
        "Promote to Organizer",
        lambda ws, i, c: mutations.promote_helper(ws, i, confirmed=c),
        "{name} is now an Organizer.",
    ),
}


def flash(message: str) -> None:
    """Queue a message to show (once) on the next page render."""
    st.session_state[_FLASH] = message


def rerun_popup() -> None:
    """Rerun just the person popup (it is a fragment), so it stays open with
    fresh content. Outside a fragment rerun (the popup's very first render) that
    isn't allowed, and the whole page reruns instead."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def render_flash() -> None:
    message = st.session_state.pop(_FLASH, None)
    if message:
        st.success(message)


def _name_of(state: dict, kind: str, person_id: int) -> str:
    people = state["organizers" if kind == "organizer" else "helpers"]
    return next((p["name"] for p in people if p["id"] == person_id), "this person")


def attempt(kind: str, person_id: int, action: str) -> None:
    """Run ``action`` ("cant_attend", "delete" or "promote") on a person from
    inside the person dialog. Success reruns the page (closing the dialog) for a
    delete or promote and only the dialog for Can't attend; a refusal is shown in
    the dialog."""
    spec = _ACTIONS[(kind, action)]
    name = _name_of(session.get_state(), kind, person_id)
    try:
        new_state = spec.run(session.get_workspace(), person_id, False)
    except mutations.ConfirmationRequired as exc:
        st.session_state[_PENDING] = {"kind": kind, "id": person_id, "action": action, "lines": list(exc.lines)}
        st.rerun()
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    session.set_state(new_state)
    if spec.done:
        flash(spec.done.format(name=name))
        st.rerun()
    rerun_popup()


def set_cant_attend(kind: str, person_id: int, flag: bool) -> None:
    """Flag or un-flag a person from the dialog; flagging may ask first."""
    if flag:
        attempt(kind, person_id, "cant_attend")
        return
    unflag = mutations.set_organizer_cant_attend if kind == "organizer" else mutations.set_cant_attend
    try:
        session.set_state(unflag(session.get_workspace(), person_id, False))
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    rerun_popup()


def _confirm_body(spec: _Action, kind: str, person_id: int, name: str, lines: list[str]) -> None:
    st.write(spec.intro.format(name=name))
    for line in lines:
        st.write(f"- {line}")
    st.caption(spec.caption)
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button(spec.button, type="primary", key="person_action_confirm"):
        try:
            session.set_state(spec.run(session.get_workspace(), person_id, True))
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        if spec.done:
            flash(spec.done.format(name=name))
        st.rerun()
    if cancel_col.button("Cancel", key="person_action_cancel"):
        st.rerun()


def show_pending(state: dict) -> None:
    """Open the confirmation for the action just requested, once."""
    pending = st.session_state.pop(_PENDING, None)
    if pending is None:
        return
    spec = _ACTIONS[(pending["kind"], pending["action"])]
    name = _name_of(state, pending["kind"], pending["id"])
    if name == "this person":  # they are gone already
        return
    st.dialog(spec.title)(_confirm_body)(spec, pending["kind"], pending["id"], name, pending["lines"])
