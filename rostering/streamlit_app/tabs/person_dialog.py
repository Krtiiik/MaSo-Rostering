"""The People tab's popups: one person's details (a Helper or an Organizer) and
the two "add" forms.

A person's popup holds everything there is to edit about them: the fields and the
Can't attend flag, their Tags, for a Helper the matching of the friend names they
wrote, and their Person links. Edits that only change the popup's own content
(Tags, friend names, Can't attend) rerun just the popup and leave it open;
saving, deleting and promoting rerun the page and so close it. Closing it by hand
reruns the page too, so the table behind it is current."""
from __future__ import annotations

import streamlit as st

from rostering.webapp import forced_groups, mutations
from rostering.streamlit_app import session, tag_pills
from rostering.streamlit_app.tabs import helper_forms, person_actions, person_links

# A refused Tag pick's reason, shown once after the rerun, and a counter that
# gives the Tag picker a fresh widget so it shows what is saved again.
_TAGS_ERROR = "_person_tags_error"
_TAGS_NONCE = "_person_tags_nonce"
# The same pair for the Friends tab's two pickers.
_FRIENDS_ERROR = "_person_friends_error"
_FRIENDS_NONCE = "_person_friends_nonce"
_FORCED_ERROR = "_person_forced_error"
_FORCED_NONCE = "_person_forced_nonce"

_DISMISS_LABEL = "✕ Nezúčastní se"
_UNRESOLVED_PLACEHOLDER = "Nepřiřazeno / Nenalezeno / Neznámé"


FRIENDS_TAB = "Kamarádi"


def open_person(kind: str, person_id: int, tab: str | None = None) -> None:
    """Open the popup for a Helper (``kind`` "helper") or an Organizer, on its
    first tab or on the one named ``tab`` (for a Helper, ``FRIENDS_TAB``)."""
    people = session.get_state()["organizers" if kind == "organizer" else "helpers"]
    person = next((p for p in people if p["id"] == person_id), None)
    if person is None:
        return
    body = _organizer_body if kind == "organizer" else _helper_body
    st.dialog(person["name"], width="large", on_dismiss="rerun")(body)(person_id, tab)


def open_add_helper() -> None:
    st.dialog("Přidat pomocníka", width="large")(helper_forms.render_add_form)()


def open_add_organizer() -> None:
    st.dialog("Přidat organizátora")(_add_organizer_body)()


def _find(kind: str, person_id: int) -> dict | None:
    people = session.get_state()["organizers" if kind == "organizer" else "helpers"]
    return next((p for p in people if p["id"] == person_id), None)


def _cant_attend_checkbox(kind: str, person: dict) -> None:
    saved = bool(person.get("cant_attend"))
    flag = st.checkbox(
        "Nemůže se zúčastnit",
        value=saved,
        key=f"person_{kind}_{person['id']}_cant_attend",
        help="Vyřadí ho z řešení i z rozdělení; po odškrtnutí se vrátí při dalším sestavení rozdělení.",
    )
    if flag != saved:
        person_actions.set_cant_attend(kind, person["id"], flag)


def _helper_body(helper_id: int, tab: str | None = None) -> None:
    helper = _find("helper", helper_id)
    if helper is None:
        st.info("Tento pomocník už neexistuje.")
        return
    details, tags, friends, links = st.tabs(
        ["Podrobnosti", "Štítky", FRIENDS_TAB, "Propojení osob"], default=tab
    )
    with details:
        _cant_attend_checkbox("helper", helper)
        helper_forms.render_details(helper)
    with tags:
        _render_tags("helper", helper)
    with friends:
        _render_friends(helper)
    with links:
        person_links.render_helper_links(session.get_workspace(), helper)


def _organizer_body(organizer_id: int, tab: str | None = None) -> None:
    organizer = _find("organizer", organizer_id)
    if organizer is None:
        st.info("Tento organizátor už neexistuje.")
        return
    details, tags = st.tabs(["Podrobnosti", "Štítky"])
    with details:
        _render_organizer_details(organizer)
    with tags:
        _render_tags("organizer", organizer)


