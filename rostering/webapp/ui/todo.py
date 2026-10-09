"""The "K vyřízení" (to-do) panel: everything that waits on a decision, in one
right-hand drawer reachable from every tab (its header button shows how many
items wait). It holds the stale and unplaced warnings, the summary of the last
re-upload, the Tag-import banner and result, the "apply their Tags?" prompt after
a link, the typed role names that match a Helper and the possible returning
Helpers (same-name Persons to link or reject), and the same two for the
Organizers (the summary of the last Organizers' import, with what it left to
review). Link edits never change a Helper or Organizer id."""
from __future__ import annotations

import inspect
from html import escape
from typing import Any, Callable

from nicegui import ui

from rostering.czech import plural
from rostering.persistence.workspace import Workspace
from rostering.webapp import labels, mutations
from rostering.webapp.ui import tag_import
from rostering.webapp.ui.session import UiSession


def _describe(email: str | None, phone: str | None) -> str:
    return f"{email or 'bez e-mailu'} · telefon {phone}" if phone else (email or "bez e-mailu")


# A review list can hold hundreds of entries: it is drawn as one HTML block with
# one click handler (as the roster grid is), not as a widget per line. Its
# buttons carry Quasar's own button classes, so they look like ``ui.button``.
_BUTTON = (
    "q-btn q-btn-item non-selectable no-outline q-btn--rectangle q-btn--actionable q-focusable q-hoverable "
    "q-btn--dense {kind}"
)
_PRIMARY = _BUTTON.format(kind="q-btn--standard bg-primary text-white")
_FLAT = _BUTTON.format(kind="q-btn--flat text-primary")
# The clicked button's action number, or nothing for a click elsewhere.
_CLICK_JS = "(e) => { const b = e.target.closest('[data-act]'); if (b) emit(Number(b.dataset.act)); }"


