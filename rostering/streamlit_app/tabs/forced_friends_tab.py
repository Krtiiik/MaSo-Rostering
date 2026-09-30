"""Tab 4: the Season's Forced friends groups — named hard constraints on people
who must share a Building, Room and/or Role (see ``CONTEXT.md``). One card per
group with an editable name, a people multiselect and the axes, plus its status
badge; groups are applied by the next full Solve (or Place new registrants)."""
from __future__ import annotations

import streamlit as st

from rostering import forced_friends
from rostering.streamlit_app import fix_focus, forced_groups, labels as ui_labels, mutations, session

_FLASH = "_ff_flash"
_FOCUS = "_ff_focus"
_NONCE = "_ff_nonce"  # bumped after a create so the "New group" form starts empty

_AXIS_LABELS = forced_friends.AXIS_LABELS
_MEMBER_STYLE = {
    forced_groups.ACTIVE: "{}",
    forced_groups.CANT_ATTEND: ":orange[{} (nemůže se zúčastnit, neaktivní)]",
    forced_groups.NOT_REGISTERED: ":gray[{} (neregistrován)]",
    forced_groups.UNPLACED: ":orange[{} (nezařazený organizátor, neaktivní)]",
}


def focus_group(group_id: int) -> None:
    """Point this tab at a group (for a hand-off from another tab, applied on
    the next run)."""
    st.session_state[_FOCUS] = group_id


def _apply(action, *args, **kwargs) -> bool:
    """Run one mutation and refresh the session state; show the reason and
    return False if it is refused."""
    try:
        session.set_state(action(session.get_workspace(), *args, **kwargs))
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return False
    return True


def _axes_from_labels(labels: list[str]) -> list[str]:
    by_label = {label: axis for axis, label in _AXIS_LABELS.items()}
    return [by_label[label] for label in labels]


def _axis_picker(key: str, axes: list[str]):
    return st.pills(
        "Musí sdílet",
        options=list(_AXIS_LABELS.values()),
        selection_mode="multi",
        default=[_AXIS_LABELS[a] for a in axes],
        key=key,
        help="Všichni aktivní členové skupinky musí být ve stejné budově, místnosti a/nebo roli. "
        "Zaškrtnutí místnosti zahrnuje i budovu. Organizátor nemá roli, takže nemůže být ve skupince, která sdílí roli.",
    )


def _people_picker(state: dict, key: str, group: dict | None):
    """The people multiselect: everyone registered this Season, plus the
    members of ``group`` who are not (kept, shown as not registered)."""
    labels = {
        o["person_id"]: o["name"] + (" (organizátor)" if o["kind"] == "organizer" else "")
        for o in forced_groups.member_options(state)
    }
    cant_attend = {
        r["person_id"] for r in (*state["helpers"], *state.get("organizers", [])) if r.get("cant_attend")
    }
    for member in group["members"] if group else []:
        labels.setdefault(member["person_id"], f"{member['name']} (neregistrován)")
    for person_id in cant_attend:
        labels[person_id] = f"{labels[person_id]} (nemůže se zúčastnit)"
    return st.multiselect(
        "Lidé",
        options=list(labels),
        default=[m["person_id"] for m in group["members"]] if group else [],
        format_func=labels.__getitem__,
        key=key,
    )


def render() -> None:
    st.header(ui_labels.TAB_FORCED)
    workspace = session.get_workspace()
    if mutations.get_open_season(workspace) is None:
        st.info("Než přidáte vynucené skupinky kamarádů, otevřete ročník (nebo nahráním odpovědí nějaký vytvořte).")
        return
    state = session.get_state()
    message = st.session_state.pop(_FLASH, None)
    if message:
        st.success(message)
    st.caption(
        "Vynucená skupinka kamarádů jsou lidé, kteří musí být ve stejné budově, místnosti a/nebo roli, na rozdíl "
        "od přání být s kamarádem, které je jen přáním. Člověk může být ve více skupinkách. Řešení drží skupinku "
        "pohromadě, kdykoli to jde; skupinka, kterou udržet nejde, se hlásí jako porušené pravidlo. Změna skupinek "
        "po sestavení nikoho nepřesouvá a rozdělení pomocníků je do dalšího sestavení neaktuální."
    )
    fix = fix_focus.render_callout(state, "forced_friends")

    _render_new(state)
    groups = forced_groups.list_groups(state)
    if not groups:
        st.info("Zatím žádné vynucené skupinky kamarádů.")
        return
    # The group a "Go fix" pointed at, for as long as that rule is still broken.
    focused = fix.group_id if fix is not None else None
    for group in groups:
        _render_group(state, group, focused == group["id"])


