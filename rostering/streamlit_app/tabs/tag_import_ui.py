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

from rostering import forced_friends
from rostering.czech import count_helpers
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
    return f"{source['label']} · {count_helpers(source['helper_count'])} · štítků: {source['tag_count']}"


def _render_groups_overview(section: dict, source_id: str, where: str) -> list[int]:
    """The Forced friends section's overview: one tick per group of the source
    Season with its returning and missing members. A group with nobody returning
    cannot be ticked, and one already in this Season is ticked but skipped by the
    import. Returns the source ids of the ticked groups."""
    st.markdown(f"**{section['title']}**")
    if not section["groups"]:
        st.caption("Zdrojový ročník nemá žádné vynucené skupinky kamarádů.")
        return []
    st.caption(
        "Každá skupinka jde se svými lidmi; člen, který v tomto ročníku není registrován, v ní zůstane jako "
        "zašedlá zástupka a ožije, pokud se později zaregistruje."
    )
    ticked: list[int] = []
    for group in section["groups"]:
        axes = ", ".join(forced_friends.AXIS_LABELS.get(axis, axis).lower() for axis in group["axes"])
        if st.checkbox(
            f"{group['name']} (shodné: {axes})",
            value=group["importable"],
            disabled=not group["importable"] or group["already_present"],
            key=f"tag_import_group_{where}_{_season_id()}_{source_id}_{group['group_id']}",
        ):
            ticked.append(group["group_id"])
        parts = [f"Vracejí se: {', '.join(group['returning']) or 'nikdo'}"]
        if group["missing"]:
            parts.append(f"Chybí: {', '.join(group['missing'])}")
        if not group["importable"]:
            parts.append("nikdo se nevrací, proto se neimportuje")
        elif group["already_present"]:
            parts.append("už v tomto ročníku je, proto se přeskočí")
        st.caption(" · ".join(parts))
    return ticked


@st.dialog("Import z dřívějšího ročníku")
def _import_dialog(where: str) -> None:
    workspace = session.get_workspace()
    offer = mutations.tag_import_offer(workspace)
    sources = {s["id"]: s for s in offer["sources"]}
    if not sources:
        st.info("Zatím není uložen žádný dřívější ročník, takže není co importovat.")
        return
    source_id = st.selectbox(
        "Zdrojový ročník",
        options=list(sources),
        index=list(sources).index(offer["default_source_id"]),
        format_func=lambda sid: _source_label(sources[sid]),
        key=f"tag_import_source_{where}_{_season_id()}",
        help="Vždy jeden ročník; předvybrán je nejnovější dřívější ročník. Další import z jiného ročníku "
        "přidává k tomu, co už je.",
    )
    st.caption(
        "Importuje: "
        + ", ".join(section["title"] for section in offer["sections"])
        + ". Strom štítků se zkopíruje i s omezeními a každý vracející se pomocník nebo organizátor propojený "
        "potvrzenou shodou dostane své štítky zpět. Vynucené skupinky kamarádů následují lidi v nich. Ve "
        "zdrojovém ročníku se nic nemění."
    )
    selections: dict[str, list[int]] = {}
    for section in mutations.import_overview(workspace, source_id)["sections"]:
        if section["key"] == _GROUPS_KEY:
            selections[_GROUPS_KEY] = _render_groups_overview(section, source_id, where)
    if st.button("Importovat", type="primary", key=f"tag_import_go_{where}"):
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
    if st.button("Import z dřívějšího ročníku", icon=":material/download:", key=f"tag_import_open_{where}"):
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
            "**Tento ročník zatím nemá žádné štítky.** Importujte štítky z dřívějšího ročníku a znovu je "
            "přiřaďte vracejícím se pomocníkům."
        )
        open_col, dismiss_col, _ = st.columns([3, 1, 4])
        with open_col:
            render_button("banner")
        if dismiss_col.button("Teď ne", key="tag_import_dismiss_banner"):
            st.session_state[_BANNER_DISMISSED] = [*st.session_state.get(_BANNER_DISMISSED, []), season_id]
            st.rerun()


