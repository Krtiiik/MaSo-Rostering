"""Tab 3: the Season's Tags — the tag tree, an edit form, and who carries each
Tag (Helpers and Organizers alike). A person's own Tags are also picked in their
popup in the People tab (``person_dialog``)."""
from __future__ import annotations

import streamlit as st

from rostering import tags as tag_tree
from rostering.domain import Role
from rostering.streamlit_app import fix_focus, mutations, session, tag_pills
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
    st.header("2. Tags")
    workspace = session.get_workspace()
    if mutations.get_open_season(workspace) is None:
        st.info("Open a Season (or upload responses to create one) before adding Tags.")
        return
    state = session.get_state()
    message = st.session_state.pop(_FLASH, None)
    if message:
        st.success(message)
    st.caption(
        "A Tag labels Helpers; it can imply one parent Tag, so everyone who carries it also carries that "
        "parent (and its parents), computed live. Tags belong to this Season."
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
            st.info("Pick a Tag to edit it or see who carries it, or create a new one.")


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
    if st.button("New tag", icon=":material/add:", type="primary", key="tags_new"):
        st.session_state[_SELECTED] = _NEW
        st.session_state.pop(_PENDING_DELETE, None)
        st.rerun()
    if not tags:
        st.caption("No Tags yet.")
        return
    selected = st.session_state.get(_SELECTED)
    for tag, depth in tag_tree.tree_order(tags):
        pill_col, count_col, edit_col = st.columns([7, 2, 1], vertical_alignment="center")
        pill = tag_pills.pill_html(tag.name, tag.colour)
        marker = "font-weight:700;" if tag.id == selected else ""
        pill_col.html(f'<div style="margin-left:{depth * 1.5}rem;{marker}">{"↳ " if depth else ""}{pill}</div>')
        count_col.caption(
            f"{counts[tag.id]} helper{'s' if counts[tag.id] != 1 else ''}"
            + (f" + {organizer_counts[tag.id]} org." if organizer_counts[tag.id] else "")
        )
        if edit_col.button(
            "", icon=":material/edit:", type="tertiary", key=f"tags_edit_{tag.id}", help=f"Edit {records[tag.id]['name']}"
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
    st.subheader("New tag" if tag is None else f"Edit {tag['name']}")
    if tag is not None and tag.get("origins"):
        st.caption("Imported from " + ", ".join(mutations.tag_origin_labels(state, tag["id"])) + ".")
    with st.form(key=prefix):
        name = st.text_input("Name", value=tag["name"] if tag else "", key=f"{prefix}_name")
        colour_col, parent_col = st.columns(2)
        colour = colour_col.color_picker(
            "Colour",
            value=tag["colour"] if tag else tag_tree.PALETTE[len(state["tags"]) % len(tag_tree.PALETTE)],
            key=f"{prefix}_colour",
        )
        options = _parent_options(state, tag)
        current_parent = tag["parent_id"] if tag and tag["parent_id"] in options else _NO_PARENT
        parent_id = parent_col.selectbox(
            "Implies (parent tag)",
            options=options,
            index=options.index(current_parent),
            format_func=lambda tid: "— none —" if tid is None else names[tid],
            key=f"{prefix}_parent",
            help="Everyone with this Tag also carries the parent Tag and its parents.",
        )
        note = st.text_area("Note", value=tag["note"] if tag else "", key=f"{prefix}_note")
        constraints = _constraint_pickers(state, tag, prefix)
        submitted = st.form_submit_button("Create tag" if tag is None else "Save changes", type="primary")
    if not submitted:
        return
    if tag is None:
        if _apply(mutations.add_tag, name, colour=colour, note=note, parent_id=parent_id, **constraints):
            st.session_state[_SELECTED] = session.get_state()["tags"][-1]["id"]
            st.session_state[_FLASH] = f"Created {name.strip()}."
            st.rerun()
    elif _apply(mutations.update_tag, tag["id"], name=name, colour=colour, note=note, parent_id=parent_id, **constraints):
        st.session_state[_FLASH] = f"Saved changes to {name.strip()}."
        st.rerun()


_NOT_IN_SEASON = " — not in this Season"


def _constraint_pickers(state: dict, tag: dict | None, prefix: str) -> dict[str, list[str]]:
    """The four Building/Role allow- and deny-list pickers of the form, chosen
    from the Season's configuration. An entry the Season no longer has stays
    listed, marked "not in this Season" (it is inert: the solver and the checker
    ignore it), so saving the form does not silently drop it."""
    entries = mutations.tag_constraint_entries(state, tag["id"]) if tag else {}
    buildings = [b["name"] for b in state["config"]]
    roles = [role.name for role in Role]
    st.caption(
        "Where this Tag's Helpers may go. An allow-list limits them to it (a Tag with none does not narrow); "
        "a deny-list always wins. Leaving a Helper with no allowed Building or Role is refused."
    )
    picked: dict[str, list[str]] = {}
    for column, (field, label, axis_options) in zip(
        st.columns(2) + st.columns(2),
        [
            ("building_allow", "Allow only Buildings", buildings),
            ("building_deny", "Deny Buildings", buildings),
            ("role_allow", "Allow only Roles", roles),
            ("role_deny", "Deny Roles", roles),
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
            placeholder="None" if options else "Configure a Building first",
        )
    return picked


def _delete_lines(state: dict, tag: dict) -> list[str]:
    impact = mutations.tag_delete_impact(state, tag["id"])
    parent = next((t["name"] for t in state["tags"] if t["id"] == tag["parent_id"]), None)
    lines = []
    if impact["helpers"]:
        lines.append(f"Removed from {len(impact['helpers'])} helper(s): " + ", ".join(impact["helpers"]))
    if impact["organizers"]:
        lines.append(f"Removed from {len(impact['organizers'])} Organizer(s): " + ", ".join(impact["organizers"]))
    if impact["children"]:
        lines.append(
            "Child tags " + ", ".join(impact["children"]) + (f" move up to {parent}" if parent else " become top-level tags")
        )
    return lines


def _render_delete_panel(state: dict, tag: dict) -> None:
    with st.expander("Delete this tag"):
        if st.session_state.get(_PENDING_DELETE) == tag["id"]:
            st.warning(f"Deleting **{tag['name']}** changes:")
            for line in _delete_lines(state, tag):
                st.write(f"- {line}")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Delete tag", type="primary", key=f"tag_delete_confirm_{tag['id']}"):
                if _apply(mutations.delete_tag, tag["id"], confirmed=True):
                    st.session_state.pop(_PENDING_DELETE, None)
                    st.session_state.pop(_SELECTED, None)
                    st.session_state[_FLASH] = f"Deleted {tag['name']}."
                    st.rerun()
            if cancel_col.button("Cancel", key=f"tag_delete_cancel_{tag['id']}"):
                st.session_state.pop(_PENDING_DELETE, None)
                st.rerun()
            return
        st.caption("A Tag that is carried directly or has child Tags asks first.")
        if st.button("Delete this tag", key=f"tag_delete_{tag['id']}"):
            try:
                session.set_state(mutations.delete_tag(session.get_workspace(), tag["id"]))
            except mutations.ConfirmationRequired:
                st.session_state[_PENDING_DELETE] = tag["id"]
                st.rerun()
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            st.session_state.pop(_SELECTED, None)
            st.session_state[_FLASH] = f"Deleted {tag['name']}."
            st.rerun()


def _render_carriers(
    state: dict, tag: dict, fixing_helper_id: int | None = None, fixing_organizer_id: int | None = None
) -> None:
    carriers = mutations.tag_carriers(state, tag["id"])
    organizer_carriers = mutations.tag_organizer_carriers(state, tag["id"])
    names = {t["id"]: t["name"] for t in state["tags"]}
    st.subheader(f"Has this tag ({len(carriers) + len(organizer_carriers)})")
    if not carriers and not organizer_carriers:
        st.caption("Nobody carries this Tag yet.")
    for carrier in carriers:
        name_col, action_col = st.columns([5, 3], vertical_alignment="center")
        name_col.write(("⚠ " if carrier["helper_id"] == fixing_helper_id else "") + carrier["name"])
        if carrier["via"] is None:
            if action_col.button(
                "Remove", icon=":material/close:", type="tertiary", key=f"tag_remove_{tag['id']}_{carrier['helper_id']}"
            ) and _apply(mutations.remove_tag_from_helper, tag["id"], carrier["helper_id"]):
                st.rerun()
        else:
            action_col.caption(f"via {names[carrier['via']]}")
    for carrier in organizer_carriers:
        name_col, action_col = st.columns([5, 3], vertical_alignment="center")
        name_col.write(("⚠ " if carrier["organizer_id"] == fixing_organizer_id else "") + carrier["name"] + " (Organizer)")
        if carrier["via"] is None:
            if action_col.button(
                "Remove",
                icon=":material/close:",
                type="tertiary",
                key=f"tag_remove_{tag['id']}_organizer_{carrier['organizer_id']}",
            ) and _apply(mutations.remove_tag_from_organizer, tag["id"], carrier["organizer_id"]):
                st.rerun()
        else:
            action_col.caption(f"via {names[carrier['via']]}")


def _render_others(state: dict, tag: dict) -> None:
    carrier_ids = {c["helper_id"] for c in mutations.tag_carriers(state, tag["id"])}
    organizer_carrier_ids = {c["organizer_id"] for c in mutations.tag_organizer_carriers(state, tag["id"])}
    # Options are "h<id>" (a Helper) or "o<id>" (an Organizer).
    others = {f"h{h['id']}": h["name"] for h in state["helpers"] if h["id"] not in carrier_ids}
    others.update(
        {f"o{o['id']}": f"{o['name']} (Organizer)" for o in state["organizers"] if o["id"] not in organizer_carrier_ids}
    )
    st.subheader("Add tag to others")
    if not others:
        st.caption("Every Helper and Organizer already carries this Tag.")
        return
    nonce = st.session_state.get(_OTHERS_NONCE, 0)
    pick_key = f"tag_others_pick_{tag['id']}_{nonce}"
    options = sorted(others, key=lambda hid: others[hid].lower())
    picked = st.multiselect(
        "Helpers to add", options=options, format_func=lambda hid: others[hid], key=pick_key, placeholder="Pick helpers"
    )
    if st.button(
        f"Add {len(picked)} to {tag['name']}", type="primary", disabled=not picked, key=f"tag_others_add_{tag['id']}"
    ) and _apply(
        mutations.add_tag_to_helpers,
        tag["id"],
        [int(key[1:]) for key in picked if key[0] == "h"],
        [int(key[1:]) for key in picked if key[0] == "o"],
    ):
        st.session_state[_OTHERS_NONCE] = nonce + 1
        st.rerun()
