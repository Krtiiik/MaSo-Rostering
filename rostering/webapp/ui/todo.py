"""The "K vyřízení" (to-do) panel: everything that waits on a decision, in one
right-hand drawer reachable from every tab (its header button shows how many
items wait). It holds the stale and unplaced warnings, the summary of the last
re-upload, the Tag-import banner and result, the "apply their Tags?" prompt after
a link, the typed role names that match a Helper and the possible returning
Helpers (same-name Persons to link or reject). Link edits never change a Helper
id."""
from __future__ import annotations

from typing import Callable

from nicegui import ui

from rostering.webapp import labels, mutations
from rostering.webapp.ui import tag_import
from rostering.webapp.ui.session import UiSession


def _describe(email: str | None, phone: str | None) -> str:
    return f"{email or 'bez e-mailu'} · telefon {phone}" if phone else (email or "bez e-mailu")


def count(session: UiSession) -> int:
    """How many items the panel shows (the badge on its header button)."""
    if mutations.get_open_season(session.workspace) is None:
        return 0
    state = session.state
    ws = session.workspace
    shown = [
        bool(mutations.stale_reasons(state)),
        bool(mutations.unplaced_reason(state)),
        mutations.upload_summary(ws) is not None,
        tag_import.banner_visible(session),
        tag_import.late_link_offer(session) is not None,
        bool(session.view.import_summary and session.view.import_summary["where"] == "todo"),
    ]
    return (
        sum(shown)
        + len(mutations.get_typed_role_link_offers(ws))
        + len(mutations.get_uncertain_matches(ws))
    )