def _render_organizer_details(organizer: dict) -> None:
    organizer_id = organizer["id"]
    prefix = f"edit_organizer_{organizer_id}"
    placement = " · ".join(filter(None, [organizer.get("building"), organizer.get("room")])) or "— (bez místa)"
    st.caption(
        f"Zařazení: {placement}. Organizátor je zařazen vedoucím místem, které drží na záložce Rozdělení pomocníků. "
        "Nemůže se zúčastnit vymaže jeho místa; po odškrtnutí se vrátí (místa se neobnoví)."
    )
    _cant_attend_checkbox("organizer", organizer)
    name_col, email_col = st.columns(2)
    name = name_col.text_input("Jméno", value=organizer["name"], key=f"{prefix}_name")
    email = email_col.text_input("E-mail", value=organizer.get("email") or "", key=f"{prefix}_email")
    save_col, delete_col = st.columns(2)
    if save_col.button("Uložit změny", type="primary", key=f"{prefix}_save"):
        try:
            session.set_state(
                mutations.update_organizer(session.get_workspace(), organizer_id, name=name, email=email)
            )
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        person_actions.flash(f"Změny uloženy: {name.strip()}")
        st.rerun()
    if delete_col.button("Smazat organizátora", key=f"{prefix}_delete"):
        person_actions.attempt("organizer", organizer_id, "delete")


def _add_organizer_body() -> None:
    name_col, email_col = st.columns(2)
    name = name_col.text_input("Jméno (povinné)", key="add_organizer_name")
    email = email_col.text_input(
        "E-mail (volitelný)",
        key="add_organizer_email",
        help="E-mailová adresa zaznamenaná v dřívějším ročníku ho propojí s touto osobou.",
    )
    if st.button("Přidat organizátora", type="primary", key="add_organizer_submit"):
        try:
            new_state = mutations.add_organizer(session.get_workspace(), name, email)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(new_state)
        person_actions.flash(f"Přidán organizátor: {new_state['organizers'][-1]['name']}.")
        st.rerun()


def _render_tags(kind: str, person: dict) -> None:
    """The person's direct Tags as a multiselect next to their implied Tags
    (direct pills solid, implied dashed); a pick saves at once."""
    state = session.get_state()
    tags = {t["id"]: t for t in state["tags"]}
    if not tags:
        st.caption("V tomto ročníku zatím nejsou žádné štítky. Vytvořte je na záložce Štítky.")
        return
    refused = st.session_state.pop(_TAGS_ERROR, None)
    if refused:
        st.error(refused)
    is_organizer = kind == "organizer"
    tags_of = mutations.organizer_tags if is_organizer else mutations.helper_tags
    set_tags = mutations.set_organizer_tags if is_organizer else mutations.set_helper_tags
    nonce = st.session_state.get(_TAGS_NONCE, 0)
    direct = tags_of(state, person["id"])["direct"]
    picked = st.multiselect(
        "Štítky (přímé)",
        options=list(tags),
        default=direct,
        format_func=lambda tid: tags[tid]["name"],
        # The saved Tags are part of the key, so the picker starts afresh from
        # them after any other edit instead of keeping a stale selection; the
        # nonce does the same after a refused pick.
        key=f"{kind}_tags_{person['id']}_{'-'.join(map(str, direct))}_{nonce}",
        placeholder="Žádné štítky",
    )
    if set(picked) != set(direct):
        try:
            session.set_state(set_tags(session.get_workspace(), person["id"], picked))
        except mutations.RosteringError as exc:
            # Refused (say, it would leave them no allowed Building): show why
            # and put the picker back to what is saved.
            st.session_state[_TAGS_ERROR] = str(exc)
            st.session_state[_TAGS_NONCE] = nonce + 1
        person_actions.rerun_popup()
    own = tags_of(state, person["id"])
    st.html(
        tag_pills.pills_html(
            (tags[t] for t in own["direct"] if t in tags), (tags[t] for t in own["implied"] if t in tags)
        )
        or '<span style="opacity:.5">Žádné štítky</span>'
    )


