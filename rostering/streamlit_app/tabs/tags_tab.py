"""Tab 3: the Season's Tags — the tag tree, an edit form, and who carries each
Tag (Helpers and Organizers alike). A person's own Tags are also picked in their
popup in the People tab (``person_dialog``)."""
from __future__ import annotations

import streamlit as st

from rostering import tags as tag_tree
from rostering.domain import Role
from rostering.czech import count_helpers, plural
from rostering.streamlit_app import fix_focus, labels, mutations, session, tag_pills
from rostering.streamlit_app.tabs import tag_import_ui

# Session-state keys: the Tag being edited (a Tag id, or _NEW for the create
# form), the Tag whose delete awaits confirmation, and a counter that gives the
# "Others" picker fresh (empty) widgets after each add.
_SELECTED = "_tags_selected"
_PENDING_DELETE = "_tags_pending_delete"
_OTHERS_NONCE = "_tags_others_nonce"
_FLASH = "_tags_flash"
_NEW = "new"
_NO_PARENT = None


def focus_tag(tag_id: int) -> None:
    """Preselect a Tag in this tab (for a hand-off from another tab, applied on
    the next run)."""
    st.session_state[_SELECTED] = tag_id
    st.session_state.pop(_PENDING_DELETE, None)


def render() -> None:
    st.header(labels.TAB_TAGS)
    workspace = session.get_workspace()
    if mutations.get_open_season(workspace) is None:
        st.info("Než přidáte štítky, otevřete ročník (nebo nahráním odpovědí nějaký vytvořte).")
        return
    state = session.get_state()
    message = st.session_state.pop(_FLASH, None)
    if message:
        st.success(message)
    st.caption(
        "Štítek označuje pomocníky; může odvozovat jeden nadřazený štítek, takže každý, kdo ho nese, nese i "
        "ten nadřazený (a jeho nadřazené), počítáno průběžně. Štítky patří k tomuto ročníku."
    )

    # A "Go fix" from a Broken rule: says what to fix here, for as long as it is
    # still broken (the Tag itself was preselected by the hand-off).
    fix = fix_focus.render_callout(state, "tags")

    tag_import_ui.render_summary("tags")
    tag_import_ui.render_promotion_auto()
    import_col, promote_col, _ = st.columns([2, 2, 6])
    with import_col:
        tag_import_ui.render_button("tags")
    with promote_col:
        tag_import_ui.render_promotion_button("tags")

    tree_col, edit_col = st.columns([5, 6], gap="large")
    with tree_col:
        _render_tree(state)
    with edit_col:
        selected = st.session_state.get(_SELECTED)
        if selected == _NEW:
            _render_form(state, None)
        elif selected is not None and any(t["id"] == selected for t in state["tags"]):
            tag = next(t for t in state["tags"] if t["id"] == selected)
            _render_form(state, tag)
            _render_delete_panel(state, tag)
            _render_carriers(state, tag, fix.helper_id if fix else None, fix.organizer_id if fix else None)
            _render_others(state, tag)
        else:
            st.session_state.pop(_SELECTED, None)
            st.info("Vyberte štítek, abyste ho upravili nebo viděli, kdo ho nese, nebo vytvořte nový.")


def _apply(action, *args, **kwargs) -> bool:
    """Run one mutation and refresh the session state; show the reason and
    return False if it is refused."""
    try:
        session.set_state(action(session.get_workspace(), *args, **kwargs))
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return False
    return True


