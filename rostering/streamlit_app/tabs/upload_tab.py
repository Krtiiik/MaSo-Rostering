"""Tab 1: upload the raw survey export and resolve friend names."""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from rostering.domain import TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE, Role
from rostering.streamlit_app import fix_focus, mutations, session
from rostering.streamlit_app.tabs import helper_forms, helper_tags

_PREF_ROLES = [r for r in Role if r != Role.Zaloha]
_SIZE_COLUMN = "T-shirt size"
_SIZE_OPTIONS = [*TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE]
_CANT_ATTEND_COLUMN = "Can't attend"
# Session-state keys: the Helper whose Can't attend flag awaits confirmation,
# and a counter that gives the helper table a fresh (unedited) widget state.
_PENDING_CANT_ATTEND = "_pending_cant_attend"
_EDITOR_NONCE = "_helpers_editor_nonce"


def render() -> None:
    st.header("1. Upload responses")
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
            f"**{season['label']}**. This replaces the helpers previously uploaded to it."
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

    if season is not None:
        helper_forms.render_flash()
        helper_forms.render_add_form(state)

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
            msg += f" **{unresolved_count}** friend name(s) still need matching below."
        st.success(msg)

        if state["ingestion_warnings"]:
            with st.expander(f"{len(state['ingestion_warnings'])} ingestion warning(s)"):
                for warning in state["ingestion_warnings"]:
                    st.write(f"- {warning}")

        with st.bottom:
            if st.button("Continue to buildings & rooms →", type="primary"):
                session.switch_tab("2. Buildings")
                st.rerun()

        _show_pending_cant_attend_confirmation(state)
        helper_forms.show_pending_delete_confirmation(state)
        helper_forms.show_pending_promote_confirmation(state)
        if mutations.stale_reasons(state):
            st.warning(
                "The roster is out of date: "
                + "; ".join(mutations.stale_reasons(state))
                + ". Solve again in the Roster tab; Export is blocked until then.",
                icon="⚠️",
            )
        _render_uncertain_matches(workspace)
        fix = fix_focus.render_callout(state, "helpers")
        helper_tags.render()
        _render_helpers_overview(state, returning, focus_helper_id=fix.helper_id if fix else None)
        helper_forms.render_edit_form(state)
        _render_person_links(workspace, state)
        _render_friend_resolution(state)


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


def _apply_link_edit(action, *args) -> None:
    """Run one link mutation, refresh the session state and rerun; show the
    error instead if it is refused."""
    try:
        session.set_state(action(session.get_workspace(), *args))
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    st.rerun()


def _describe(email: str | None, phone: str | None) -> str:
    return f"{email or 'no e-mail'} · phone {phone}" if phone else (email or "no e-mail")


def _render_uncertain_matches(workspace) -> None:
    """The review list: same-name Persons proposed for a new Helper, to be
    confirmed or rejected one by one. Unreviewed candidates stay unlinked."""
    entries = mutations.get_uncertain_matches(workspace)
    if not entries:
        return
    st.subheader(f"Possible returning helpers ({len(entries)})")
    st.caption(
        "These Helpers have the same name as someone from an earlier Season but a different (or no) e-mail, "
        "so they are **not linked** until you confirm. The phone is only a hint. Anything you leave "
        "unreviewed stays unlinked."
    )
    for entry in entries:
        with st.container(border=True):
            st.markdown(
                f"**{entry['helper_name']}** — {_describe(entry['helper_email'], entry['helper_phone'])}"
            )
            for candidate in entry["candidates"]:
                info_col, link_col, reject_col = st.columns([5, 1.2, 2.2], vertical_alignment="center")
                info_col.write(
                    f"{candidate['name']} · Season {candidate['season']} · "
                    f"{_describe(candidate['email'], candidate['phone'])}"
                )
                key = f"{entry['helper_id']}_{candidate['person_id']}"
                if link_col.button("Link", key=f"review_link_{key}", type="primary"):
                    _apply_link_edit(mutations.link_helper, entry["helper_id"], candidate["person_id"])
                if reject_col.button("Not the same person", key=f"review_reject_{key}"):
                    _apply_link_edit(
                        mutations.reject_person_match, entry["helper_id"], candidate["person_id"]
                    )
            if len(entry["candidates"]) > 1 and st.button(
                "None of these", key=f"review_none_{entry['helper_id']}"
            ):
                try:
                    for candidate in entry["candidates"]:
                        session.set_state(
                            mutations.reject_person_match(
                                workspace, entry["helper_id"], candidate["person_id"]
                            )
                        )
                except mutations.RosteringError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()