class TodoPanel:
    def __init__(self, session: UiSession) -> None:
        self.session = session
        session.on_change(self.render.refresh)

    @ui.refreshable_method
    def render(self) -> None:
        s = self.session
        with ui.column().classes("w-full gap-3"):
            ui.label("K vyřízení").classes("text-lg font-bold")
            if mutations.get_open_season(s.workspace) is None:
                ui.label("Zatím není otevřený žádný ročník.").classes("text-sm text-gray-500")
                return
            if count(s) == 0:
                ui.label("Nic nečeká na vyřízení.").classes("text-sm text-gray-500")
            self._warnings()
            self._upload_summary()
            tag_import.render_banner(s)
            tag_import.render_summary(s, "todo")
            tag_import.render_late_link_prompt(s)
            self._typed_role_links()
            self._uncertain_matches()

    # ------------------------------------------------------------------ pieces
    def _warnings(self) -> None:
        state = self.session.state
        stale = mutations.stale_reasons(state)
        if stale:
            _warning(
                "Rozdělení pomocníků je neaktuální: "
                + "; ".join(stale)
                + f". Sestavte rozdělení znovu na záložce {labels.TAB_ROSTER}; do té doby je export zablokovaný."
            )
        unplaced = mutations.unplaced_reason(state)
        if unplaced:
            _warning(unplaced + f". Zařaďte je na záložce {labels.TAB_ROSTER}; do té doby je export zablokovaný.")

    def _upload_summary(self) -> None:
        s = self.session
        summary = mutations.upload_summary(s.workspace)
        if summary is None:
            return
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center"):
                ui.label("Co změnilo poslední nahrání").classes("font-bold grow")
                ui.button("Skrýt", on_click=lambda: s.act(lambda: mutations.dismiss_upload_summary(s.workspace))).props(
                    "flat dense"
                )
            if summary["new"]:
                ui.markdown(
                    f"**Noví zájemci ({len(summary['new'])})**, zatím nezařazení (export je zablokovaný, dokud "
                    "nebudou): " + ", ".join(entry["name"] for entry in summary["new"])
                )
            if summary["changed"]:
                ui.markdown(
                    f"**Zařazení pomocníci, kteří změnili odpovědi ({len(summary['changed'])})** (jejich přiřazení "
                    "zůstalo beze změny; v mřížce jsou označeni ✎, dokud je nepřesunete nebo neuzamknete):"
                )
                for entry in summary["changed"]:
                    ui.label(
                        f"• {entry['name']}: {', '.join(labels.answer_label(f) for f in entry['fields'])}"
                    ).classes("text-sm")
            if summary["missing"]:
                ui.markdown(
                    f"**Pomocníci chybějící v exportu ({len(summary['missing'])})** (zůstávají, jak jsou): "
                    + ", ".join(entry["name"] for entry in summary["missing"])
                )
            if summary["uncertain"]:
                ui.markdown(
                    f"**Nejisté shody čekající na posouzení ({len(summary['uncertain'])})** (níže): "
                    + ", ".join(entry["helper_name"] for entry in summary["uncertain"])
                )

    async def _link_edit(self, action: Callable[..., dict], *args, tagged_helper_id: int | None = None) -> None:
        """Run one link mutation; after a confirmed link, offer the Person's Tags
        from an already-imported Season. ``tagged_helper_id`` is the Helper who
        holds the link afterwards when that isn't the first argument (a merge
        into a Helper added by hand)."""
        s = self.session
        if await s.act(lambda: action(s.workspace, *args)) is None:
            return
        if action is mutations.link_helper:
            tag_import.queue_late_link_offer(s, tagged_helper_id or args[0])
            s.refresh()

    def _typed_role_links(self) -> None:
        """Names typed into a Manual role for someone unregistered that a Helper
        has since matched, offered a link to that Helper."""
        offers = mutations.get_typed_role_link_offers(self.session.workspace)
        if not offers:
            return
        ui.label(f"Napsaná jména rolí shodná s pomocníkem ({len(offers)})").classes("font-bold")
        ui.label(
            f"Tato jména byla napsána do role na záložce {labels.TAB_ROSTER} a registrovaný pomocník má nyní "
            "stejné jméno. Propojením se napsaný text změní na tohoto pomocníka; „Není to tatáž osoba“ ho nechá "
            "tak, jak byl napsán."
        ).classes("text-sm text-gray-600")
        for offer in offers:
            with ui.card().classes("w-full"):
                ui.markdown(f"**{offer['name']}** — napsáno jako: {'; '.join(offer['slots'])}")
                for candidate in offer["candidates"]:
                    ui.label(f"{candidate['name']} · {_describe(candidate['email'], candidate['phone'])}").classes(
                        "text-sm"
                    )
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "Propojit",
                            on_click=lambda n=offer["name"], h=candidate["helper_id"]: self._link_edit(
                                mutations.link_typed_role_name, n, h
                            ),
                        ).props("dense")
                        ui.button(
                            "Není to tatáž osoba",
                            on_click=lambda n=offer["name"], h=candidate["helper_id"]: self._link_edit(
                                mutations.decline_typed_role_link, n, h
                            ),
                        ).props("flat dense")

    def _uncertain_matches(self) -> None:
        """Same-name Persons proposed for a new Helper, to be confirmed or rejected
        one by one. Unreviewed candidates stay unlinked."""
        entries = mutations.get_uncertain_matches(self.session.workspace)
        if not entries:
            return
        ui.label(f"Možní vracející se pomocníci ({len(entries)})").classes("font-bold")
        ui.markdown(
            "Tito pomocníci mají stejné jméno jako někdo z dřívějšího ročníku (nebo pomocník přidaný manuálně), "
            "ale jiný (nebo žádný) e-mail, takže **nejsou propojeni**, dokud to nepotvrdíte. Telefon je jen "
            "nápověda. Co nechcete posoudit, zůstane nepropojené."
        ).classes("text-sm text-gray-600")
        for entry in entries:
            with ui.card().classes("w-full"):
                ui.markdown(f"**{entry['helper_name']}** — {_describe(entry['helper_email'], entry['helper_phone'])}")
                for candidate in entry["candidates"]:
                    merges_into = candidate["merges_into"]
                    ui.label(
                        f"{candidate['name']} · "
                        + ("manuálně přidán v tomto ročníku" if merges_into else f"ročník {candidate['season']}")
                        + f" · {_describe(candidate['email'], candidate['phone'])}"
                    ).classes("text-sm")
                    if merges_into:
                        ui.label(
                            "Sloučení zachová pomocníka, kterého jste přidali (jeho přiřazení, zámek, štítky a role) "
                            "a to, co jste nechali prázdné, doplní z tohoto řádku ankety."
                        ).classes("text-xs text-gray-600")
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "Sloučit" if merges_into else "Propojit",
                            on_click=lambda h=entry["helper_id"], p=candidate["person_id"], m=merges_into: self._link_edit(
                                mutations.link_helper, h, p, tagged_helper_id=m
                            ),
                        ).props("dense")
                        ui.button(
                            "Není to tatáž osoba",
                            on_click=lambda h=entry["helper_id"], p=candidate["person_id"]: self._link_edit(
                                mutations.reject_person_match, h, p
                            ),
                        ).props("flat dense")
                if len(entry["candidates"]) > 1:
                    ui.button("Ani jedna z nich", on_click=lambda e=entry: self._reject_all(e)).props("flat dense")

    async def _reject_all(self, entry: dict) -> None:
        s = self.session

        def reject_all() -> dict:
            state = s.state
            for candidate in entry["candidates"]:
                state = mutations.reject_person_match(s.workspace, entry["helper_id"], candidate["person_id"])
            return state

        await s.act(reject_all)


def _warning(text: str) -> None:
    with ui.row().classes("w-full no-wrap items-start gap-2 rounded bg-amber-50 px-3 py-2"):
        ui.icon("warning", color="warning")
        ui.label(text).classes("text-sm")