def render_summary(where: str) -> None:
    """The result of the import started from ``where``, until dismissed."""
    shown = st.session_state.get(_SUMMARY)
    if not shown or shown["where"] != where:
        return
    summary = shown["summary"]
    with st.container(border=True):
        st.success(f"Importováno z ročníku {summary['source']['label']}.")
        for section in summary["sections"]:
            st.markdown(f"**{section['title']}**")
            for line in section.get("lines", []):
                st.write(f"- {line}")
        if st.button("Skrýt", key=f"tag_import_dismiss_summary_{where}"):
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
            f"Použito u {done['helper']}: {', '.join(done['applied']) or 'žádné štítky'}."
            + "".join(f" Přeskočeno: {line}." for line in done["skipped"])
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
        st.markdown(f"**{offer['helper_name']}** je nyní propojen(a). Použít jejich štítky?")
        st.write(
            ", ".join(f"{tag['name']} (z ročníku {tag['source']})" for tag in offer["tags"])
        )
        apply_col, skip_col, _ = st.columns([1.5, 1.5, 5])
        if apply_col.button("Použít jejich štítky", type="primary", key="tag_import_late_apply"):
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
        if skip_col.button("Ne, děkuji", key="tag_import_late_skip"):
            st.session_state.pop(_LATE_LINK, None)
            st.rerun()


@st.dialog("Zestárnutí třídy", width="large")
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
        st.info("Teď není co zestárnout: žádný štítek třídy nezaostává o školní rok.")
    else:
        st.caption(
            "Štítky tříd se posunou o školní rok. Zaškrtněte ty, které se mají přejmenovat; nic se nezmění, dokud nestisknete Použít."
        )
    for suggestion in offer["suggestions"]:
        key = f"class_promotion_tick_{season_id}_{suggestion['tag_id']}_{suggestion['target']}"
        if st.checkbox(f"{suggestion['name']}  →  {suggestion['target']}", value=True, key=key):
            renames[suggestion["tag_id"]] = suggestion["target"]

    others = {t["tag_id"]: t for t in offer["other_tags"]}
    if others:
        picked = st.multiselect(
            "Přejmenovat i další štítky",
            options=list(others),
            format_func=lambda tag_id: others[tag_id]["name"],
            key=f"class_promotion_extra_{season_id}",
            placeholder="Vyberte štítek, kterému dáte nový název",
            help="Pro třídu, kterou vzor názvu nepozná (nebo která nemá dřívější ročník, od kterého by se počítalo). "
            "Nový název začíná jako ten současný.",
        )
        for tag_id in picked:
            renames[tag_id] = st.text_input(
                f"Nový název pro {others[tag_id]['name']}",
                value=others[tag_id]["target"],
                key=f"class_promotion_target_{season_id}_{tag_id}",
            )

    problems = mutations.class_promotion_conflicts(workspace, renames)
    for problem in problems:
        st.error(problem)
    apply_col, skip_col, _ = st.columns([1.5, 2, 4])
    can_apply = not problems and bool(offer["suggestions"] or renames)
    if apply_col.button("Použít", type="primary", disabled=not can_apply, key="class_promotion_apply"):
        try:
            state = mutations.apply_class_promotion(workspace, renames)
        except mutations.RosteringError as exc:
            st.error(str(exc))
            return
        session.set_state(state)
        st.session_state[_PROMOTE_NOTICE] = f"Přejmenováno štítků: {len(renames)}."
        st.rerun()
    if skip_col.button("Zatím přeskočit", key="class_promotion_skip"):
        st.rerun()


def render_promotion_button(where: str) -> None:
    """The always-available "Promote classes" button."""
    if st.button("Zestárnout třídu", icon=":material/arrow_upward:", key=f"class_promotion_open_{where}"):
        _promotion_dialog()


def render_promotion_auto() -> None:
    """What Apply renamed, once, and the dialog itself right after an import that
    asked for it (see ``mutations.import_from_season``'s ``promotion_prompt``)."""
    notice = st.session_state.pop(_PROMOTE_NOTICE, None)
    if notice:
        st.success(notice)
    if st.session_state.pop(_PROMOTE_AUTO, False):
        _promotion_dialog()
