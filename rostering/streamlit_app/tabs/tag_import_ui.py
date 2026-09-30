"""The Tag import offer (see CONTEXT.md "Tag import"), shared by the Tags tab (an
always-available button) and the Upload tab (a banner while the Season has no
Tags yet, and the "apply their Tags?" prompt after an uncertain link is
confirmed). The dialog lists the sections the import will bring (Tags today; the
offer is section-based) and the result summary is shown once in the tab that
started the import."""
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


def _season_id() -> str | None:
    season = mutations.get_open_season(session.get_workspace())
    return season["id"] if season else None


def _source_label(source: dict) -> str:
    return f"{source['label']} · {source['helper_count']} helpers · {source['tag_count']} Tags"


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
        + ". The Tag tree is copied with its constraints, and every Returning helper linked by a confirmed "
        "match gets their Tags back. Nothing in the source Season changes."
    )
    if st.button("Import", type="primary", key=f"tag_import_go_{where}"):
        try:
            summary = mutations.import_from_season(workspace, source_id)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(mutations.get_state(workspace))
        st.session_state[_SUMMARY] = {"where": where, "summary": summary}
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