def _decision_ids(value: object) -> list[int | dict] | None:
    """Normalize a friend_name_decisions value to a list of friend references
    (a Helper id, or ``{"organizer_id": n}``), or None for dismissed. Older
    persisted state stored a single int per name instead of a list."""
    if value is None:
        return None
    if isinstance(value, (int, dict)):
        return [value]
    return list(value)


def _friend_names(helper: dict) -> list[str]:
    decisions = helper.get("friend_name_decisions", {})
    all_names = list(dict.fromkeys(list(helper["unresolved_friend_names"]) + list(decisions)))
    # friend_name_order is fixed at upload time so names keep their original
    # position even after being resolved and dropping out of
    # unresolved_friend_names; fall back to encounter order for state persisted
    # before that field existed.
    order_index = {n: i for i, n in enumerate(helper.get("friend_name_order") or [])}
    return sorted(all_names, key=lambda n: order_index.get(n, len(order_index)))


def _save_decision(helper_id: int, name: str, *args) -> None:
    """Save one friend-name decision and refresh the popup (the error is shown
    instead when it is refused)."""
    try:
        session.set_state(mutations.resolve_friend(session.get_workspace(), helper_id, name, *args))
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    person_actions.rerun_popup()


def _render_friends(helper: dict) -> None:
    """The Friends tab: every survey name on top (when there are any), matched
    or not, in its original order so a decided name stays where it was and can
    be changed, then the Friends picker and, from those friends, the ones forced
    into the same Room."""
    names = _friend_names(helper)
    if names:
        st.markdown("**K přiřazení**")
        st.caption(
            "Jména z dotazníku a komu patří. Jméno může odpovídat více pomocníkům, pokud označuje skupinu lidí."
        )
        _render_name_matchers(helper, names)
        st.markdown("**Přiřazení kamarádi**")
    _render_friend_picker(helper)
    _render_forced_picker(helper)


def _render_friend_picker(helper: dict) -> None:
    """The Helper's friends as a multiselect over every Helper and Organizer; a
    pick saves at once."""
    state = session.get_state()
    saved = helper.get("friends", [])
    nonce = st.session_state.get(_FRIENDS_NONCE, 0)
    refused = st.session_state.pop(_FRIENDS_ERROR, None)
    if refused:
        st.error(refused)
    # The saved friends are part of the key, so the picker starts afresh from
    # them after the name matching changed them; the nonce does the same after
    # a refused pick.
    picked = helper_forms.friends_picker(
        state,
        helper["id"],
        saved,
        key=f"friends_{helper['id']}_{'-'.join(map(str, sorted(map(helper_forms.friend_key, saved))))}_{nonce}",
    )
    if {helper_forms.friend_key(f) for f in picked} == {helper_forms.friend_key(f) for f in saved}:
        return
    try:
        session.set_state(mutations.update_helper(session.get_workspace(), helper["id"], friends=picked))
    except mutations.RosteringError as exc:
        st.session_state[_FRIENDS_ERROR] = str(exc)
        st.session_state[_FRIENDS_NONCE] = nonce + 1
    person_actions.rerun_popup()


