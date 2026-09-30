"""The Tag import offer (see CONTEXT.md "Tag import"), shared by the Tags tab (an
always-available button) and the Upload tab (a banner while the Season has no
Tags yet, and the "apply their Tags?" prompt after an uncertain link is
confirmed). The dialog lists the sections the import will bring (Tags, then
Forced friends groups, with one tick per group; the offer is section-based) and
the result summary is shown once in the tab that started the import. Class promotion (see CONTEXT.md) shares the module: its
dialog opens from a button in the Tags tab and by itself after an import that
crossed a school year into podzim."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session

# Session-state keys: the last import's result and the tab that showed its
# button, the Seasons whose banner was dismissed, and the Helper whose late link
# awaits the "apply their Tags?" answer.
_SUMMARY = "_tag_import_summary"
_BANNER_DISMISSED = "_tag_import_banner_dismissed"
_LATE_LINK = "_tag_import_late_link_helper"
_LATE_RESULT = "_tag_import_late_link_result"
# Class promotion: set after an import that should open the dialog by itself, and
# the line saying what an Apply renamed (shown once).
_PROMOTE_AUTO = "_class_promotion_auto"
_PROMOTE_NOTICE = "_class_promotion_notice"
# The key of the Forced friends section of the offer (see ``forced_groups``).
_GROUPS_KEY = "forced_groups"


def _season_id() -> str | None:
    season = mutations.get_open_season(session.get_workspace())
    return season["id"] if season else None


def _source_label(source: dict) -> str:
    return f"{source['label']} · {source['helper_count']} helpers · {source['tag_count']} Tags"


def _render_groups_overview(section: dict, source_id: str, where: str) -> list[int]:
    """The Forced friends section's overview: one tick per group of the source
    Season with its returning and missing members. A group with nobody returning
    cannot be ticked, and one already in this Season is ticked but skipped by the
    import. Returns the source ids of the ticked groups."""
    st.markdown(f"**{section['title']}**")
    if not section["groups"]:
        st.caption("The source Season has no Forced friends groups.")
        return []
    st.caption(
        "Each group goes with its people; a member who is not registered this Season stays in it as a dim "
        "placeholder and becomes live if they register later."
    )
    ticked: list[int] = []
    for group in section["groups"]:
        axes = ", ".join(axis.capitalize() for axis in group["axes"])
        if st.checkbox(
            f"{group['name']} (same {axes})",
            value=group["importable"],
            disabled=not group["importable"] or group["already_present"],
            key=f"tag_import_group_{where}_{_season_id()}_{source_id}_{group['group_id']}",
        ):
            ticked.append(group["group_id"])
        parts = [f"Returning: {', '.join(group['returning']) or 'nobody'}"]
        if group["missing"]:
            parts.append(f"Missing: {', '.join(group['missing'])}")
        if not group["importable"]:
            parts.append("nobody returns, so it is not imported")
        elif group["already_present"]:
            parts.append("already in this Season, so it is skipped")
        st.caption(" · ".join(parts))
    return ticked


@st.dialog("Import from an earlier Season")
def _import_dialog(where: str) -> None:
    workspace = session.get_workspace()
    offer = mutations.tag_import_offer(workspace)
    sources = {s["id"]: s for s in offer["sources"]}
    if not sources:
        st.info("No earlier Season is stored yet, so there is nothing to import.")
        return
    source_id = st.selectbox(
        "Source Season",
        options=list(sources),
        index=list(sources).index(offer["default_source_id"]),
        format_func=lambda sid: _source_label(sources[sid]),
        key=f"tag_import_source_{where}_{_season_id()}",
        help="One Season at a time; the most recent earlier Season is preselected. Importing again from "
        "another Season adds to what is there.",
    )
    st.caption(
        "Imports: "
        + ", ".join(section["title"] for section in offer["sections"])
        + ". The Tag tree is copied with its constraints, and every Returning helper or Organizer linked by a "
        "confirmed match gets their Tags back. Forced friends groups follow the people in them. Nothing in the "
        "source Season changes."
    )
    selections: dict[str, list[int]] = {}
    for section in mutations.import_overview(workspace, source_id)["sections"]:
        if section["key"] == _GROUPS_KEY:
            selections[_GROUPS_KEY] = _render_groups_overview(section, source_id, where)
    if st.button("Import", type="primary", key=f"tag_import_go_{where}"):
        try:
            summary = mutations.import_from_season(workspace, source_id, selections)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(mutations.get_state(workspace))
        st.session_state[_SUMMARY] = {"where": where, "summary": summary}
        if summary["promotion_prompt"]:
            st.session_state[_PROMOTE_AUTO] = True
        st.rerun()


def render_button(where: str) -> None:
    """The always-available "Import Tags" button."""
    if st.button("Import from an earlier Season", icon=":material/download:", key=f"tag_import_open_{where}"):
        _import_dialog(where)


def render_banner() -> None:
    """A banner after the first upload while the Season has no Tags and an earlier
    Season has some. It does not wait for the uncertain-match review."""
    workspace = session.get_workspace()
    season_id = _season_id()
    if season_id is None or season_id in st.session_state.get(_BANNER_DISMISSED, []):
        return
    offer = mutations.tag_import_offer(workspace)
    if not offer["banner"]:
        return
    with st.container(border=True):
        st.markdown(
            "**This Season has no Tags yet.** Import an earlier Season's Tags and re-apply them to your "
            "Returning helpers."
        )
        open_col, dismiss_col, _ = st.columns([3, 1, 4])
        with open_col:
            render_button("banner")
        if dismiss_col.button("Not now", key="tag_import_dismiss_banner"):
            st.session_state[_BANNER_DISMISSED] = [*st.session_state.get(_BANNER_DISMISSED, []), season_id]
            st.rerun()


def render_summary(where: str) -> None:
    """The result of the import started from ``where``, until dismissed."""
    shown = st.session_state.get(_SUMMARY)
    if not shown or shown["where"] != where:
        return
    summary = shown["summary"]
    with st.container(border=True):
        st.success(f"Imported from {summary['source']['label']}.")
        for section in summary["sections"]:
            st.markdown(f"**{section['title']}**")
            for line in section.get("lines", []):
                st.write(f"- {line}")
        if st.button("Dismiss", key=f"tag_import_dismiss_summary_{where}"):
            st.session_state.pop(_SUMMARY, None)
            st.rerun()


def queue_late_link_offer(helper_id: int) -> None:
    """A link was just confirmed: ask, on the next run, whether to apply the
    Helper's Tags from an already-imported Season (only if there are any)."""
    if mutations.late_link_tag_offer(session.get_workspace(), helper_id) is not None:
        st.session_state[_LATE_LINK] = helper_id