class _Review:
    """Builds one review list's HTML; each button runs the action it was added with."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.actions: list[Callable[[], Any]] = []

    def button(self, label: str, action: Callable[[], Any], primary: bool = True) -> str:
        self.actions.append(action)
        return (
            f'<button type="button" class="{_PRIMARY if primary else _FLAT}" data-act="{len(self.actions) - 1}">'
            '<span class="q-focus-helper"></span>'
            '<span class="q-btn__content text-center col items-center q-anchor--skip justify-center row">'
            f'<span class="block">{escape(label)}</span></span></button>'
        )

    def show(self, mark: str) -> None:
        actions = self.actions

        async def clicked(e) -> None:
            index = e.args
            if isinstance(index, int) and 0 <= index < len(actions):
                result = actions[index]()
                if inspect.isawaitable(result):
                    await result

        ui.html("".join(self.parts), sanitize=False).classes("w-full column q-gutter-y-sm").on(
            "click", clicked, js_handler=_CLICK_JS
        ).mark(mark)


def _card(head: str, lines: list[str]) -> str:
    return '<div class="q-card q-pa-md column q-gutter-y-xs">' + head + "".join(lines) + "</div>"


def _line(text: str, cls: str = "text-sm") -> str:
    return f'<div class="{cls}">{escape(text)}</div>'


def _buttons(*buttons: str) -> str:
    return '<div class="row q-gutter-x-sm">' + "".join(buttons) + "</div>"


def _query(session: UiSession, query: Callable[[Workspace], Any]) -> Any:
    """``query(workspace)``, shared by the header's count and the panel within
    one redraw (each reads every stored Season)."""
    return session.cached(f"todo.{query.__name__}", lambda: query(session.workspace))


def count(session: UiSession) -> int:
    """How many items the panel shows (the badge on its header button)."""
    if mutations.get_open_season(session.workspace) is None:
        return 0
    state = session.state
    shown = [
        bool(mutations.stale_reasons(state)),
        bool(mutations.unplaced_reason(state)),
        _query(session, mutations.upload_summary) is not None,
        tag_import.banner_visible(session),
        tag_import.late_link_offer(session) is not None,
        tag_import.late_link_organizer_offer(session) is not None,
        _query(session, mutations.organizer_upload_summary) is not None,
        bool(session.view.import_summary and session.view.import_summary["where"] == "todo"),
    ]
    return (
        sum(shown)
        + len(_query(session, mutations.get_typed_role_link_offers))
        + len(_query(session, mutations.get_uncertain_matches))
        + len(_query(session, mutations.get_uncertain_organizer_matches))
        + len(_query(session, mutations.get_organizer_slot_offers))
        + len(_query(session, mutations.get_building_match_offers))
    )


class TodoPanel:
    """Drawn only while its ``drawer`` is open: it reads every stored Season."""

    def __init__(self, session: UiSession, drawer: ui.right_drawer) -> None:
        self.session = session
        self.drawer = drawer
        session.on_change(self._on_change)
        drawer.on_value_change(self._toggled)

    def _on_change(self) -> None:
        if self.drawer.value:
            self.render.refresh()

    def _toggled(self, e) -> None:
        if e.value:  # what it shows may have changed since it was last drawn
            self.session.forget_cached()
            self.render.refresh()

    @ui.refreshable_method
    def render(self) -> None:
        s = self.session
        if not self.drawer.value:
            return
        with ui.column().classes("w-full gap-3"):
            ui.label("K vyřízení").classes("text-lg font-bold")
            if mutations.get_open_season(s.workspace) is None:
                ui.label("Zatím není otevřený žádný ročník.").classes("text-sm text-gray-500")
                return
            if count(s) == 0:
                ui.label("Nic nečeká na vyřízení.").classes("text-sm text-gray-500")
            self._warnings()
            self._upload_summary()
            self._organizer_upload_summary()
            tag_import.render_banner(s)
            tag_import.render_summary(s, "todo")
            tag_import.render_late_link_prompt(s)
            self._typed_role_links()
            self._uncertain_matches()
            self._uncertain_organizer_matches()
            self._organizer_slot_offers()
            self._building_match_offers()

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
        summary = _query(s, mutations.upload_summary)
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

    def _organizer_upload_summary(self) -> None:
        s = self.session
        summary = _query(s, mutations.organizer_upload_summary)
        if summary is None:
            return
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center"):
                ui.label("Co změnilo poslední nahrání organizátorů").classes("font-bold grow")
                ui.button(
                    "Skrýt", on_click=lambda: s.act(lambda: mutations.dismiss_organizer_upload_summary(s.workspace))
                ).props("flat dense")
            if summary["new"]:
                ui.markdown(
                    f"**Noví organizátoři ({len(summary['new'])})** (zařadíte je na záložce {labels.TAB_ROSTER}): "
                    + ", ".join(
                        entry["name"] + (" (nemůže se zúčastnit)" if entry.get("cant_attend") else "")
                        for entry in summary["new"]
                    )
                )
            if summary["adopted"]:
                ui.markdown(
                    f"**Odpovědi doplněny k organizátorům, které jste už měli ({len(summary['adopted'])})** "
                    "(podle shody jména): " + ", ".join(entry["name"] for entry in summary["adopted"])
                )
            if summary["changed"]:
                ui.markdown(
                    f"**Organizátoři, kteří změnili odpovědi ({len(summary['changed'])})** (jejich zařazení ani "
                    "příznak Nemůže se zúčastnit se nezměnily):"
                )
                for entry in summary["changed"]:
                    ui.label(
                        f"• {entry['name']}: {', '.join(labels.organizer_field_label(f) for f in entry['fields'])}"
                    ).classes("text-sm")
            if summary["missing"]:
                ui.markdown(
                    f"**Organizátoři chybějící v souboru ({len(summary['missing'])})** (zůstávají, jak jsou): "
                    + ", ".join(entry["name"] for entry in summary["missing"])
                )
            if summary["also_helper"]:
                ui.markdown(
                    f"**Stejné jméno jako u pomocníka ({len(summary['also_helper'])})**: "
                    + ", ".join(entry["name"] for entry in summary["also_helper"])
                    + ". Nic nebylo odebráno, osoba je teď zároveň pomocník i organizátor. Jedno z toho smažte "
                    "(organizátora nebo pomocníka) na záložce Lidé."
                )
            if summary["uncertain"]:
                ui.markdown(
                    f"**Nejisté shody organizátorů čekající na posouzení ({len(summary['uncertain'])})** (níže): "
                    + ", ".join(entry["organizer_name"] for entry in summary["uncertain"])
                )
            if summary["warnings"]:
                with ui.expansion(f"Upozornění při načítání: {len(summary['warnings'])}", icon="info").classes("w-full"):
                    for warning in summary["warnings"]:
                        ui.label(f"• {warning}").classes("text-sm")

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
        offers = _query(self.session, mutations.get_typed_role_link_offers)
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
        entries = _query(self.session, mutations.get_uncertain_matches)
        if not entries:
            return
        ui.label(f"Možní vracející se pomocníci ({len(entries)})").classes("font-bold")
        ui.markdown(
            "Tito pomocníci mají stejné jméno jako někdo z dřívějšího ročníku (nebo pomocník přidaný manuálně), "
            "ale jiný (nebo žádný) e-mail, takže **nejsou propojeni**, dokud to nepotvrdíte. Telefon je jen "
            "nápověda. Co nechcete posoudit, zůstane nepropojené."
        ).classes("text-sm text-gray-600")
        review = _Review()
        for entry in entries:
            lines = []
            for candidate in entry["candidates"]:
                merges_into = candidate["merges_into"]
                lines.append(
                    _line(
                        f"{candidate['name']} · "
                        + ("manuálně přidán v tomto ročníku" if merges_into else f"ročník {candidate['season']}")
                        + f" · {_describe(candidate['email'], candidate['phone'])}"
                    )
                )
                if merges_into:
                    lines.append(
                        _line(
                            "Sloučení zachová pomocníka, kterého jste přidali (jeho přiřazení, zámek, štítky a role) "
                            "a to, co jste nechali prázdné, doplní z tohoto řádku ankety.",
                            "text-xs text-grey-7",
                        )
                    )
                lines.append(
                    _buttons(
                        review.button(
                            "Sloučit" if merges_into else "Propojit",
                            lambda h=entry["helper_id"], p=candidate["person_id"], m=merges_into: self._link_edit(
                                mutations.link_helper, h, p, tagged_helper_id=m
                            ),
                        ),
                        review.button(
                            "Není to tatáž osoba",
                            lambda h=entry["helper_id"], p=candidate["person_id"]: self._link_edit(
                                mutations.reject_person_match, h, p
                            ),
                            primary=False,
                        ),
                    )
                )
            if len(entry["candidates"]) > 1:
                lines.append(_buttons(review.button("Ani jedna z nich", lambda e=entry: self._reject_all(e), False)))
            head = (
                f"<div><b>{escape(entry['helper_name'])}</b> — "
                f"{escape(_describe(entry['helper_email'], entry['helper_phone']))}</div>"
            )
            review.parts.append(_card(head, lines))
        review.show("helper-review")

    async def _reject_all(self, entry: dict) -> None:
        s = self.session

        def reject_all() -> dict:
            state = s.state
            for candidate in entry["candidates"]:
                state = mutations.reject_person_match(s.workspace, entry["helper_id"], candidate["person_id"])
            return state

        await s.act(reject_all)

    async def _organizer_link_edit(self, action: Callable[..., dict], organizer_id: int, person_id: str) -> None:
        """Run one Organizer link mutation; after a confirmed link, offer the
        Person's Tags from an already-imported Season."""
        s = self.session
        if await s.act(lambda: action(s.workspace, organizer_id, person_id)) is None:
            return
        if action is mutations.link_organizer:
            tag_import.queue_late_link_organizer_offer(s, organizer_id)
            s.refresh()

    def _uncertain_organizer_matches(self) -> None:
        """Same-name Persons proposed for an Organizer, to be confirmed or
        rejected one by one. Unreviewed candidates stay unlinked."""
        entries = _query(self.session, mutations.get_uncertain_organizer_matches)
        if not entries:
            return
        ui.label(f"Možní vracející se organizátoři ({len(entries)})").classes("font-bold")
        ui.markdown(
            "Tito organizátoři mají stejné jméno jako někdo z dřívějšího ročníku, ale jiný (nebo žádný) e-mail, "
            "takže **nejsou propojeni**, dokud to nepotvrdíte. Telefon je jen nápověda. Co nechcete posoudit, "
            "zůstane nepropojené."
        ).classes("text-sm text-gray-600")
        review = _Review()
        for entry in entries:
            lines = []
            for candidate in entry["candidates"]:
                lines.append(
                    _line(
                        f"{candidate['name']} · ročník {candidate['season']} · "
                        f"{_describe(candidate['email'], candidate['phone'])}"
                    )
                )
                lines.append(
                    _buttons(
                        review.button(
                            "Propojit",
                            lambda o=entry["organizer_id"], p=candidate["person_id"]: self._organizer_link_edit(
                                mutations.link_organizer, o, p
                            ),
                        ),
                        review.button(
                            "Není to tatáž osoba",
                            lambda o=entry["organizer_id"], p=candidate["person_id"]: self._organizer_link_edit(
                                mutations.reject_organizer_match, o, p
                            ),
                            primary=False,
                        ),
                    )
                )
            if len(entry["candidates"]) > 1:
                lines.append(
                    _buttons(review.button("Ani jedna z nich", lambda e=entry: self._reject_all_organizer(e), False))
                )
            head = (
                f"<div><b>{escape(entry['organizer_name'])}</b> — "
                f"{escape(_describe(entry['organizer_email'], None))}</div>"
            )
            review.parts.append(_card(head, lines))
        review.show("organizer-review")

    async def _reject_all_organizer(self, entry: dict) -> None:
        s = self.session

        def reject_all() -> dict:
            state = s.state
            for candidate in entry["candidates"]:
                state = mutations.reject_organizer_match(s.workspace, entry["organizer_id"], candidate["person_id"])
            return state

        await s.act(reject_all)


    def _organizer_slot_offers(self) -> None:
        """Leadership names from a loaded Buildings sheet that matched no Organizer
        exactly: the Organizers with a similar name are offered for the slot, to be
        picked or declined one by one."""
        s = self.session
        offers = _query(s, mutations.get_organizer_slot_offers)
        if not offers:
            return
        ui.label(f"Jména z tabulky budov bez shody ({len(offers)})").classes("font-bold")
        ui.markdown(
            "Tato jména z načtené tabulky nejsou mezi organizátory ročníku přesně tak, jak jsou napsána, a proto "
            "nejsou zařazena. Vyberte, kdo se jimi myslí, nebo místo nechte prázdné. Chybějícího organizátora "
            f"přidejte na záložce {labels.TAB_PEOPLE}, návrh se pak doplní sám."
        ).classes("text-sm text-gray-600")
        for offer in offers:
            with ui.card().classes("w-full"):
                ui.markdown(f"**{offer['name']}** — {offer['label']}")
                if not offer["candidates"]:
                    ui.label("Žádný organizátor s podobným jménem.").classes("text-sm text-gray-600")
                for candidate in offer["candidates"]:
                    ui.label(
                        f"{candidate['name']} · {_describe(candidate['email'], None)}"
                        + (f" · nyní zařazen(a): {candidate['placed']}" if candidate["placed"] else "")
                    ).classes("text-sm")
                    ui.button(
                        "Zařadit",
                        on_click=lambda o=offer["id"], c=candidate["organizer_id"]: s.act(
                            lambda: mutations.accept_organizer_slot_offer(s.workspace, o, c)
                        ),
                    ).props("dense")
                ui.button(
                    "Nechat prázdné",
                    on_click=lambda o=offer["id"]: s.act(lambda: mutations.dismiss_organizer_slot_offer(s.workspace, o)),
                ).props("flat dense")

    def _building_match_offers(self) -> None:
        """Building names from the survey that match no configured Building (not even
        by an alias or a part of the name): which Building they mean is picked here,
        and every Helper who gave the name gets it."""
        s = self.session
        offers = _query(s, mutations.get_building_match_offers)
        if not offers:
            return
        ui.label(f"Budovy z dotazníku bez shody ({len(offers)})").classes("font-bold")
        ui.markdown(
            "Tyto budovy z dotazníku se nepodařilo přiřadit k žádné budově v konfiguraci, a proto se u pomocníků "
            "zatím nepočítají jako preference. Vyberte, které budovy se jimi myslí (i více), nebo je nejdřív "
            f"doplňte na záložce {labels.TAB_BUILDINGS}."
        ).classes("text-sm text-gray-600")
        for offer in offers:
            with ui.card().classes("w-full"):
                n_helpers = len(offer["helpers"])
                ui.markdown(f"**{offer['name']}** — {n_helpers} {plural(n_helpers, 'pomocník', 'pomocníci', 'pomocníků')}")
                ui.label(", ".join(offer["helpers"])).classes("text-sm text-gray-600")
                pick = (
                    ui.select(offer["candidates"], multiple=True, label="Odpovídající budovy")
                    .props("use-chips")
                    .classes("w-full")
                )
                ui.button(
                    "Přiřadit",
                    on_click=lambda n=offer["name"], p=pick: s.act(
                        lambda: mutations.match_building(s.workspace, n, list(p.value or []))
                    ),
                ).props("dense")


def _warning(text: str) -> None:
    with ui.row().classes("w-full no-wrap items-start gap-2 rounded bg-amber-50 px-3 py-2"):
        ui.icon("warning", color="warning")
        ui.label(text).classes("text-sm")