def _render_new(state: dict) -> None:
    nonce = st.session_state.get(_NONCE, 0)
    with st.expander("Nová skupinka", icon=":material/add:", expanded=not state.get("forced_groups")):
        if not forced_groups.member_options(state):
            st.caption("Nejdřív nahrajte odpovědi: skupinka se skládá z registrovaných lidí.")
            return
        with st.form(key=f"ff_new_{nonce}"):
            name = st.text_input("Název", key=f"ff_new_name_{nonce}")
            people = _people_picker(state, f"ff_new_people_{nonce}", None)
            axes = _axis_picker(f"ff_new_axes_{nonce}", ["room"])
            submitted = st.form_submit_button("Vytvořit skupinku", type="primary")
        if submitted and _apply(forced_groups.add_group, name, people, _axes_from_labels(axes or [])):
            st.session_state[_NONCE] = nonce + 1
            st.session_state[_FLASH] = f"Vytvořeno: {name.strip()}."
            st.rerun()


def _badge(group: dict) -> None:
    """The status badge: active, dormant (with the reason) or violated by the
    roster as it stands (with the live checker's lines)."""
    status = group["status"]
    if status == forced_groups.DORMANT:
        st.badge("Nečinná", icon=":material/pause:", color="orange", help=group["reason"])
    elif status == forced_groups.VIOLATED:
        st.badge("Porušena", icon=":material/warning:", color="red")
    else:
        st.badge("Aktivní", icon=":material/check:", color="green")


def _render_group(state: dict, group: dict, focused: bool) -> None:
    prefix = f"ff_group_{group['id']}"
    with st.container(border=True):
        head, badge_col = st.columns([6, 3], vertical_alignment="center")
        head.subheader(group["name"])
        with badge_col:
            _badge(group)
        if group["status"] == forced_groups.DORMANT:
            st.caption(group["reason"])
        for line in group["violations"]:
            st.caption(f":red[{line}]")
        for badge in group["badges"]:
            st.badge(badge, icon=":material/info:", color="gray")
        st.markdown(
            "  \n".join(_MEMBER_STYLE[m["state"]].format(m["name"] or "?") for m in group["members"])
            or ":gray[Žádní členové]"
        )
        # The editor opens for a group to fix (from a Broken-rule "Go fix") and
        # for one the roster violates, and stays folded away otherwise.
        with st.expander("Upravit skupinku", icon=":material/edit:", expanded=focused or group["status"] == forced_groups.VIOLATED):
            with st.form(key=prefix):
                name = st.text_input("Název", value=group["name"], key=f"{prefix}_name")
                people = _people_picker(state, f"{prefix}_people", group)
                axes = _axis_picker(f"{prefix}_axes", group["axes"])
                save_col, dissolve_col, _ = st.columns([2, 2, 6])
                saved = save_col.form_submit_button("Uložit změny", type="primary")
                dissolved = dissolve_col.form_submit_button("Rozpustit skupinku")
        if saved and _apply(
            forced_groups.update_group,
            group["id"],
            name=name,
            person_ids=people,
            axes=_axes_from_labels(axes or []),
        ):
            st.session_state[_FLASH] = f"Změny uloženy: {name.strip()}."
            st.rerun()
        if dissolved and _apply(forced_groups.dissolve_group, group["id"]):
            st.session_state[_FLASH] = f"Rozpuštěno: {group['name']}."
            st.rerun()
