"""Add, edit and delete a Helper by hand (part of the upload tab). A hand-added
Helper is an ordinary Helper, so nothing here marks one as different."""
from __future__ import annotations

import streamlit as st

from rostering.domain import TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE, Preference, Role
from rostering.streamlit_app import mutations, session

_ROLES = [r for r in Role if r != Role.Zaloha]  # Záloha is not a survey Preference
_UNSET = "—"  # no answer: the Role reads as Nevadí
_PREFERENCE_LABELS = {
    Preference.Ano: "Ano",
    Preference.Klidne: "Klidně",
    Preference.Nevadi: "Nevadí",
    Preference.Spise_ne: "Spíš ne",
    Preference.Ne: "Ne",
}
_SIZE_OPTIONS = [*TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE]
# Session-state keys: a counter that gives the add form fresh (empty) widgets
# after each add, the Helper whose delete awaits confirmation, and a message to
# show once after a rerun.
_ADD_NONCE = "_add_helper_nonce"
_PENDING_DELETE = "_pending_delete_helper"
_PENDING_PROMOTE = "_pending_promote_helper"
_FLASH = "_helper_form_flash"


def _preference_inputs(prefix: str, current: dict[str, str]) -> dict[str, str]:
    """One selectbox per survey Role; returns the Preferences that were
    answered (a Role left at the dash has no entry)."""
    by_label = {label: pref.name for pref, label in _PREFERENCE_LABELS.items()}
    label_by_name = {pref.name: label for pref, label in _PREFERENCE_LABELS.items()}
    chosen: dict[str, str] = {}
    columns = st.columns(len(_ROLES))
    for column, role in zip(columns, _ROLES):
        label = column.selectbox(
            role.value,
            options=[_UNSET, *by_label],
            index=([_UNSET, *by_label].index(label_by_name[current[role.name]]) if role.name in current else 0),
            key=f"{prefix}_pref_{role.name}",
        )
        if label != _UNSET:
            chosen[role.name] = by_label[label]
    return chosen


def _optional_inputs(state: dict, prefix: str, helper: dict | None, own_id: int | None) -> dict:
    """The optional Helper fields, prefilled from ``helper`` when editing."""
    helper = helper or {}
    st.caption("Role preferences (left at the dash, a Role counts as Nevadí)")
    role_preferences = _preference_inputs(prefix, helper.get("role_preferences", {}))
    buildings = [b["name"] for b in state["config"]]
    building_preferences = st.multiselect(
        "Acceptable buildings (none picked: any)",
        options=buildings,
        default=[b for b in helper.get("building_preferences", []) if b in buildings],
        key=f"{prefix}_buildings",
    )
    notebook_col, camera_col, size_col = st.columns(3)
    can_bring_notebook = notebook_col.checkbox(
        "Can bring a notebook", value=bool(helper.get("can_bring_notebook")), key=f"{prefix}_notebook"
    )
    can_bring_camera = camera_col.checkbox(
        "Can bring a camera", value=bool(helper.get("can_bring_camera")), key=f"{prefix}_camera"
    )
    tshirt_size = size_col.selectbox(
        "T-shirt size",
        options=_SIZE_OPTIONS,
        index=_SIZE_OPTIONS.index(helper.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE),
        key=f"{prefix}_size",
    )
    # A friend is a Helper or an Organizer: options are "h<id>" / "o<id>" keys.
    names = {f"h{h['id']}": h["name"] for h in state["helpers"] if h["id"] != own_id}
    names.update({f"o{o['id']}": f"{o['name']} (Organizer)" for o in state["organizers"]})
    picked = st.multiselect(
        "Friends (Helpers or Organizers to share a Room with)",
        options=sorted(names, key=lambda key: names[key].lower()),
        default=[
            key
            for key in (
                f"o{f['organizer_id']}" if isinstance(f, dict) else f"h{f}" for f in helper.get("friends", [])
            )
            if key in names
        ],
        format_func=lambda key: names[key],
        key=f"{prefix}_friends",
    )
    friends = [{"organizer_id": int(key[1:])} if key[0] == "o" else int(key[1:]) for key in picked]
    return {
        "role_preferences": role_preferences,
        "building_preferences": building_preferences,
        "can_bring_notebook": can_bring_notebook,
        "can_bring_camera": can_bring_camera,
        "friends": friends,
        "tshirt_size": tshirt_size,
    }


def render_flash() -> None:
    """Show (once) the message left by the last add, edit or delete."""
    message = st.session_state.pop(_FLASH, None)
    if message:
        st.success(message)


def render_add_form(state: dict) -> None:
    """The "Add helper" form: a name and a contact are required, everything
    else optional (blank, like an unanswered survey row)."""
    with st.expander("Add a helper by hand"):
        prefix = f"add_helper_{st.session_state.get(_ADD_NONCE, 0)}"
        name_col, contact_col = st.columns(2)
        name = name_col.text_input("Name (required)", key=f"{prefix}_name")
        contact = contact_col.text_input(
            "Contact (required)",
            key=f"{prefix}_contact",
            help="An e-mail address lets a later survey answer from the same address link to this person; "
            "anything else (a phone number, say) is kept for display and matching falls back to the name.",
        )
        if name.strip() or contact.strip():
            for line in mutations.helper_collisions(state, name, contact):
                st.warning(line, icon="⚠️")
        optional = _optional_inputs(state, prefix, None, None)
        if st.button("Add helper", type="primary", key=f"{prefix}_submit"):
            try:
                new_state = mutations.add_helper(session.get_workspace(), name, contact, **optional)
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            session.set_state(new_state)
            st.session_state[_ADD_NONCE] = st.session_state.get(_ADD_NONCE, 0) + 1
            st.session_state[_FLASH] = f"Added {new_state['helpers'][-1]['name']}."
            st.rerun()