def render_late_link_prompt() -> None:
    """"Apply their Tags?" for the Helper whose link was just confirmed, and what
    happened once they answered."""
    done = st.session_state.pop(_LATE_RESULT, None)
    if done:
        (st.warning if done["skipped"] else st.success)(
            f"Applied to {done['helper']}: {', '.join(done['applied']) or 'no Tags'}."
            + "".join(f" Skipped {line}." for line in done["skipped"])
        )
    helper_id = st.session_state.get(_LATE_LINK)
    if helper_id is None:
        return
    workspace = session.get_workspace()
    try:
        offer = mutations.late_link_tag_offer(workspace, helper_id)
    except mutations.RosteringError:
        offer = None
    if offer is None:
        st.session_state.pop(_LATE_LINK, None)
        return
    with st.container(border=True):
        st.markdown(f"**{offer['helper_name']}** is linked now. Apply their Tags?")
        st.write(
            ", ".join(f"{tag['name']} (from {tag['source']})" for tag in offer["tags"])
        )
        apply_col, skip_col, _ = st.columns([1.5, 1.5, 5])
        if apply_col.button("Apply their Tags", type="primary", key="tag_import_late_apply"):
            try:
                result = mutations.apply_late_link_tags(workspace, helper_id)
            except mutations.RosteringError as exc:
                st.error(str(exc))
                return
            session.set_state(mutations.get_state(workspace))
            st.session_state.pop(_LATE_LINK, None)
            st.session_state[_LATE_RESULT] = {
                "helper": offer["helper_name"],
                "applied": result["applied"],
                "skipped": [f"{item['tag']}: {item['reason']}" for item in result["skipped"]],
            }
            st.rerun()
        if skip_col.button("No thanks", key="tag_import_late_skip"):
            st.session_state.pop(_LATE_LINK, None)
            st.rerun()


@st.dialog("Promote classes", width="large")
def _promotion_dialog() -> None:
    workspace = session.get_workspace()
    try:
        offer = mutations.class_promotion_offer(workspace)
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    season_id = _season_id()
    renames: dict[int, str] = {}
    if offer["nothing_to_promote"]:
        st.info("Nothing to promote right now: no class Tag is a school year behind.")
    else:
        st.caption(
            "Class Tags move up one school year. Tick the ones to rename; nothing changes until you press Apply."
        )
    for suggestion in offer["suggestions"]:
        key = f"class_promotion_tick_{season_id}_{suggestion['tag_id']}_{suggestion['target']}"
        if st.checkbox(f"{suggestion['name']}  →  {suggestion['target']}", value=True, key=key):
            renames[suggestion["tag_id"]] = suggestion["target"]

    others = {t["tag_id"]: t for t in offer["other_tags"]}
    if others:
        picked = st.multiselect(
            "Rename other Tags too",
            options=list(others),
            format_func=lambda tag_id: others[tag_id]["name"],
            key=f"class_promotion_extra_{season_id}",
            placeholder="Pick a Tag to give it a new name",
            help="For a class the name pattern does not recognize (or that has no earlier Season to count from). "
            "The new name starts as the current one.",
        )
        for tag_id in picked:
            renames[tag_id] = st.text_input(
                f"New name for {others[tag_id]['name']}",
                value=others[tag_id]["target"],
                key=f"class_promotion_target_{season_id}_{tag_id}",
            )

    problems = mutations.class_promotion_conflicts(workspace, renames)
    for problem in problems:
        st.error(problem)
    apply_col, skip_col, _ = st.columns([1.5, 2, 4])
    can_apply = not problems and bool(offer["suggestions"] or renames)
    if apply_col.button("Apply", type="primary", disabled=not can_apply, key="class_promotion_apply"):
        try:
            state = mutations.apply_class_promotion(workspace, renames)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(state)
        st.session_state[_PROMOTE_NOTICE] = f"Renamed {len(renames)} Tag{'s' if len(renames) != 1 else ''}."
        st.rerun()
    if skip_col.button("Skip for now", key="class_promotion_skip"):
        st.rerun()


def render_promotion_button(where: str) -> None:
    """The always-available "Promote classes" button."""
    if st.button("Promote classes", icon=":material/arrow_upward:", key=f"class_promotion_open_{where}"):
        _promotion_dialog()


def render_promotion_auto() -> None:
    """What Apply renamed, once, and the dialog itself right after an import that
    asked for it (see ``mutations.import_from_season``'s ``promotion_prompt``)."""
    notice = st.session_state.pop(_PROMOTE_NOTICE, None)
    if notice:
        st.success(notice)
    if st.session_state.pop(_PROMOTE_AUTO, False):
        _promotion_dialog()
