"""The Helper forms of the People tab's dialogs: add a Helper by hand, and edit
any field of one (with the delete and promote actions). A hand-added Helper is an
ordinary Helper, so nothing here marks one as different."""
from __future__ import annotations

import streamlit as st

from rostering.domain import TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE, Preference, Role
from rostering.streamlit_app import mutations, session
from rostering.streamlit_app.tabs import person_actions

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
# A counter that gives the edit form fresh widgets after the friends were
# changed somewhere else in the dialog (the friend-name matching), so its
# Friends picker shows what is saved instead of a stale selection.
DETAILS_NONCE = "_helper_details_nonce"


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
    st.caption("Preference rolí (role ponechaná na pomlčce se počítá jako Nevadí)")
    role_preferences = _preference_inputs(prefix, helper.get("role_preferences", {}))
    buildings = [b["name"] for b in state["config"]]
    building_preferences = st.multiselect(
        "Přijatelné budovy (nevybráno nic: libovolná)",
        options=buildings,
        default=[b for b in helper.get("building_preferences", []) if b in buildings],
        key=f"{prefix}_buildings",
    )
    notebook_col, camera_col, size_col = st.columns(3)
    can_bring_notebook = notebook_col.checkbox(
        "Může přinést notebook", value=bool(helper.get("can_bring_notebook")), key=f"{prefix}_notebook"
    )
    can_bring_camera = camera_col.checkbox(
        "Může přinést fotoaparát", value=bool(helper.get("can_bring_camera")), key=f"{prefix}_camera"
    )
    tshirt_size = size_col.selectbox(
        "Velikost trička",
        options=_SIZE_OPTIONS,
        index=_SIZE_OPTIONS.index(helper.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE),
        key=f"{prefix}_size",
    )
    # A friend is a Helper or an Organizer: options are "h<id>" / "o<id>" keys.
    names = {f"h{h['id']}": h["name"] for h in state["helpers"] if h["id"] != own_id}
    names.update({f"o{o['id']}": f"{o['name']} (organizátor)" for o in state["organizers"]})
    picked = st.multiselect(
        "Kamarádi (pomocníci nebo organizátoři, se kterými chce sdílet místnost)",
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


def render_add_form() -> None:
    """The "Add helper" form: a name and a contact are required, everything
    else optional (blank, like an unanswered survey row)."""
    state = session.get_state()
    prefix = "add_helper"
    name_col, contact_col = st.columns(2)
    name = name_col.text_input("Jméno (povinné)", key=f"{prefix}_name")
    contact = contact_col.text_input(
        "Kontakt (povinný)",
        key=f"{prefix}_contact",
        help="E-mailová adresa umožní propojit s touto osobou pozdější odpověď ankety ze stejné adresy; "
        "cokoli jiného (třeba telefon) se uchová jen pro zobrazení a párování se vrátí ke jménu.",
    )
    if name.strip() or contact.strip():
        for line in mutations.helper_collisions(state, name, contact):
            st.warning(line, icon="⚠️")
    optional = _optional_inputs(state, prefix, None, None)
    if st.button("Přidat pomocníka", type="primary", key=f"{prefix}_submit"):
        try:
            new_state = mutations.add_helper(session.get_workspace(), name, contact, **optional)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(new_state)
        person_actions.flash(f"Přidán pomocník: {new_state['helpers'][-1]['name']}.")
        st.rerun()


def render_details(helper: dict) -> None:
    """Edit any field of a Helper, or promote or delete them."""
    state = session.get_state()
    helper_id = helper["id"]
    prefix = f"edit_helper_{helper_id}_{st.session_state.get(DETAILS_NONCE, 0)}"
    name_col, email_col, phone_col = st.columns(3)
    name = name_col.text_input("Jméno", value=helper["name"], key=f"{prefix}_name")
    email = email_col.text_input("E-mail", value=helper.get("email") or "", key=f"{prefix}_email")
    phone = phone_col.text_input("Telefon / jiný kontakt", value=helper.get("phone") or "", key=f"{prefix}_phone")
    for line in mutations.helper_collisions(state, name, email, exclude_helper_id=helper_id):
        st.warning(line, icon="⚠️")
    optional = _optional_inputs(state, prefix, helper, helper_id)
    save_col, promote_col, delete_col = st.columns(3)
    if save_col.button("Uložit změny", type="primary", key=f"{prefix}_save"):
        try:
            new_state = mutations.update_helper(
                session.get_workspace(), helper_id, name=name, email=email, phone=phone, **optional
            )
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(new_state)
        person_actions.flash(f"Změny uloženy: {name.strip()}")
        st.rerun()
    if promote_col.button(
        "Povýšit na organizátora",
        key=f"{prefix}_promote",
        help="Vyřadí je z množiny pomocníků: zachovají si jméno, e-mail, štítky i propojení osoby, ale "
        "nedostanou žádnou sestavenou roli; zařadí se tím, že jim v rozdělení přidělíte vedoucí místo.",
    ):
        person_actions.attempt("helper", helper_id, "promote")
    if delete_col.button("Smazat pomocníka", key=f"{prefix}_delete"):
        person_actions.attempt("helper", helper_id, "delete")