def render_edit_form(state: dict) -> None:
    """Edit any field of a Helper, or delete them."""
    with st.expander("Edit or delete a helper"):
        helpers = {h["id"]: h for h in state["helpers"]}
        helper_id = st.selectbox(
            "Helper",
            options=sorted(helpers, key=lambda hid: helpers[hid]["name"].lower()),
            format_func=lambda hid: helpers[hid]["name"],
            index=None,
            placeholder="Pick a Helper",
            key="edit_helper_pick",
        )
        if helper_id is None:
            return
        helper = helpers[helper_id]
        prefix = f"edit_helper_{helper_id}"
        name_col, email_col, phone_col = st.columns(3)
        name = name_col.text_input("Name", value=helper["name"], key=f"{prefix}_name")
        email = email_col.text_input("E-mail", value=helper.get("email") or "", key=f"{prefix}_email")
        phone = phone_col.text_input("Phone / other contact", value=helper.get("phone") or "", key=f"{prefix}_phone")
        for line in mutations.helper_collisions(state, name, email, exclude_helper_id=helper_id):
            st.warning(line, icon="⚠️")
        optional = _optional_inputs(state, prefix, helper, helper_id)
        save_col, promote_col, delete_col = st.columns(3)
        if save_col.button("Save changes", type="primary", key=f"{prefix}_save"):
            try:
                new_state = mutations.update_helper(
                    session.get_workspace(), helper_id, name=name, email=email, phone=phone, **optional
                )
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            session.set_state(new_state)
            st.session_state[_FLASH] = f"Saved changes to {name.strip()}"
            st.rerun()
        if promote_col.button(
            "Promote to Organizer",
            key=f"{prefix}_promote",
            help="Moves them out of the Helper pool: they keep their name, e-mail, Tags and Person link but "
            "receive no solved Role, and are placed by giving them a leadership slot on the Roster grid.",
        ):
            try:
                session.set_state(mutations.promote_helper(session.get_workspace(), helper_id))
            except mutations.ConfirmationRequired:
                st.session_state[_PENDING_PROMOTE] = helper_id
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            _forget_picked_helper(helper["name"], promoted=True)
            st.rerun()
        if delete_col.button("Delete helper", key=f"{prefix}_delete"):
            try:
                session.set_state(mutations.delete_helper(session.get_workspace(), helper_id))
            except mutations.ConfirmationRequired:
                st.session_state[_PENDING_DELETE] = helper_id
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            _forget_picked_helper(helper["name"])
            st.rerun()


def _forget_picked_helper(name: str, promoted: bool = False) -> None:
    st.session_state.pop("edit_helper_pick", None)
    st.session_state[_FLASH] = f"{name} is now an Organizer." if promoted else f"Deleted {name}."


@st.dialog("Delete this helper?")
def _confirm_delete(helper_id: int, name: str, lines: list[str]) -> None:
    st.write(f"Deleting **{name}** clears:")
    for line in lines:
        st.write(f"- {line}")
    st.caption("This can't be undone. The roster is out of date until the next Solve, and Export is blocked until then.")
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Delete helper", type="primary", key="delete_helper_confirm"):
        try:
            session.set_state(mutations.delete_helper(session.get_workspace(), helper_id, confirmed=True))
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        _forget_picked_helper(name)
        st.rerun()
    if cancel_col.button("Cancel", key="delete_helper_cancel"):
        st.rerun()


@st.dialog("Promote this helper to Organizer?")
def _confirm_promote(helper_id: int, name: str, lines: list[str]) -> None:
    st.write(f"Promoting **{name}** to Organizer clears:")
    for line in lines:
        st.write(f"- {line}")
    st.caption(
        "They leave the Helper pool and get no solved Role. The roster is out of date until the next Solve, "
        "and Export is blocked until then."
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Promote to Organizer", type="primary", key="promote_helper_confirm"):
        try:
            session.set_state(mutations.promote_helper(session.get_workspace(), helper_id, confirmed=True))
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        _forget_picked_helper(name, promoted=True)
        st.rerun()
    if cancel_col.button("Cancel", key="promote_helper_cancel"):
        st.rerun()


def show_pending_promote_confirmation(state: dict) -> None:
    """Open the confirmation for the Helper whose promotion was just requested
    (once: dismissing the dialog drops the request, changing nothing)."""
    helper_id = st.session_state.pop(_PENDING_PROMOTE, None)
    if helper_id is None:
        return
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    lines = mutations.cant_attend_impact(state, helper_id) if helper else []
    if helper is not None and lines:
        _confirm_promote(helper_id, helper["name"], lines)


def show_pending_delete_confirmation(state: dict) -> None:
    """Open the confirmation for the Helper whose delete was just requested
    (once: dismissing the dialog drops the request, changing nothing)."""
    helper_id = st.session_state.pop(_PENDING_DELETE, None)
    if helper_id is None:
        return
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    lines = mutations.cant_attend_impact(state, helper_id) if helper else []
    if helper is not None and lines:
        _confirm_delete(helper_id, helper["name"], lines)
