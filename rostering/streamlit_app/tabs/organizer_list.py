"""The Season's Organizers in the Upload tab, under the Helper list: who they are,
where they are placed (by the slot they hold) and the Can't attend checkbox, with
the same confirmation as for a Helper. Organizers are tagged in the Tags tab and
in the "Tag helpers" section above (``helper_tags``)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from rostering.streamlit_app import mutations, session

_NAME_COLUMN = "Organizer"
_PLACEMENT_COLUMN = "Placement"
_CANT_ATTEND_COLUMN = "Can't attend"
# Session-state keys: the Organizer whose Can't attend flag awaits confirmation,
# and a counter that gives the table a fresh (unedited) widget state.
_PENDING = "_pending_organizer_cant_attend"
_NONCE = "_organizers_editor_nonce"


def _placement(organizer: dict) -> str:
    return " · ".join(filter(None, [organizer.get("building"), organizer.get("room")])) or "— (no slot)"


def render(state: dict) -> None:
    organizers = state["organizers"]
    if not organizers:
        return
    _show_pending_confirmation(state)
    st.subheader(f"Organizers ({len(organizers)})")
    st.caption(
        "An Organizer is placed by the leadership slot they hold in the Roster tab. Tick Can't attend to leave one "
        "out of the roster; it clears their slots, and untick brings them back (their slots are not restored)."
    )
    shown = pd.DataFrame(
        [
            {
                _NAME_COLUMN: o["name"],
                _PLACEMENT_COLUMN: _placement(o),
                _CANT_ATTEND_COLUMN: bool(o.get("cant_attend")),
            }
            for o in organizers
        ]
    )
    edited = st.data_editor(
        shown,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=[c for c in shown.columns if c != _CANT_ATTEND_COLUMN],
        column_config={_CANT_ATTEND_COLUMN: st.column_config.CheckboxColumn(_CANT_ATTEND_COLUMN)},
        key=f"organizers_editor_{st.session_state.get(_NONCE, 0)}",
    )
    # Rows keep their original position in the returned frame, so position i is
    # state["organizers"][i].
    changed = False
    for i, cant_attend in edited[_CANT_ATTEND_COLUMN].items():
        organizer = organizers[i]
        if bool(cant_attend) == bool(shown[_CANT_ATTEND_COLUMN][i]):
            continue
        try:
            session.set_state(
                mutations.set_organizer_cant_attend(session.get_workspace(), organizer["id"], bool(cant_attend))
            )
        except mutations.ConfirmationRequired:
            # Flagging would clear their slots: reset the table to what is saved
            # (unticked) and ask first, on the next run.
            st.session_state[_PENDING] = organizer["id"]
            st.session_state[_NONCE] = st.session_state.get(_NONCE, 0) + 1
            st.rerun()
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        changed = True
    if changed:
        st.rerun()


@st.dialog("Mark as Can't attend?")
def _confirm(organizer_id: int, name: str, lines: list[str]) -> None:
    st.write(f"Marking **{name}** as Can't attend clears:")
    for line in lines:
        st.write(f"- {line}")
    st.caption(
        "Un-ticking Can't attend later does not restore these. The roster is out of date until the next Solve, "
        "and Export is blocked until then."
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Mark as Can't attend", type="primary", key="organizer_cant_attend_confirm"):
        try:
            session.set_state(
                mutations.set_organizer_cant_attend(session.get_workspace(), organizer_id, True, confirmed=True)
            )
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        st.rerun()
    if cancel_col.button("Cancel", key="organizer_cant_attend_cancel"):
        st.rerun()


def _show_pending_confirmation(state: dict) -> None:
    """Open the confirmation for the Organizer whose flag was just requested
    (once: dismissing the dialog drops the request, changing nothing)."""
    organizer_id = st.session_state.pop(_PENDING, None)
    if organizer_id is None:
        return
    organizer = next((o for o in state["organizers"] if o["id"] == organizer_id), None)
    lines = mutations.organizer_cant_attend_impact(state, organizer_id) if organizer else []
    if organizer is not None and lines:
        _confirm(organizer_id, organizer["name"], lines)
