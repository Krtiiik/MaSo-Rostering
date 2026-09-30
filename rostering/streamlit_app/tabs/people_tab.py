"""Tab 1: the people of the Season. Upload the raw survey export, review the
matches it raised, and see every Organizer and Helper in one table-like view;
the ⚙️ button on a row opens that person's popup (``person_dialog``), where
everything about them is edited."""
from __future__ import annotations

import hashlib

import streamlit as st

from rostering.domain import UNKNOWN_TSHIRT_SIZE
from rostering.streamlit_app import fix_focus, mutations, session
from rostering.streamlit_app import labels as ui_labels
from rostering.streamlit_app import tag_pills
from rostering.streamlit_app.tabs import person_actions, person_dialog, person_links, tag_import_ui, upload_summary_ui
_OPEN_LABEL = "⚙️"
# Bumped on every Can't attend tick so the checkboxes start afresh from the saved
# state (a flag that was refused or is still awaiting confirmation must not stay ticked).
_CANT_ATTEND_NONCE = "_people_cant_attend_nonce"


def render() -> None:
    st.header(ui_labels.TAB_PEOPLE)
    workspace = session.get_workspace()
    season = mutations.get_open_season(workspace)

    state = session.get_state()
    uploaded = st.file_uploader(
        "Soubor s odpověďmi", type=["xlsx"], key=f"responses_file_{st.session_state.get('_uploader_nonce', 0)}"
    )
    if uploaded is not None:
        content = uploaded.getvalue()
        content_hash = hashlib.md5(content).hexdigest()
        if season is None:
            _render_create_season(workspace, uploaded.name, content, content_hash)
        elif st.session_state.get("_last_upload_hash") != content_hash:
            with st.spinner("Nahrávám a zpracovávám…"):
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
        msg = f"Načteno pomocníků: **{len(state['helpers'])}**."
        absent_count = sum(1 for h in state["helpers"] if h.get("cant_attend"))
        if absent_count:
            msg += f" Nemůže se zúčastnit: **{absent_count}**."
        if returning:
            msg += f" Vracejících se pomocníků (poznaných podle e-mailu z dřívějšího ročníku): **{len(returning)}**."
        if unresolved_count:
            msg += f" Žádosti o kamarády, které je nutné přiřadit (otevřete pomocníka označeného ⚠️): **{unresolved_count}**."
        st.success(msg)

        if state["ingestion_warnings"]:
            with st.expander(f"Upozornění při načítání: {len(state['ingestion_warnings'])}"):
                for warning in state["ingestion_warnings"]:
                    st.write(f"- {warning}")

        with st.bottom:
            if st.button("Pokračovat na štítky →", type="primary"):
                session.switch_tab(ui_labels.TAB_TAGS)
                st.rerun()

        if mutations.stale_reasons(state):
            st.warning(
                "Rozdělení pomocníků je neaktuální: "
                + "; ".join(mutations.stale_reasons(state))
                + ". Sestavte rozdělení znovu na záložce Rozdělení pomocníků; do té doby je export zablokovaný.",
                icon="⚠️",
            )
        unplaced = mutations.unplaced_reason(state)
        if unplaced:
            st.warning(unplaced + ". Zařaďte je na záložce Rozdělení pomocníků; do té doby je export zablokovaný.", icon="⚠️")
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
        st.warning("Data odeslání v tomto exportu se nepodařilo přečíst, zadejte proto označení ročníku sami.")
    with st.form(key=f"create_season_form_{content_hash}"):
        label = st.text_input(
            ui_labels.SEASON_LABEL_FIELD,
            value=suggested or "",
            placeholder="např. 2026-jaro",
            help="Rok a jaro (leden až červen) nebo podzim (červenec až prosinec); mezi uloženými ročníky jedinečné.",
        )
        submitted = st.form_submit_button("Vytvořit ročník a načíst odpovědi", type="primary")
    if not submitted:
        return
    try:
        with st.spinner("Nahrávám a zpracovávám…"):
            state = mutations.upload_responses(workspace, content, filename, label=label)
    except mutations.RosteringError as exc:
        hint = " Zvolte jiné označení, nebo tento ročník otevřete v postranním panelu a nahrajte do něj odpovědi znovu."
        st.error(str(exc) + (hint if "již existuje" in str(exc) else ""))
        return
    session.set_state(state)
    st.session_state["_last_upload_hash"] = content_hash
    st.rerun()


def _tag_width(pills: dict | None) -> int:
    """The width, in characters, a person's Tag pills need (name plus the pill's padding)."""
    if not pills:
        return 1
    return sum(len(tag["name"]) + 3 for tag in [*pills["direct"], *pills["implied"]]) or 1


def _tag_html(pills: dict | None) -> str:
    """A person's Tags as pills: direct Tags solid, implied ones dashed."""
    if not pills:
        return "—"
    return tag_pills.pills_html(pills["direct"], pills["implied"]) or "—"