def _render_forced_picker(helper: dict) -> None:
    """"Vynucení kamarádi v místnosti": a multiselect over this Helper's own
    friends. Each one picked is a Forced friends group of the two who must share
    a Room (hence a Building); unpicking one dissolves that group. The friend
    wish itself is never touched."""
    requests = [r for r in forced_groups.friend_requests(session.get_state()) if r["helper_id"] == helper["id"]]
    if not requests:
        st.caption("Vynucení kamarádi v místnosti: tento pomocník zatím nemá žádného přiřazeného kamaráda.")
        return
    labels = {helper_forms.friend_key(r["friend"]): r["friend_name"] for r in requests}
    by_key = {helper_forms.friend_key(r["friend"]): r["friend"] for r in requests}
    forced = [helper_forms.friend_key(r["friend"]) for r in requests if r["forced"]]
    nonce = st.session_state.get(_FORCED_NONCE, 0)
    refused = st.session_state.pop(_FORCED_ERROR, None)
    if refused:
        st.error(refused)
    picked = st.multiselect(
        "Vynucení kamarádi v místnosti",
        options=sorted(labels, key=lambda k: labels[k].lower()),
        default=forced,
        format_func=lambda k: labels[k],
        key=f"forced_{helper['id']}_{'-'.join(sorted(forced))}_{nonce}",
        placeholder="Nikdo není vynucen",
        help="Přání být s kamarádem je jen přání. Vynucením vznikne skupinka dvou lidí, kteří musí sdílet "
        "místnost (a tedy i budovu); samotné přání zůstane, jak bylo. Skupinky najdete na záložce „Vynucené skupinky kamarádů“.",
    )
    if set(picked) == set(forced):
        return
    workspace = session.get_workspace()
    try:
        for key in (k for k in picked if k not in forced):
            session.set_state(forced_groups.make_forced(workspace, helper["id"], by_key[key]))
        for key in (k for k in forced if k not in picked):
            session.set_state(forced_groups.unforce(workspace, helper["id"], by_key[key]))
    except mutations.RosteringError as exc:
        st.session_state[_FORCED_ERROR] = str(exc)
        st.session_state[_FORCED_NONCE] = nonce + 1
    person_actions.rerun_popup()


def _render_name_matchers(helper: dict, names: list[str]) -> None:
    """Match the given friend names this Helper wrote on the survey to people. A
    name can match more than one helper if it refers to a group."""
    state = session.get_state()
    decisions = helper.get("friend_name_decisions", {})
    other_helpers = {h["id"]: h["name"] for h in state["helpers"]}
    candidates = sorted((hid for hid in other_helpers if hid != helper["id"]), key=lambda hid: other_helpers[hid].lower())
    helper_id_by_name = {other_helpers[hid]: hid for hid in candidates}
    # An Organizer can be named too; their option carries a suffix so a Helper
    # with the same name stays distinguishable.
    organizer_labels = {o["id"]: f"{o['name']} (organizátor)" for o in state["organizers"]}
    organizer_id_by_label = {label: oid for oid, label in organizer_labels.items()}
    options = [_DISMISS_LABEL, *(other_helpers[hid] for hid in candidates), *organizer_id_by_label]

    for name in names:
        label_col, select_col = st.columns([2, 3])
        label_col.write(f"“{name}”")
        was_decided = name in decisions
        decided_ids = _decision_ids(decisions.get(name))
        if was_decided and decided_ids is None:
            default = [_DISMISS_LABEL]
        elif was_decided:
            default = [
                organizer_labels[ref["organizer_id"]] if isinstance(ref, dict) else other_helpers[ref]
                for ref in decided_ids
                if (ref["organizer_id"] in organizer_labels if isinstance(ref, dict) else ref in other_helpers)
            ]
        else:
            default = []
        choice = select_col.multiselect(
            name,
            options=options,
            default=default,
            placeholder=_UNRESOLVED_PLACEHOLDER,
            accept_new_options=True,
            key=f"match_{helper['id']}_{name}",
            label_visibility="collapsed",
        )
        if not choice:
            continue

        if _DISMISS_LABEL in choice:
            if len(choice) > 1:
                select_col.warning(f"„{_DISMISS_LABEL}“ nelze kombinovat s dalšími shodami.")
                continue
            if was_decided and decided_ids is None:
                continue
            _save_decision(helper["id"], name, "dismiss")
            continue

        resolved_ids = []
        resolved_organizer_ids = []
        unknown = []
        for picked in choice:
            hid = helper_id_by_name.get(picked)
            oid = organizer_id_by_label.get(picked)
            if hid is not None:
                resolved_ids.append(hid)
            elif oid is not None:
                resolved_organizer_ids.append(oid)
            else:
                unknown.append(picked)
        if unknown:
            names_str = ", ".join(f"“{u}”" for u in unknown)
            select_col.warning(f"{names_str}: žádný známý pomocník nesedí.")
            continue
        if was_decided and decided_ids == [*resolved_ids, *({"organizer_id": o} for o in resolved_organizer_ids)]:
            continue
        _save_decision(helper["id"], name, "resolve", resolved_ids, resolved_organizer_ids)
