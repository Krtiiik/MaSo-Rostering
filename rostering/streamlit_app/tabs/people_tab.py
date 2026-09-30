"""Tab 1: the people of the Season. Upload the raw survey export, review the
matches it raised, and see every Organizer and Helper in one table-like view;
clicking a name opens that person's popup (``person_dialog``), where everything
about them is edited."""
from __future__ import annotations

import hashlib
from html import escape

import streamlit as st

from rostering.domain import UNKNOWN_TSHIRT_SIZE
from rostering.streamlit_app import fix_focus, mutations, session, tag_pills
from rostering.streamlit_app.tabs import person_actions, person_dialog, person_links, tag_import_ui, upload_summary_ui
# Height in px of one table row; see ``_row_cells``.
_ROW_HEIGHT = 44
# Bumped on every Can't attend tick so the checkboxes start afresh from the saved
# state (a flag that was refused or is still awaiting confirmation must not stay ticked).
_CANT_ATTEND_NONCE = "_people_cant_attend_nonce"


def render() -> None:
    st.header("1. People")
    workspace = session.get_workspace()
    season = mutations.get_open_season(workspace)
    if season is None:
        st.write(
            "Upload the raw Google Forms export (.xlsx) of helper responses. This creates a new Season: "
            "you'll confirm its label first."
        )
    else:
        st.write(
            f"Upload the raw Google Forms export (.xlsx) to load helper responses into Season "
            f"**{season['label']}**. Helpers already in it are refreshed from their latest row (matched by e-mail), "
            "new registrants are added unassigned, and nobody is moved or removed."
        )

    state = session.get_state()
    uploaded = st.file_uploader(
        "Responses file", type=["xlsx"], key=f"responses_file_{st.session_state.get('_uploader_nonce', 0)}"
    )
    if uploaded is not None:
        content = uploaded.getvalue()
        content_hash = hashlib.md5(content).hexdigest()
        if season is None:
            _render_create_season(workspace, uploaded.name, content, content_hash)
        elif st.session_state.get("_last_upload_hash") != content_hash:
            with st.spinner("Uploading and parsing…"):
                try:
                    state = mutations.upload_responses(workspace, content, uploaded.name)
                    session.set_state(state)
                    st.session_state["_last_upload_hash"] = content_hash
                except mutations.RosteringError as exc:
                    st.error(str(exc))
            st.rerun()

    upload_summary_ui.render("upload")

    if season is None:
        return
    person_actions.render_flash()
    person_actions.show_pending(state)

    returning: dict[int, list[str]] = {}
    fix = None
    if state["helpers"]:
        unresolved_count = sum(len(h["unresolved_friend_names"]) for h in state["helpers"])
        returning = mutations.get_returning_helpers(workspace)
        msg = f"**{len(state['helpers'])}** helpers loaded."
        absent_count = sum(1 for h in state["helpers"] if h.get("cant_attend"))
        if absent_count:
            msg += f" **{absent_count}** can't attend."
        if returning:
            msg += f" **{len(returning)}** are Returning helpers (recognized by e-mail from an earlier Season)."
        if unresolved_count:
            msg += f" **{unresolved_count}** friend name(s) still need matching (open a helper marked ⚠)."
        st.success(msg)

        if state["ingestion_warnings"]:
            with st.expander(f"{len(state['ingestion_warnings'])} ingestion warning(s)"):
                for warning in state["ingestion_warnings"]:
                    st.write(f"- {warning}")

        with st.bottom:
            if st.button("Continue to buildings & rooms →", type="primary"):
                session.switch_tab("2. Buildings")
                st.rerun()

        if mutations.stale_reasons(state):
            st.warning(
                "The roster is out of date: "
                + "; ".join(mutations.stale_reasons(state))
                + ". Solve again in the Roster tab; Export is blocked until then.",
                icon="⚠️",
            )
        unplaced = mutations.unplaced_reason(state)
        if unplaced:
            st.warning(unplaced + ". Place them in the Roster tab; Export is blocked until then.", icon="⚠️")
        tag_import_ui.render_banner()
        tag_import_ui.render_summary("banner")
        tag_import_ui.render_promotion_auto()
        tag_import_ui.render_late_link_prompt()
        person_links.render_uncertain_matches(workspace)
        fix = fix_focus.render_callout(state, "helpers")

    _render_organizers(state)
    _render_helpers(state, returning, focus_helper_id=fix.helper_id if fix else None)


def _render_create_season(workspace, filename: str, content: bytes, content_hash: str) -> None:
    """No Season is open: uploading creates one. Its label is prefilled from
    the export's submission dates, editable, and required."""
    try:
        suggested = mutations.suggest_season_label(content, filename)
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    if suggested is None:
        st.warning("The submission dates in this export couldn't be read, so enter the Season label yourself.")
    with st.form(key=f"create_season_form_{content_hash}"):
        label = st.text_input(
            "Season label",
            value=suggested or "",
            placeholder="e.g. 2026-jaro",
            help="A year plus jaro (January to June) or podzim (July to December); unique among stored Seasons.",
        )
        submitted = st.form_submit_button("Create Season and load responses", type="primary")
    if not submitted:
        return
    try:
        with st.spinner("Uploading and parsing…"):
            state = mutations.upload_responses(workspace, content, filename, label=label)
    except mutations.RosteringError as exc:
        hint = " Choose another label, or open that Season in the sidebar to re-upload into it."
        st.error(str(exc) + (hint if "already exists" in str(exc) else ""))
        return
    session.set_state(state)
    st.session_state["_last_upload_hash"] = content_hash
    st.rerun()