def _render_person_links(workspace, state: dict) -> None:
    """Undo a Helper's link, or link them by hand to any Person the stored
    Seasons know (link edits never change a Helper id)."""
    with st.expander("Person links (unlink, or link a Helper by hand)"):
        links = mutations.get_person_links(workspace)
        helpers = {h["id"]: h for h in state["helpers"]}
        helper_id = st.selectbox(
            "Helper",
            options=sorted(helpers, key=lambda hid: helpers[hid]["name"].lower()),
            format_func=lambda hid: helpers[hid]["name"] + (" (linked)" if hid in links else ""),
            key="person_links_helper",
        )
        if helper_id is None:
            return
        link = links.get(helper_id)
        if link is not None:
            st.write(
                "Linked to: "
                + "; ".join(
                    f"{r['name']} ({r['season']}, {r['email'] or 'no e-mail'})" for r in link["records"]
                )
            )
            if st.button("Unlink", key=f"unlink_{helper_id}"):
                _apply_link_edit(mutations.unlink_helper, helper_id)
        else:
            st.write("Not linked to any earlier record.")

        own_person = helpers[helper_id].get("person_id")
        persons = {p["person_id"]: p for p in mutations.list_persons(workspace) if p["person_id"] != own_person}
        if not persons:
            return
        person_id = st.selectbox(
            "Link to a past Person",
            options=sorted(persons, key=lambda pid: persons[pid]["name"].lower()),
            format_func=lambda pid: (
                f"{persons[pid]['name']} — {', '.join(persons[pid]['seasons'])} — "
                f"{', '.join(persons[pid]['emails']) or 'no e-mail'}"
            ),
            index=None,
            placeholder="Pick a Person",
            key=f"person_links_target_{helper_id}",
        )
        if person_id is not None and st.button("Link to this Person", key=f"manual_link_{helper_id}"):
            _apply_link_edit(mutations.link_helper, helper_id, person_id)


def _render_helpers_overview(
    state: dict, returning: dict[int, list[str]], focus_helper_id: int | None = None
) -> None:
    """The helper list; ``focus_helper_id`` (a "Go fix" target) marks that
    helper's row."""
    rows = []
    for h in state["helpers"]:
        buildings = ", ".join(h["building_preferences"]) or "any"
        equipment = " ".join(
            filter(None, ["💻" if h["can_bring_notebook"] else "", "📷" if h["can_bring_camera"] else ""])
        ) or "—"
        prefs = ", ".join(
            f"{role.value}: {h['role_preferences'][role.name]}"
            for role in _PREF_ROLES
            if role.name in h["role_preferences"]
        )
        friends = ", ".join(
            next((o["name"] for o in state["organizers"] if o["id"] == fid["organizer_id"]), f"#{fid['organizer_id']}")
            + " (Organizer)"
            if isinstance(fid, dict)
            else next((f["name"] for f in state["helpers"] if f["id"] == fid), f"#{fid}")
            for fid in h["friends"]
        )
        rows.append(
            {
                "Name": ("▶ " if h["id"] == focus_helper_id else "") + h["name"],
                "Earlier Seasons": ", ".join(returning.get(h["id"], [])) or "—",
                "Buildings": buildings,
                "Equipment": equipment,
                _SIZE_COLUMN: h.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE,
                _CANT_ATTEND_COLUMN: bool(h.get("cant_attend")),
                "Role preferences": prefs,
                "Resolved friends": friends,
            }
        )
    st.caption(
        "Pick a size in the T-shirt size column to fix an Unknown. Tick Can't attend to leave a Helper out of "
        "the solve and the roster; untick it to bring them back at the next Solve."
    )
    shown = pd.DataFrame(rows)
    edited = st.data_editor(
        shown,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=[c for c in shown.columns if c not in (_SIZE_COLUMN, _CANT_ATTEND_COLUMN)],
        column_config={
            _SIZE_COLUMN: st.column_config.SelectboxColumn(_SIZE_COLUMN, options=_SIZE_OPTIONS, required=True),
            _CANT_ATTEND_COLUMN: st.column_config.CheckboxColumn(_CANT_ATTEND_COLUMN),
        },
        key=f"helpers_overview_editor_{st.session_state.get(_EDITOR_NONCE, 0)}",
    )
    # Rows keep their original position in the returned frame (even when the
    # user sorts the view), so position i is state["helpers"][i].
    changed = False
    for i, size in edited[_SIZE_COLUMN].items():
        helper = state["helpers"][i]
        if size == shown[_SIZE_COLUMN][i]:
            continue
        try:
            session.set_state(mutations.set_tshirt_size(session.get_workspace(), helper["id"], size))
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        changed = True
    for i, cant_attend in edited[_CANT_ATTEND_COLUMN].items():
        helper = state["helpers"][i]
        if bool(cant_attend) == bool(shown[_CANT_ATTEND_COLUMN][i]):
            continue
        try:
            session.set_state(mutations.set_cant_attend(session.get_workspace(), helper["id"], bool(cant_attend)))
        except mutations.ConfirmationRequired:
            # Flagging would clear hand work: reset the table to what is saved
            # (unticked) and ask first, on the next run.
            st.session_state[_PENDING_CANT_ATTEND] = helper["id"]
            st.session_state[_EDITOR_NONCE] = st.session_state.get(_EDITOR_NONCE, 0) + 1
            st.rerun()
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        changed = True
    if changed:
        st.rerun()