def _render_tree(state: dict) -> None:
    tags = [tag_tree.tag_from_dict(t) for t in state["tags"]]
    records = {t["id"]: t for t in state["tags"]}
    counts = mutations.tag_helper_counts(state)
    organizer_counts = mutations.tag_organizer_counts(state)
    if st.button("Nový štítek", icon=":material/add:", type="primary", key="tags_new"):
        st.session_state[_SELECTED] = _NEW
        st.session_state.pop(_PENDING_DELETE, None)
        st.rerun()
    if not tags:
        st.caption("Zatím žádné štítky.")
        return
    selected = st.session_state.get(_SELECTED)
    for tag, depth in tag_tree.tree_order(tags):
        pill_col, count_col, edit_col = st.columns([7, 2, 1], vertical_alignment="center")
        pill = tag_pills.pill_html(tag.name, tag.colour)
        marker = "font-weight:700;" if tag.id == selected else ""
        pill_col.html(f'<div style="margin-left:{depth * 1.5}rem;{marker}">{"↳ " if depth else ""}{pill}</div>')
        count_col.caption(
            count_helpers(counts[tag.id])
            + (
                f" + {organizer_counts[tag.id]} "
                + plural(organizer_counts[tag.id], "organizátor", "organizátoři", "organizátorů")
                if organizer_counts[tag.id]
                else ""
            )
        )
        if edit_col.button(
            "", icon=":material/edit:", type="tertiary", key=f"tags_edit_{tag.id}", help=f"Upravit {records[tag.id]['name']}"
        ):
            st.session_state[_SELECTED] = tag.id
            st.session_state.pop(_PENDING_DELETE, None)
            st.rerun()


def _parent_options(state: dict, tag: dict | None) -> list[int | None]:
    """The Tags that may become ``tag``'s parent: any Tag except itself and
    the ones that imply it."""
    definitions = [tag_tree.tag_from_dict(t) for t in state["tags"]]
    allowed = [
        t.id for t, _ in tag_tree.tree_order(definitions) if tag is None or tag_tree.can_be_parent(definitions, tag["id"], t.id)
    ]
    return [_NO_PARENT, *allowed]


def _render_form(state: dict, tag: dict | None) -> None:
    names = {t["id"]: t["name"] for t in state["tags"]}
    prefix = f"tag_form_{tag['id'] if tag else 'new'}"
    st.subheader("Nový štítek" if tag is None else f"Upravit {tag['name']}")
    if tag is not None and tag.get("origins"):
        st.caption("Importováno z: " + ", ".join(mutations.tag_origin_labels(state, tag["id"])) + ".")
    with st.form(key=prefix):
        name = st.text_input("Název", value=tag["name"] if tag else "", key=f"{prefix}_name")
        colour_col, parent_col = st.columns(2)
        colour = colour_col.color_picker(
            "Barva",
            value=tag["colour"] if tag else tag_tree.PALETTE[len(state["tags"]) % len(tag_tree.PALETTE)],
            key=f"{prefix}_colour",
        )
        options = _parent_options(state, tag)
        current_parent = tag["parent_id"] if tag and tag["parent_id"] in options else _NO_PARENT
        parent_id = parent_col.selectbox(
            "Odvozuje (nadřazený štítek)",
            options=options,
            index=options.index(current_parent),
            format_func=lambda tid: "— žádný —" if tid is None else names[tid],
            key=f"{prefix}_parent",
            help="Každý, kdo má tento štítek, nese i nadřazený štítek a jeho nadřazené.",
        )
        note = st.text_area("Poznámka", value=tag["note"] if tag else "", key=f"{prefix}_note")
        constraints = _constraint_pickers(state, tag, prefix)
        submitted = st.form_submit_button("Vytvořit štítek" if tag is None else "Uložit změny", type="primary")
    if not submitted:
        return
    if tag is None:
        if _apply(mutations.add_tag, name, colour=colour, note=note, parent_id=parent_id, **constraints):
            st.session_state[_SELECTED] = session.get_state()["tags"][-1]["id"]
            st.session_state[_FLASH] = f"Vytvořeno: {name.strip()}."
            st.rerun()
    elif _apply(mutations.update_tag, tag["id"], name=name, colour=colour, note=note, parent_id=parent_id, **constraints):
        st.session_state[_FLASH] = f"Změny uloženy: {name.strip()}."
        st.rerun()


