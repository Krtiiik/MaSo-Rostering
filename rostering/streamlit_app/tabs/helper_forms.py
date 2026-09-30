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


def _optional_inputs(
    state: dict, prefix: str, helper: dict | None, own_id: int | None, *, with_friends: bool = True
) -> dict:
    """The optional Helper fields, prefilled from ``helper`` when editing. The
    friends picker is left out of the edit form (``with_friends`` False): it
    lives on the popup's Kamarádi tab."""
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
    fields = {
        "role_preferences": role_preferences,
        "building_preferences": building_preferences,
        "can_bring_notebook": can_bring_notebook,
        "can_bring_camera": can_bring_camera,
        "tshirt_size": tshirt_size,
    }
    if with_friends:
        fields["friends"] = friends_picker(
            state, own_id, helper.get("friends", []), key=f"{prefix}_friends"
        )
    return fields


def friend_key(ref: int | dict) -> str:
    """A friend reference (a Helper id, or ``{"organizer_id": n}``) as the
    "h<id>" / "o<id>" option key of the friends pickers."""
    return f"o{ref['organizer_id']}" if isinstance(ref, dict) else f"h{ref}"


def _friend_ref(key: str) -> int | dict:
    return {"organizer_id": int(key[1:])} if key[0] == "o" else int(key[1:])


def friend_labels(state: dict, own_id: int | None) -> dict[str, str]:
    """Every person a Helper can name as a friend, by option key: the other
    Helpers and all Organizers (marked as such)."""
    labels = {f"h{h['id']}": h["name"] for h in state["helpers"] if h["id"] != own_id}
    labels.update({f"o{o['id']}": f"{o['name']} (organizátor)" for o in state["organizers"]})
    return labels


def friends_picker(state: dict, own_id: int | None, current: list, *, key: str) -> list[int | dict]:
    """The "Kamarádi" multiselect over every Helper and Organizer, prefilled with
    the ``current`` friend references; returns the picked references."""
    labels = friend_labels(state, own_id)
    picked = st.multiselect(
        "Kamarádi (pomocníci nebo organizátoři, se kterými chce sdílet místnost)",
        options=sorted(labels, key=lambda k: labels[k].lower()),
        default=[k for k in map(friend_key, current) if k in labels],
        format_func=lambda k: labels[k],
        key=key,
    )
    return [_friend_ref(k) for k in picked]


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
    prefix = f"edit_helper_{helper_id}"
    name_col, email_col, phone_col = st.columns(3)
    name = name_col.text_input("Jméno", value=helper["name"], key=f"{prefix}_name")
    email = email_col.text_input("E-mail", value=helper.get("email") or "", key=f"{prefix}_email")
    phone = phone_col.text_input("Telefon / jiný kontakt", value=helper.get("phone") or "", key=f"{prefix}_phone")
    for line in mutations.helper_collisions(state, name, email, exclude_helper_id=helper_id):
        st.warning(line, icon="⚠️")
    optional = _optional_inputs(state, prefix, helper, helper_id, with_friends=False)
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