def _cant_attend_cell(cell, kind: str, person: dict) -> None:
    """The row's Can't attend checkbox; a change is saved (flagging may first ask
    for confirmation, see ``person_actions``) and reruns the page."""
    saved = bool(person.get("cant_attend"))
    flag = cell.checkbox(
        f"Nemůže se zúčastnit: {person['name']}",
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
    tags: list[dict | None],
    add_label: str,
    on_add,
    detail_actions: list[dict[int, str]] | None = None,
) -> None:
    """One ``st.columns`` row per person with one column per field: the name as
    plain text, each detail as a plain ``st.text``, the Can't attend checkbox,
    the Tags, then a ⚙️ button (opens the popup) in the last column. No
    per-cell containers: the page renders (and reruns) in proportion to its
    element count, which is what made the earlier container-per-cell table slow.
    The columns' ratios follow the longest text of each column, the same for
    every row, so the rows stay level. ``detail_actions`` (one dict per person)
    turns a detail cell, by its index, into a button that opens the person's
    popup on the named tab."""
    detail_actions = detail_actions or [{} for _ in people]
    absent_label = "Nemůže se zúčastnit"
    name_label, tags_label = "Jméno", "Štítky"
    ratios = [
        max(len(text) for text in [name_label, *names]) + 2,
        *(
            max(len(text) for text in [label, *(row[i] for row in details)])
            + (5 if any(i in actions for actions in detail_actions) else 2)
            for i, label in enumerate(detail_labels)
        ),
        len(absent_label) + 2,
        max([len(tags_label), *(_tag_width(pills) for pills in tags)]),
        6,
    ]
    header = st.columns(ratios, vertical_alignment="center")
    for column, label in zip(header, [name_label, *detail_labels, absent_label, tags_label]):
        column.markdown(f"**{label}**")
    for person, name, row, person_tags, actions in zip(people, names, details, tags, detail_actions):
        name_cell, *detail_cells, absent_cell, tags_cell, open_cell = st.columns(ratios, vertical_alignment="center")
        name_cell.text(name)
        for i, (cell, text) in enumerate(zip(detail_cells, row)):
            if i in actions:
                if cell.button(text, key=f"detail_{kind}_{person['id']}_{i}", help=f"Otevřít: {person['name']}"):
                    person_dialog.open_person(kind, person["id"], actions[i])
            else:
                cell.text(text)
        _cant_attend_cell(absent_cell, kind, person)
        tags_cell.html(_tag_html(person_tags))
        if open_cell.button(_OPEN_LABEL, key=f"open_{kind}_{person['id']}", help=f"Otevřít: {person['name']}"):
            person_dialog.open_person(kind, person["id"])
    if st.button(add_label, key=f"add_{kind}_open"):
        on_add()


def _render_organizers(state: dict) -> None:
    organizers = sorted(state["organizers"], key=lambda o: o["name"].lower())
    st.subheader(f"Organizátoři ({len(organizers)})")
    pills = mutations.organizer_tag_pills(state)
    _render_table(
        "organizer",
        organizers,
        [o["name"] for o in organizers],
        ["Zařazení"],
        [[" · ".join(filter(None, [o.get("building"), o.get("room")])) or "—"] for o in organizers],
        [pills.get(o["id"]) for o in organizers],
        "＋ Přidat organizátora",
        person_dialog.open_add_organizer,
    )


def _render_helpers(state: dict, returning: dict[int, list[str]], focus_helper_id: int | None = None) -> None:
    """The helper table; ``focus_helper_id`` (a "Go fix" target) marks that
    helper's row."""
    helpers = sorted(state["helpers"], key=lambda h: h["name"].lower())
    st.subheader(f"Pomocníci ({len(helpers)})")
    st.caption("Odvozené štítky (které pomocník má jen díky nadřazenému štítku) mají čárkovaný obrys. Vybavení: 💻 notebook, 📷 fotoaparát.")
    pills = mutations.grid_tag_pills(state)
    detail_labels = ["Dřívější ročníky", "Budovy", "Vybavení", "Tričko", "Kamarádi"]
    friends_column = detail_labels.index("Kamarádi")
    names, details, detail_actions = [], [], []
    for helper in helpers:
        unresolved = len(helper["unresolved_friend_names"])
        names.append(("▶ " if helper["id"] == focus_helper_id else "") + ("⚠️ " if unresolved else "") + helper["name"])
        details.append(
            [
                ", ".join(returning.get(helper["id"], [])) or "—",
                ", ".join(helper["building_preferences"]) or "libovolná",
                " ".join(filter(None, ["💻" if helper["can_bring_notebook"] else "", "📷" if helper["can_bring_camera"] else ""]))
                or "—",
                helper.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE,
                f"⚠️ k přiřazení: {unresolved}" if unresolved else str(mutations.attending_friend_count(state, helper)),
            ]
        )
        detail_actions.append({friends_column: person_dialog.FRIENDS_TAB} if unresolved else {})
    _render_table(
        "helper",
        helpers,
        names,
        detail_labels,
        details,
        [pills.get(h["id"]) for h in helpers],
        "＋ Přidat pomocníka",
        person_dialog.open_add_helper,
        detail_actions,
    )