_NOT_IN_SEASON = " — není v tomto ročníku"


def _constraint_pickers(state: dict, tag: dict | None, prefix: str) -> dict[str, list[str]]:
    """The four Building/Role allow- and deny-list pickers of the form, chosen
    from the Season's configuration. An entry the Season no longer has stays
    listed, marked "not in this Season" (it is inert: the solver and the checker
    ignore it), so saving the form does not silently drop it."""
    entries = mutations.tag_constraint_entries(state, tag["id"]) if tag else {}
    buildings = [b["name"] for b in state["config"]]
    roles = [role.name for role in Role]
    st.caption(
        "Kam smějí pomocníci s tímto štítkem. Seznam povolených je omezuje jen na něj (štítek bez něj nic "
        "nezužuje); seznam zakázaných vždy vyhrává. Nastavení, po kterém by pomocník neměl žádnou povolenou "
        "budovu ani roli, se odmítne."
    )
    picked: dict[str, list[str]] = {}
    for column, (field, label, axis_options) in zip(
        st.columns(2) + st.columns(2),
        [
            ("building_allow", "Povolit jen budovy", buildings),
            ("building_deny", "Zakázat budovy", buildings),
            ("role_allow", "Povolit jen role", roles),
            ("role_deny", "Zakázat role", roles),
        ],
    ):
        current = entries.get(field, [])
        inert = {e["name"] for e in current if not e["in_season"]}
        options = [*axis_options, *(e["name"] for e in current if e["name"] not in axis_options)]

        def show(value: str, field=field, inert=inert) -> str:
            text = Role[value].value if field.startswith("role") else value
            return text + (_NOT_IN_SEASON if value in inert else "")

        picked[field] = column.multiselect(
            label,
            options=options,
            default=[e["name"] for e in current],
            format_func=show,
            key=f"{prefix}_{field}",
            placeholder="Žádné" if options else "Nejdřív nastavte budovu",
        )
    return picked


def _delete_lines(state: dict, tag: dict) -> list[str]:
    impact = mutations.tag_delete_impact(state, tag["id"])
    parent = next((t["name"] for t in state["tags"] if t["id"] == tag["parent_id"]), None)
    lines = []
    if impact["helpers"]:
        lines.append(f"Odebráno pomocníkům ({len(impact['helpers'])}): " + ", ".join(impact["helpers"]))
    if impact["organizers"]:
        lines.append(f"Odebráno organizátorům ({len(impact['organizers'])}): " + ", ".join(impact["organizers"]))
    if impact["children"]:
        lines.append(
            "Podřízené štítky " + ", ".join(impact["children"]) + (f" se přesunou pod {parent}" if parent else " se stanou štítky nejvyšší úrovně")
        )
    return lines


def _render_delete_panel(state: dict, tag: dict) -> None:
    with st.expander("Smazat tento štítek"):
        if st.session_state.get(_PENDING_DELETE) == tag["id"]:
            st.warning(f"Smazáním štítku **{tag['name']}** se změní:")
            for line in _delete_lines(state, tag):
                st.write(f"- {line}")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Smazat štítek", type="primary", key=f"tag_delete_confirm_{tag['id']}"):
                if _apply(mutations.delete_tag, tag["id"], confirmed=True):
                    st.session_state.pop(_PENDING_DELETE, None)
                    st.session_state.pop(_SELECTED, None)
                    st.session_state[_FLASH] = f"Smazáno: {tag['name']}."
                    st.rerun()
            if cancel_col.button("Zrušit", key=f"tag_delete_cancel_{tag['id']}"):
                st.session_state.pop(_PENDING_DELETE, None)
                st.rerun()
            return
        st.caption("Štítek, který někdo nese přímo nebo který má podřízené štítky, se před smazáním zeptá.")
        if st.button("Smazat tento štítek", key=f"tag_delete_{tag['id']}"):
            try:
                session.set_state(mutations.delete_tag(session.get_workspace(), tag["id"]))
            except mutations.ConfirmationRequired:
                st.session_state[_PENDING_DELETE] = tag["id"]
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            st.session_state.pop(_SELECTED, None)
            st.session_state[_FLASH] = f"Smazáno: {tag['name']}."
            st.rerun()