def _table_columns(labels: list[str]) -> list:
    """One content-width column per label, created upfront with the header as its
    first cell; the caller then appends each row's cell to its column. A column
    is as wide as its widest cell, so nothing is measured in advance."""
    row = st.container(horizontal=True, wrap=False, gap="medium")
    columns = [row.container(width="content") for _ in labels]
    for column, label in zip(columns, labels):
        column.markdown(f"**{label}**")
    return columns


def _row_cells(columns: list) -> list:
    """The next row's cell in each column. Columns are independent vertical
    stacks, so every cell gets the same fixed height to keep a row's cells level."""
    return [column.container(height=_ROW_HEIGHT, border=False, vertical_alignment="center") for column in columns]


_NOWRAP = "white-space:nowrap;"


def _text(cell, text: str) -> None:
    """A plain-text cell on one line: a cell has a fixed height, so wrapped text
    would scroll vertically instead."""
    cell.html(f'<div style="{_NOWRAP}">{escape(text)}</div>')


def _pills(pills: dict | None) -> str:
    html = tag_pills.pills_html(pills["direct"], pills["implied"]) if pills else ""
    return f'<div style="{_NOWRAP}">{html}</div>' if html else '<span style="opacity:.5">—</span>'  # st.html refuses an empty body


def _cant_attend_cell(cell, kind: str, person: dict) -> None:
    """The row's Can't attend checkbox; a change is saved (flagging may first ask
    for confirmation, see ``person_actions``) and reruns the page."""
    saved = bool(person.get("cant_attend"))
    flag = cell.checkbox(
        f"Can't attend: {person['name']}",
        value=saved,
        key=f"cant_attend_{kind}_{person['id']}_{st.session_state.get(_CANT_ATTEND_NONCE, 0)}",
        label_visibility="collapsed",
    )
    if flag != saved:
        st.session_state[_CANT_ATTEND_NONCE] = st.session_state.get(_CANT_ATTEND_NONCE, 0) + 1
        person_actions.set_cant_attend(kind, person["id"], flag)


def _render_organizers(state: dict) -> None:
    organizers = sorted(state["organizers"], key=lambda o: o["name"].lower())
    st.subheader(f"Organizers ({len(organizers)})")
    pills = mutations.organizer_tag_pills(state)
    with st.container(border=True):
        columns = _table_columns(["Name", "Placement", "Can't attend", "Tags"])
        for organizer in organizers:
            name_cell, placement_cell, absent_cell, tags_cell = _row_cells(columns)
            if name_cell.button(organizer["name"], key=f"open_organizer_{organizer['id']}", type="tertiary"):
                person_dialog.open_person("organizer", organizer["id"])
            _text(placement_cell, " · ".join(filter(None, [organizer.get("building"), organizer.get("room")])) or "—")
            _cant_attend_cell(absent_cell, "organizer", organizer)
            tags_cell.html(_pills(pills.get(organizer["id"])))
        if st.button("＋ Add organizer", key="add_organizer_open"):
            person_dialog.open_add_organizer()


def _render_helpers(state: dict, returning: dict[int, list[str]], focus_helper_id: int | None = None) -> None:
    """The helper table; ``focus_helper_id`` (a "Go fix" target) marks that
    helper's row."""
    helpers = sorted(state["helpers"], key=lambda h: h["name"].lower())
    st.subheader(f"Helpers ({len(helpers)})")
    pills = mutations.grid_tag_pills(state)
    with st.container(border=True):
        columns = _table_columns(
            ["Name", "Earlier Seasons", "Buildings", "Equipment", "T-shirt", "Friends", "Can't attend", "Tags"]
        )
        for helper in helpers:
            name_cell, seasons_cell, buildings_cell, equipment_cell, size_cell, friends_cell, absent_cell, tags_cell = (
                _row_cells(columns)
            )
            unresolved = len(helper["unresolved_friend_names"])
            mark = ("▶ " if helper["id"] == focus_helper_id else "") + ("⚠ " if unresolved else "")
            if name_cell.button(mark + helper["name"], key=f"open_helper_{helper['id']}", type="tertiary"):
                person_dialog.open_person("helper", helper["id"])
            _text(seasons_cell, ", ".join(returning.get(helper["id"], [])) or "—")
            _text(buildings_cell, ", ".join(helper["building_preferences"]) or "any")
            _text(
                equipment_cell,
                " ".join(filter(None, ["💻" if helper["can_bring_notebook"] else "", "📷" if helper["can_bring_camera"] else ""]))
                or "—"
            )
            _text(size_cell, helper.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE)
            _text(friends_cell, f"{unresolved} to match" if unresolved else str(len(helper["friends"])))
            _cant_attend_cell(absent_cell, "helper", helper)
            tags_cell.html(_pills(pills.get(helper["id"])))
        if st.button("＋ Add helper", key="add_helper_open"):
            person_dialog.open_add_helper()
