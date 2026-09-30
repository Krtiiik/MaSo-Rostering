"""Person links in the People tab: the page-level review lists (same-name Persons
proposed for a new Helper, typed role names matching a Helper) and the per-Helper
"Person links" section of the person dialog (unlink, or link by hand to any
Person the stored Seasons know). Link edits never change a Helper id."""
from __future__ import annotations

import streamlit as st

from rostering.streamlit_app import mutations, session
from rostering.streamlit_app.tabs import tag_import_ui


def apply_link_edit(action, *args, tagged_helper_id: int | None = None) -> None:
    """Run one link mutation, refresh the session state and rerun; show the
    error instead if it is refused. ``tagged_helper_id`` is the Helper who holds
    the link afterwards when that isn't the first argument (a merge into a
    Helper added by hand)."""
    try:
        session.set_state(action(session.get_workspace(), *args))
    except mutations.RosteringError as exc:
        st.error(str(exc))
        return
    if action is mutations.link_helper:
        # A confirmed link: offer the Person's Tags from an already-imported Season.
        tag_import_ui.queue_late_link_offer(tagged_helper_id or args[0])
    st.rerun()


def _describe(email: str | None, phone: str | None) -> str:
    return f"{email or 'bez e-mailu'} · telefon {phone}" if phone else (email or "bez e-mailu")


def render_uncertain_matches(workspace) -> None:
    """The review list: same-name Persons proposed for a new Helper, to be
    confirmed or rejected one by one. Unreviewed candidates stay unlinked."""
    _render_typed_role_links(workspace)
    entries = mutations.get_uncertain_matches(workspace)
    if not entries:
        return
    st.subheader(f"Možní vracející se pomocníci ({len(entries)})")
    st.caption(
        "Tito pomocníci mají stejné jméno jako někdo z dřívějšího ročníku (nebo pomocník přidaný manuálně), "
        "ale jiný (nebo žádný) e-mail, takže **nejsou propojeni**, dokud to nepotvrdíte. Telefon je jen "
        "nápověda. Co nechcete posoudit, zůstane nepropojené."
    )
    for entry in entries:
        with st.container(border=True):
            st.markdown(
                f"**{entry['helper_name']}** — {_describe(entry['helper_email'], entry['helper_phone'])}"
            )
            for candidate in entry["candidates"]:
                info_col, link_col, reject_col = st.columns([5, 1.2, 2.2], vertical_alignment="center")
                merges_into = candidate["merges_into"]
                info_col.write(
                    f"{candidate['name']} · "
                    + ("manuálně přidán v tomto ročníku" if merges_into else f"ročník {candidate['season']}")
                    + f" · {_describe(candidate['email'], candidate['phone'])}"
                )
                if merges_into:
                    info_col.caption(
                        "Sloučení zachová pomocníka, kterého jste přidali (jeho přiřazení, zámek, štítky a role) "
                        "a to, co jste nechali prázdné, doplní z tohoto řádku ankety."
                    )
                key = f"{entry['helper_id']}_{candidate['person_id']}"
                if link_col.button("Sloučit" if merges_into else "Propojit", key=f"review_link_{key}", type="primary"):
                    apply_link_edit(
                        mutations.link_helper,
                        entry["helper_id"],
                        candidate["person_id"],
                        tagged_helper_id=merges_into,
                    )
                if reject_col.button("Není to tatáž osoba", key=f"review_reject_{key}"):
                    apply_link_edit(mutations.reject_person_match, entry["helper_id"], candidate["person_id"])
            if len(entry["candidates"]) > 1 and st.button(
                "Ani jedna z nich", key=f"review_none_{entry['helper_id']}"
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


def _render_typed_role_links(workspace) -> None:
    """Names typed into a Manual role for someone unregistered that a Helper
    has since matched, offered a link to that Helper. Declining leaves the text."""
    offers = mutations.get_typed_role_link_offers(workspace)
    if not offers:
        return
    st.subheader(f"Napsaná jména rolí shodná s pomocníkem ({len(offers)})")
    st.caption(
        "Tato jména byla napsána do role na záložce Rozdělení pomocníků a registrovaný pomocník má nyní stejné jméno. "
        "Propojením se napsaný text změní na tohoto pomocníka; „Není to tatáž osoba“ ho nechá tak, jak byl napsán."
    )
    for offer in offers:
        with st.container(border=True):
            st.markdown(f"**{offer['name']}** — napsáno jako: {'; '.join(offer['slots'])}")
            for candidate in offer["candidates"]:
                info_col, link_col, reject_col = st.columns([5, 1.2, 2.2], vertical_alignment="center")
                info_col.write(f"{candidate['name']} · {_describe(candidate['email'], candidate['phone'])}")
                key = f"{offer['name']}_{candidate['helper_id']}"
                if link_col.button("Propojit", key=f"typed_role_link_{key}", type="primary"):
                    apply_link_edit(mutations.link_typed_role_name, offer["name"], candidate["helper_id"])
                if reject_col.button("Není to tatáž osoba", key=f"typed_role_reject_{key}"):
                    apply_link_edit(mutations.decline_typed_role_link, offer["name"], candidate["helper_id"])


def render_helper_links(workspace, helper: dict) -> None:
    """Undo this Helper's link, or link them by hand to a Person the stored
    Seasons know."""
    helper_id = helper["id"]
    link = mutations.get_person_links(workspace).get(helper_id)
    if link is not None:
        st.write(
            "Propojen s: "
            + "; ".join(f"{r['name']} ({r['season']}, {r['email'] or 'bez e-mailu'})" for r in link["records"])
        )
        if st.button("Zrušit propojení", key=f"unlink_{helper_id}"):
            apply_link_edit(mutations.unlink_helper, helper_id)
    else:
        st.write("Není propojen s žádným dřívějším záznamem.")

    own_person = helper.get("person_id")
    persons = {p["person_id"]: p for p in mutations.list_persons(workspace) if p["person_id"] != own_person}
    if not persons:
        return
    person_id = st.selectbox(
        "Propojit s dřívější osobou",
        options=sorted(persons, key=lambda pid: persons[pid]["name"].lower()),
        format_func=lambda pid: (
            f"{persons[pid]['name']} — {', '.join(persons[pid]['seasons'])} — "
            f"{', '.join(persons[pid]['emails']) or 'bez e-mailu'}"
        ),
        index=None,
        placeholder="Vyberte osobu",
        key=f"person_links_target_{helper_id}",
    )
    if person_id is not None and st.button("Propojit s touto osobou", key=f"manual_link_{helper_id}"):
        apply_link_edit(mutations.link_helper, helper_id, person_id)