def _render_carriers(
    state: dict, tag: dict, fixing_helper_id: int | None = None, fixing_organizer_id: int | None = None
) -> None:
    carriers = mutations.tag_carriers(state, tag["id"])
    organizer_carriers = mutations.tag_organizer_carriers(state, tag["id"])
    names = {t["id"]: t["name"] for t in state["tags"]}
    st.subheader(f"Mají tento štítek ({len(carriers) + len(organizer_carriers)})")
    if not carriers and not organizer_carriers:
        st.caption("Tento štítek zatím nikdo nenese.")
    for carrier in carriers:
        name_col, action_col = st.columns([5, 3], vertical_alignment="center")
        name_col.write(("⚠ " if carrier["helper_id"] == fixing_helper_id else "") + carrier["name"])
        if carrier["via"] is None:
            if action_col.button(
                "Odebrat", icon=":material/close:", type="tertiary", key=f"tag_remove_{tag['id']}_{carrier['helper_id']}"
            ) and _apply(mutations.remove_tag_from_helper, tag["id"], carrier["helper_id"]):
                st.rerun()
        else:
            action_col.caption(f"přes {names[carrier['via']]}")
    for carrier in organizer_carriers:
        name_col, action_col = st.columns([5, 3], vertical_alignment="center")
        name_col.write(("⚠ " if carrier["organizer_id"] == fixing_organizer_id else "") + carrier["name"] + " (organizátor)")
        if carrier["via"] is None:
            if action_col.button(
                "Odebrat",
                icon=":material/close:",
                type="tertiary",
                key=f"tag_remove_{tag['id']}_organizer_{carrier['organizer_id']}",
            ) and _apply(mutations.remove_tag_from_organizer, tag["id"], carrier["organizer_id"]):
                st.rerun()
        else:
            action_col.caption(f"přes {names[carrier['via']]}")


def _render_others(state: dict, tag: dict) -> None:
    carrier_ids = {c["helper_id"] for c in mutations.tag_carriers(state, tag["id"])}
    organizer_carrier_ids = {c["organizer_id"] for c in mutations.tag_organizer_carriers(state, tag["id"])}
    # Options are "h<id>" (a Helper) or "o<id>" (an Organizer).
    others = {f"h{h['id']}": h["name"] for h in state["helpers"] if h["id"] not in carrier_ids}
    others.update(
        {f"o{o['id']}": f"{o['name']} (organizátor)" for o in state["organizers"] if o["id"] not in organizer_carrier_ids}
    )
    st.subheader("Přidat štítek dalším lidem")
    if not others:
        st.caption("Tento štítek už nese každý pomocník i organizátor.")
        return
    nonce = st.session_state.get(_OTHERS_NONCE, 0)
    pick_key = f"tag_others_pick_{tag['id']}_{nonce}"
    options = sorted(others, key=lambda hid: others[hid].lower())
    picked = st.multiselect(
        "Pomocníci k přidání", options=options, format_func=lambda hid: others[hid], key=pick_key, placeholder="Vyberte pomocníky"
    )
    if st.button(
        f"Přidat ({len(picked)}) ke štítku {tag['name']}", type="primary", disabled=not picked, key=f"tag_others_add_{tag['id']}"
    ) and _apply(
        mutations.add_tag_to_helpers,
        tag["id"],
        [int(key[1:]) for key in picked if key[0] == "h"],
        [int(key[1:]) for key in picked if key[0] == "o"],
    ):
        st.session_state[_OTHERS_NONCE] = nonce + 1
        st.rerun()
