"""Tab 1: the people of the Season. Upload the raw survey export, review the
matches it raised, and see every Organizer and Helper in one table-like view;
clicking a name opens that person's popup (``person_dialog``), where everything
about them is edited."""
from __future__ import annotations

import hashlib

import streamlit as st

from rostering.domain import UNKNOWN_TSHIRT_SIZE
from rostering.streamlit_app import fix_focus, mutations, session
from rostering.streamlit_app.tabs import person_actions, person_dialog, person_links, tag_import_ui, upload_summary_ui
# Between the padded detail cells of a row (monospace, see ``_line``).
_GAP = "  "
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
            if st.button("Continue to tags →", type="primary"):
                session.switch_tab("2. Tags")
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


def _tag_text(pills: dict | None) -> str:
    """A person's Tags as plain text: direct Tags by name, implied ones in brackets."""
    if not pills:
        return "—"
    names = [tag["name"] for tag in pills["direct"]] + [f"({tag['name']})" for tag in pills["implied"]]
    return " ".join(names) or "—"


def _line(cells: list[str], widths: list[int]) -> str:
    """``cells`` padded to ``widths`` and joined, so the monospace ``st.text`` of every row lines up."""
    return _GAP.join(cell.ljust(width) for cell, width in zip(cells, widths))


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


def _render_table(
    kind: str,
    people: list[dict],
    names: list[str],
    detail_labels: list[str],
    details: list[list[str]],
    tags: list[str],
    add_label: str,
    on_add,
) -> None:
    """One row per person: the name as a button (opens the popup), every other
    column (Tags last) as a single padded ``st.text``, then the Can't attend
    checkbox. Three elements a row, no per-cell containers: the page renders
    (and reruns) in proportion to its element count, which is what made the
    earlier cell-per-container table slow. The columns' ratios follow the
    text lengths, the same for every row, so the rows stay level."""
    labels = [*detail_labels, "Tags"]
    rows = [[*row, tag_text] for row, tag_text in zip(details, tags)]
    widths = [max(len(text) for text in [label, *(row[i] for row in rows)]) for i, label in enumerate(labels)]
    widths[-1] = 0  # the last cell is not padded
    ratios = [
        max(len(text) for text in ["Name", *names]) + 6,
        max(len(text) for text in [_line(labels, widths), *(_line(row, widths) for row in rows)]),
        len("Can't attend") + 2,
    ]
    header = st.columns(ratios, vertical_alignment="center")
    header[0].text("Name")
    header[1].text(_line(labels, widths))
    header[2].text("Can't attend")
    for person, name, row in zip(people, names, rows):
        name_cell, details_cell, absent_cell = st.columns(ratios, vertical_alignment="center")
        if name_cell.button(name, key=f"open_{kind}_{person['id']}", type="tertiary"):
            person_dialog.open_person(kind, person["id"])
        details_cell.text(_line(row, widths))
        _cant_attend_cell(absent_cell, kind, person)
    if st.button(add_label, key=f"add_{kind}_open"):
        on_add()


def _render_organizers(state: dict) -> None:
    organizers = sorted(state["organizers"], key=lambda o: o["name"].lower())
    st.subheader(f"Organizers ({len(organizers)})")
    pills = mutations.organizer_tag_pills(state)
    _render_table(
        "organizer",
        organizers,
        [o["name"] for o in organizers],
        ["Placement"],
        [[" · ".join(filter(None, [o.get("building"), o.get("room")])) or "—"] for o in organizers],
        [_tag_text(pills.get(o["id"])) for o in organizers],
        "＋ Add organizer",
        person_dialog.open_add_organizer,
    )


def _render_helpers(state: dict, returning: dict[int, list[str]], focus_helper_id: int | None = None) -> None:
    """The helper table; ``focus_helper_id`` (a "Go fix" target) marks that
    helper's row."""
    helpers = sorted(state["helpers"], key=lambda h: h["name"].lower())
    st.subheader(f"Helpers ({len(helpers)})")
    st.caption("Tags a helper only has by implication are shown in (brackets).")
    pills = mutations.grid_tag_pills(state)
    names, details = [], []
    for helper in helpers:
        unresolved = len(helper["unresolved_friend_names"])
        names.append(("▶ " if helper["id"] == focus_helper_id else "") + ("⚠ " if unresolved else "") + helper["name"])
        details.append(
            [
                ", ".join(returning.get(helper["id"], [])) or "—",
                ", ".join(helper["building_preferences"]) or "any",
                ", ".join(filter(None, ["notebook" if helper["can_bring_notebook"] else "", "camera" if helper["can_bring_camera"] else ""]))
                or "—",
                helper.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE,
                f"{unresolved} to match" if unresolved else str(len(helper["friends"])),
            ]
        )
    _render_table(
        "helper",
        helpers,
        names,
        ["Earlier Seasons", "Buildings", "Equipment", "T-shirt", "Friends"],
        details,
        [_tag_text(pills.get(h["id"])) for h in helpers],
        "＋ Add helper",
        person_dialog.open_add_helper,
    )