@st.dialog("Mark as Can't attend?")
def _confirm_cant_attend(helper_id: int, name: str, lines: list[str]) -> None:
    st.write(f"Marking **{name}** as Can't attend clears:")
    for line in lines:
        st.write(f"- {line}")
    st.caption(
        "Un-ticking Can't attend later does not restore these. The roster is out of date until the next Solve, "
        "and Export is blocked until then."
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Mark as Can't attend", type="primary", key="cant_attend_confirm"):
        try:
            session.set_state(mutations.set_cant_attend(session.get_workspace(), helper_id, True, confirmed=True))
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        st.rerun()
    if cancel_col.button("Cancel", key="cant_attend_cancel"):
        st.rerun()


def _show_pending_cant_attend_confirmation(state: dict) -> None:
    """Open the confirmation for the Helper whose flag was just requested (once:
    dismissing the dialog drops the request, changing nothing)."""
    helper_id = st.session_state.pop(_PENDING_CANT_ATTEND, None)
    if helper_id is None:
        return
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    lines = mutations.cant_attend_impact(state, helper_id) if helper else []
    if helper is not None and lines:
        _confirm_cant_attend(helper_id, helper["name"], lines)


_DISMISS_LABEL = "✕ Not attending"
_UNRESOLVED_PLACEHOLDER = "Unresolved / Unmatched / Unknown"


def _decision_ids(value: object) -> list[int | dict] | None:
    """Normalize a friend_name_decisions value to a list of friend references
    (a Helper id, or ``{"organizer_id": n}``), or None for dismissed. Older
    persisted state stored a single int per name instead of a list."""
    if value is None:
        return None
    if isinstance(value, (int, dict)):
        return [value]
    return list(value)


def _render_friend_resolution(state: dict) -> None:
    rows = []
    for h in state["helpers"]:
        decisions = h.get("friend_name_decisions", {})
        all_names = list(dict.fromkeys(list(h["unresolved_friend_names"]) + list(decisions)))
        # friend_name_order is fixed at upload time so names keep their
        # original position even after being resolved and dropping out of
        # unresolved_friend_names; fall back to encounter order for state
        # persisted before that field existed.
        order_index = {n: i for i, n in enumerate(h.get("friend_name_order") or [])}
        names = sorted(all_names, key=lambda n: order_index.get(n, len(order_index)))
        if names:
            rows.append((h, names))
    if not rows:
        return

    st.subheader("Resolve friend names")
    st.caption("A name can match more than one helper if it refers to a group of people.")
    other_helpers = {h["id"]: h["name"] for h in state["helpers"]}
    # An Organizer can be named too; their option carries a suffix so a Helper
    # with the same name stays distinguishable.
    organizer_labels = {o["id"]: f"{o['name']} (Organizer)" for o in state["organizers"]}
    for helper, names in rows:
        decisions = helper.get("friend_name_decisions", {})
        candidates = sorted(
            (hid for hid in other_helpers if hid != helper["id"]),
            key=lambda hid: other_helpers[hid].lower(),
        )
        helper_id_by_name = {other_helpers[hid]: hid for hid in candidates}
        organizer_id_by_label = {label: oid for oid, label in organizer_labels.items()}
        options = [_DISMISS_LABEL, *(other_helpers[hid] for hid in candidates), *organizer_id_by_label]

        st.markdown(f"**{helper['name']}** named:")
        for name in names:
            _, label_col, select_col = st.columns([0.3, 2, 3])
            label_col.write(f"“{name}”")
            was_decided = name in decisions
            decided_ids = _decision_ids(decisions.get(name))
            if was_decided and decided_ids is None:
                default = [_DISMISS_LABEL]
            elif was_decided:
                default = [
                    organizer_labels[ref["organizer_id"]]
                    if isinstance(ref, dict)
                    else other_helpers[ref]
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
                    select_col.warning(f"“{_DISMISS_LABEL}” can't be combined with other matches.")
                    continue
                if was_decided and decided_ids is None:
                    continue
                try:
                    session.set_state(
                        mutations.resolve_friend(session.get_workspace(), helper["id"], name, "dismiss")
                    )
                except mutations.RosteringError as exc:
                    st.error(str(exc))
                    continue
                st.rerun()
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
                select_col.warning(f"{names_str} doesn't match any known helper.")
                continue
            if was_decided and decided_ids == [*resolved_ids, *({"organizer_id": o} for o in resolved_organizer_ids)]:
                continue
            try:
                session.set_state(
                    mutations.resolve_friend(
                        session.get_workspace(), helper["id"], name, "resolve", resolved_ids, resolved_organizer_ids
                    )
                )
            except mutations.RosteringError as exc:
                st.error(str(exc))
                continue
            st.rerun()
