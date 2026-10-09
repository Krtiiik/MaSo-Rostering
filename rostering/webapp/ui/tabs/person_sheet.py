"""The person sheet: everything about one Helper or Organizer, in a panel that
slides in from the right while the People table stays visible behind it (a click
on another row switches the sheet to that person).

A Helper's sheet has the tabs Details (Can't attend, every field, Save / Promote
/ Delete), Tags, Friends (the survey's friend names to match, the Friends picker
and the friends forced into the same Room) and Person links; an Organizer's has
Details and Tags. Pickers save on every change. A picker is only rebuilt when
what it shows changed elsewhere, so picking several values in a row keeps its
list open. Actions that would throw hand work away (Can't attend, Delete,
Promote) ask first, on top of the sheet.

Also here: the "Add helper" and "Add organizer" dialogs."""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from nicegui import ui

from rostering.webapp import forced_groups, mutations
from rostering.webapp.ui import dialogs, pills, tag_import
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.tabs.helper_fields import HelperFields, friend_key, friend_ref, friends_select

DETAILS_TAB = "Podrobnosti"
TAGS_TAB = "Štítky"
FRIENDS_TAB = "Kamarádi"
LINKS_TAB = "Propojení osob"

_DISMISS = "__dismiss__"
_DISMISS_LABEL = "✕ Nezúčastní se"
_UNRESOLVED_PLACEHOLDER = "Nepřiřazeno / Nenalezeno / Neznámé"

_CANT_ATTEND_CAPTION = (
    "Pozdější odškrtnutí Nemůže se zúčastnit to neobnoví. Rozdělení pomocníků je neaktuální do dalšího "
    "sestavení a do té doby je export zablokovaný."
)


def _cant_attend_spec(kind: str, name: str) -> dialogs.ConfirmSpec:
    who = "organizátora" if kind == "organizer" else "pomocníka"
    return dialogs.ConfirmSpec(
        title="Označit jako Nemůže se zúčastnit?",
        ok_label="Označit jako Nemůže se zúčastnit",
        intro=f"Označením {who} **{name}** jako Nemůže se zúčastnit se vymaže:",
        caption=_CANT_ATTEND_CAPTION,
    )


async def set_cant_attend(session: UiSession, kind: str, person: dict, flag: bool) -> None:
    """Flag or un-flag a person; flagging a placed one asks first."""
    setter = mutations.set_organizer_cant_attend if kind == "organizer" else mutations.set_cant_attend
    if not flag:
        await session.act(lambda: setter(session.workspace, person["id"], False))
        return
    await session.act(
        lambda confirmed: setter(session.workspace, person["id"], True, confirmed=confirmed),
        confirm=_cant_attend_spec(kind, person["name"]),
    )
    # Declined or refused: the checkbox must show the saved flag again.
    session.refresh()


def _find(state: dict, kind: str, person_id: int) -> Optional[dict]:
    people = state["organizers" if kind == "organizer" else "helpers"]
    return next((p for p in people if p["id"] == person_id), None)


def _decision_ids(value: object) -> Optional[list]:
    """A friend_name_decisions value as a list of friend references (a Helper id,
    or ``{"organizer_id": n}``), or None for dismissed. Older persisted state
    stored a single int per name instead of a list."""
    if value is None:
        return None
    if isinstance(value, (int, dict)):
        return [value]
    return list(value)


def _friend_names(helper: dict) -> list[str]:
    decisions = helper.get("friend_name_decisions", {})
    all_names = list(dict.fromkeys(list(helper["unresolved_friend_names"]) + list(decisions)))
    # friend_name_order is fixed at upload time, so a name keeps its position
    # after it is resolved and drops out of unresolved_friend_names.
    order_index = {n: i for i, n in enumerate(helper.get("friend_name_order") or [])}
    return sorted(all_names, key=lambda n: order_index.get(n, len(order_index)))


class _Section:
    """A piece of the sheet that is rebuilt only when its ``signature`` (what it
    shows, as saved) changed — not after its own edit, which already shows."""

    def __init__(self, build: Callable[[], None], signature: Callable[[], Any]) -> None:
        self.build = build
        self._signature = signature
        self._sig: Optional[str] = None
        self.container = ui.column().classes("w-full gap-2")
        self.rebuild()

    def _current(self) -> str:
        return json.dumps(self._signature(), sort_keys=True, default=str)

    def rebuild(self) -> None:
        self._sig = self._current()
        self.container.clear()
        with self.container:
            self.build()

    def refresh(self) -> None:
        if self._current() != self._sig:
            self.rebuild()

    def saw_own_edit(self) -> None:
        """The edit just saved came from this section: don't rebuild for it."""
        self._sig = self._current()


class PersonSheet:
    """The page's single person sheet; :meth:`show` opens it for a person."""

    def __init__(self, session: UiSession) -> None:
        self.session = session
        self.kind: Optional[str] = None
        self.person_id: Optional[int] = None
        self.tab = DETAILS_TAB
        self._sections: list[_Section] = []
        self._after_edit: list[Callable[[], None]] = []
        with ui.dialog().props("position=right seamless full-height") as self.dialog:
            self.card = ui.card().classes("w-[40rem] max-w-[95vw] h-full overflow-auto").style("max-width: min(40rem, 95vw)")
        session.on_change(self._on_change)

    # ------------------------------------------------------------------ lifecycle
    def show(self, kind: str, person_id: int, tab: Optional[str] = None) -> None:
        self.kind, self.person_id, self.tab = kind, person_id, tab or DETAILS_TAB
        self._build()
        self.dialog.open()

    def close(self) -> None:
        self.dialog.close()
        self.person_id = None

    @property
    def person(self) -> Optional[dict]:
        if self.kind is None or self.person_id is None:
            return None
        return _find(self.session.state, self.kind, self.person_id)

    def _on_change(self) -> None:
        if self.person_id is None or not self.dialog.value:
            return
        if self.person is None:  # deleted or promoted
            self.close()
            return
        self.title.text = self.person["name"]
        for section in self._sections:
            section.refresh()

    def _build(self) -> None:
        self._sections = []
        self.card.clear()
        person = self.person
        if person is None:
            return
        with self.card:
            with ui.row().classes("w-full items-center no-wrap"):
                kind_label = "Organizátor" if self.kind == "organizer" else "Pomocník"
                with ui.column().classes("gap-0 grow"):
                    ui.label(kind_label).classes("text-xs text-gray-500 uppercase")
                    self.title = ui.label(person["name"]).classes("text-xl font-bold")
                ui.button(icon="close", on_click=self.close).props("flat round dense")
            names = [DETAILS_TAB, TAGS_TAB] + ([FRIENDS_TAB, LINKS_TAB] if self.kind == "helper" else [])
            with ui.tabs(on_change=lambda e: setattr(self, "tab", e.value)).classes("w-full") as tabs:
                for name in names:
                    ui.tab(name)
            with ui.tab_panels(tabs, value=self.tab if self.tab in names else DETAILS_TAB).classes("w-full"):
                with ui.tab_panel(DETAILS_TAB):
                    self._details()
                with ui.tab_panel(TAGS_TAB):
                    self._section(self._tags, lambda: self._tags_signature())
                if self.kind == "helper":
                    with ui.tab_panel(FRIENDS_TAB):
                        self._section(self._matchers, lambda: self._matchers_signature())
                        self._section(self._friends_picker, lambda: self._friends_signature())
                        self._section(self._forced_picker, lambda: self._forced_signature())
                    with ui.tab_panel(LINKS_TAB):
                        self._section(self._links, lambda: self._links_signature())

    def _owner(self, build: Callable[[], None]) -> Optional[_Section]:
        """The section built by ``build`` (a bound method of this sheet)."""
        return next((sec for sec in self._sections if sec.build == build), None)

    def _section(self, build: Callable[[], None], signature: Callable[[], Any]) -> _Section:
        section = _Section(build, signature)
        self._sections.append(section)
        return section

    async def _save(self, section_owner: Optional[_Section], run: Callable[[], dict]) -> bool:
        """Run a picker's mutation; on success apply it without rebuilding the
        picker it came from. A refusal is shown and rebuilds the picker from what
        is saved."""
        try:
            new_state = run()
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            if section_owner is not None:
                section_owner.rebuild()
            return False
        self.session.state = new_state
        if section_owner is not None:
            section_owner.saw_own_edit()
        self.session.apply(new_state)
        return True

    # ------------------------------------------------------------------ Details
    def _details(self) -> None:
        s = self.session
        person = self.person
        assert person is not None
        kind = self.kind
        assert kind is not None

        def cant_attend_box() -> None:
            current = self.person
            if current is None:
                return
            box = ui.checkbox("Nemůže se zúčastnit", value=bool(current.get("cant_attend")))
            box.tooltip("Vyřadí ho z řešení i z rozdělení; po odškrtnutí se vrátí při dalším sestavení rozdělení.")
            box.on_value_change(lambda e: set_cant_attend(s, kind, current, bool(e.value)))

        if kind == "organizer":
            self._section(
                lambda: ui.label(
                    "Zařazení: "
                    + (" · ".join(filter(None, [self.person.get("building"), self.person.get("room")])) or "— (bez místa)")
                    + ". Organizátor je zařazen vedoucím místem, které drží na záložce Rozdělení pomocníků. "
                    "Nemůže se zúčastnit vymaže jeho místa; po odškrtnutí se vrátí (místa se neobnoví)."
                ).classes("text-sm text-gray-600"),
                lambda: [self.person.get("building"), self.person.get("room")] if self.person else None,
            )
        self._section(cant_attend_box, lambda: bool(self.person and self.person.get("cant_attend")))

        if kind == "organizer":
            with ui.row().classes("w-full gap-4 no-wrap"):
                name = ui.input("Jméno", value=person["name"]).classes("grow")
                email = ui.input("E-mail", value=person.get("email") or "").classes("grow")

            async def save_organizer() -> None:
                await s.act(
                    lambda: mutations.update_organizer(s.workspace, person["id"], name=name.value, email=email.value),
                    success=f"Změny uloženy: {(name.value or '').strip()}",
                )

            with ui.row().classes("gap-2 mt-2"):
                ui.button("Uložit změny", on_click=save_organizer).props("color=primary")
                ui.button("Smazat organizátora", on_click=self._delete).props("flat color=negative")
            return

        with ui.row().classes("w-full gap-4 no-wrap"):
            name = ui.input("Jméno", value=person["name"]).classes("grow")
            email = ui.input("E-mail", value=person.get("email") or "").classes("grow")
            phone = ui.input("Telefon / jiný kontakt", value=person.get("phone") or "").classes("grow")
        collisions = ui.column().classes("gap-0")

        def show_collisions() -> None:
            collisions.clear()
            with collisions:
                for line in mutations.helper_collisions(s.state, name.value, email.value, exclude_helper_id=person["id"]):
                    ui.label(f"⚠️ {line}").classes("text-sm text-warning")

        name.on_value_change(show_collisions)
        email.on_value_change(show_collisions)
        show_collisions()
        fields = HelperFields(s.state, person, with_friends=False)

        async def save_helper() -> None:
            await s.act(
                lambda: mutations.update_helper(
                    s.workspace, person["id"], name=name.value, email=email.value, phone=phone.value, **fields.values()
                ),
                success=f"Změny uloženy: {(name.value or '').strip()}",
            )

        with ui.row().classes("gap-2 mt-2"):
            ui.button("Uložit změny", on_click=save_helper).props("color=primary")
            ui.button("Povýšit na organizátora", on_click=self._promote).props("flat").tooltip(
                "Vyřadí je z množiny pomocníků: zachovají si jméno, e-mail, štítky i propojení osoby, ale "
                "nedostanou žádnou sestavenou roli; zařadí se tím, že jim v rozdělení přidělíte vedoucí místo."
            )
            ui.button("Smazat pomocníka", on_click=self._delete).props("flat color=negative")

    async def _delete(self) -> None:
        """Delete the person, after confirming (listing what goes with them)."""
        s = self.session
        person = self.person
        if person is None:
            return
        if self.kind == "organizer":
            spec = dialogs.ConfirmSpec(
                title="Smazat tohoto organizátora?",
                ok_label="Smazat organizátora",
                intro=f"Smazáním organizátora **{person['name']}** se vymaže:",
                caption="Nelze vrátit zpět.",
            )
            lines = mutations.organizer_cant_attend_impact(s.state, person["id"])
            run = mutations.delete_organizer
            noun = "organizátor"
        else:
            spec = dialogs.ConfirmSpec(
                title="Smazat tohoto pomocníka?",
                ok_label="Smazat pomocníka",
                intro=f"Smazáním pomocníka **{person['name']}** se vymaže:",
                caption="Nelze vrátit zpět. Rozdělení pomocníků je neaktuální do dalšího sestavení a do té doby je "
                "export zablokovaný.",
            )
            lines = mutations.cant_attend_impact(s.state, person["id"])
            run = mutations.delete_helper
            noun = "pomocník"
        if not lines:
            spec = dialogs.ConfirmSpec(
                title=spec.title, ok_label=spec.ok_label, intro=f"Smazat **{person['name']}**?", caption=spec.caption
            )
        if not await dialogs.confirm(spec.with_lines(lines)):
            return
        await s.act(lambda: run(s.workspace, person["id"], confirmed=True), success=f"Smazán {noun}: {person['name']}.")

    async def _promote(self) -> None:
        s = self.session
        person = self.person
        if person is None:
            return
        await s.act(
            lambda confirmed: mutations.promote_helper(s.workspace, person["id"], confirmed=confirmed),
            confirm=dialogs.ConfirmSpec(
                title="Povýšit tohoto pomocníka na organizátora?",
                ok_label="Povýšit na organizátora",
                intro=f"Povýšením pomocníka **{person['name']}** na organizátora se vymaže:",
                caption="Opustí množinu pomocníků a nedostanou žádnou sestavenou roli. Rozdělení pomocníků je "
                "neaktuální do dalšího sestavení a do té doby je export zablokovaný.",
                danger=False,
            ),
            success=f"{person['name']} je nyní organizátor.",
        )

    # ------------------------------------------------------------------ Tags
    def _tags_signature(self) -> Any:
        state = self.session.state
        person = self.person
        if person is None:
            return None
        tags_of = mutations.organizer_tags if self.kind == "organizer" else mutations.helper_tags
        return [tags_of(state, person["id"]), state["tags"]]

    def _tags(self) -> None:
        s = self.session
        person = self.person
        if person is None:
            return
        tags = {t["id"]: t for t in s.state["tags"]}
        if not tags:
            ui.label("V tomto ročníku zatím nejsou žádné štítky. Vytvořte je na záložce Štítky.").classes(
                "text-sm text-gray-600"
            )
            return
        is_organizer = self.kind == "organizer"
        tags_of = mutations.organizer_tags if is_organizer else mutations.helper_tags
        set_tags = mutations.set_organizer_tags if is_organizer else mutations.set_helper_tags
        own = tags_of(s.state, person["id"])

        def show_pills() -> None:
            mine = tags_of(s.state, person["id"])
            pills_box.content = pills.pills_html(
                (tags[t] for t in mine["direct"] if t in tags), (tags[t] for t in mine["implied"] if t in tags)
            ) or '<span style="opacity:.5">Žádné štítky</span>'

        async def picked(e) -> None:
            if await self._save(self._owner(self._tags), lambda: set_tags(s.workspace, person["id"], list(e.value or []))):
                show_pills()

        ui.select(
            {tid: t["name"] for tid, t in tags.items()},
            multiple=True,
            with_input=True,
            label="Štítky (přímé)",
            value=list(own["direct"]),
            on_change=picked,
        ).props("use-chips").classes("w-full")
        pills_box = ui.html("")
        show_pills()

    # ------------------------------------------------------------------ Friends
    def _matchers_signature(self) -> Any:
        person = self.person
        if person is None:
            return None
        return [
            person.get("friend_name_decisions"),
            person["unresolved_friend_names"],
            [(h["id"], h["name"]) for h in self.session.state["helpers"]],
            [(o["id"], o["name"]) for o in self.session.state["organizers"]],
        ]

    def _matchers(self) -> None:
        """Match the friend names this Helper wrote on the survey to people. A
        name can match more than one helper if it refers to a group."""
        helper = self.person
        if helper is None:
            return
        names = _friend_names(helper)
        if not names:
            return
        state = self.session.state
        ui.label("K přiřazení").classes("font-bold")
        ui.label(
            "Jména z dotazníku a komu patří. Jméno může odpovídat více pomocníkům, pokud označuje skupinu lidí."
        ).classes("text-sm text-gray-600")
        decisions = helper.get("friend_name_decisions", {})
        others = {
            f"h{h['id']}": h["name"] for h in sorted(state["helpers"], key=lambda h: h["name"].lower()) if h["id"] != helper["id"]
        }
        organizers = {f"o{o['id']}": f"{o['name']} (organizátor)" for o in state["organizers"]}
        options = {_DISMISS: _DISMISS_LABEL, **others, **organizers}
        for name in names:
            was_decided = name in decisions
            decided = _decision_ids(decisions.get(name))
            if was_decided and decided is None:
                value = [_DISMISS]
            elif was_decided:
                value = [k for k in map(friend_key, decided) if k in options]
            else:
                value = []
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.label(f"“{name}”").classes("w-40 shrink-0")
                ui.select(
                    options,
                    multiple=True,
                    with_input=True,
                    new_value_mode="add-unique",
                    value=value,
                    label=_UNRESOLVED_PLACEHOLDER,
                    on_change=lambda e, n=name, d=was_decided, ids=decided: self._match(n, list(e.value or []), d, ids),
                ).props("use-chips").classes("grow")

    async def _match(self, name: str, choice: list[str], was_decided: bool, decided: Optional[list]) -> None:
        if not choice:
            return
        s = self.session
        helper_id = self.person_id
        owner = self._owner(self._matchers)
        if _DISMISS in choice:
            if len(choice) > 1:
                ui.notify(f"„{_DISMISS_LABEL}“ nelze kombinovat s dalšími shodami.", type="warning")
                return
            if was_decided and decided is None:
                return
            await self._save(owner, lambda: mutations.resolve_friend(s.workspace, helper_id, name, "dismiss"))
            return
        unknown = [c for c in choice if c[:1] not in ("h", "o") or not c[1:].isdigit()]
        if unknown:
            ui.notify(", ".join(f"“{u}”" for u in unknown) + ": žádný známý pomocník nesedí.", type="warning")
            return
        refs = [friend_ref(c) for c in choice]
        helper_ids = [r for r in refs if isinstance(r, int)]
        organizer_ids = [r["organizer_id"] for r in refs if isinstance(r, dict)]
        if was_decided and decided == [*helper_ids, *({"organizer_id": o} for o in organizer_ids)]:
            return
        await self._save(
            owner, lambda: mutations.resolve_friend(s.workspace, helper_id, name, "resolve", helper_ids, organizer_ids)
        )

    def _friends_signature(self) -> Any:
        person = self.person
        if person is None:
            return None
        return [sorted(map(friend_key, person.get("friends", []))), [(h["id"], h["name"]) for h in self.session.state["helpers"]]]

    def _friends_picker(self) -> None:
        """The Helper's friends over every Helper and Organizer; saves at once."""
        helper = self.person
        if helper is None:
            return
        s = self.session
        if _friend_names(helper):
            ui.label("Přiřazení kamarádi").classes("font-bold")
        async def changed(e) -> None:
            picked = [friend_ref(k) for k in e.value or []]
            if {friend_key(f) for f in picked} == {friend_key(f) for f in helper.get("friends", [])}:
                return
            await self._save(
                self._owner(self._friends_picker),
                lambda: mutations.update_helper(s.workspace, helper["id"], friends=picked),
            )

        friends_select(s.state, helper["id"], helper.get("friends", []), on_change=changed)

    def _forced_signature(self) -> Any:
        return [r for r in forced_groups.friend_requests(self.session.state) if r["helper_id"] == self.person_id]

    def _forced_picker(self) -> None:
        """"Vynucení kamarádi v místnosti": each of this Helper's friends picked
        is a Forced friends group of the two who must share a Room; unpicking one
        dissolves that group. The friend wish itself is never touched."""
        s = self.session
        helper_id = self.person_id
        requests = self._forced_signature()
        if not requests:
            ui.label("Vynucení kamarádi v místnosti: tento pomocník zatím nemá žádného přiřazeného kamaráda.").classes(
                "text-sm text-gray-600"
            )
            return
        labels = {friend_key(r["friend"]): r["friend_name"] for r in sorted(requests, key=lambda r: r["friend_name"].lower())}
        by_key = {friend_key(r["friend"]): r["friend"] for r in requests}
        forced = [friend_key(r["friend"]) for r in requests if r["forced"]]

        async def changed(e) -> None:
            picked = list(e.value or [])

            def run() -> dict:
                state = s.state
                for key in (k for k in picked if k not in forced):
                    state = forced_groups.make_forced(s.workspace, helper_id, by_key[key])
                for key in (k for k in forced if k not in picked):
                    state = forced_groups.unforce(s.workspace, helper_id, by_key[key])
                return state

            if set(picked) != set(forced) and await self._save(self._owner(self._forced_picker), run):
                forced[:] = picked

        ui.select(
            labels, multiple=True, label="Vynucení kamarádi v místnosti", value=forced, on_change=changed
        ).props("use-chips").classes("w-full").tooltip(
            "Přání být s kamarádem je jen přání. Vynucením vznikne skupinka dvou lidí, kteří musí sdílet "
            "místnost (a tedy i budovu); samotné přání zůstane, jak bylo. Skupinky najdete na záložce "
            "„Vynucené skupinky kamarádů“."
        )

    # ------------------------------------------------------------------ Person links
    def _links_signature(self) -> Any:
        person = self.person
        return [person.get("person_id"), person.get("link_confirmed"), person.get("rejected_person_ids")] if person else None

    def _links(self) -> None:
        """Undo this Helper's link, or link them by hand to a Person the stored
        Seasons know."""
        s = self.session
        helper = self.person
        if helper is None:
            return
        helper_id = helper["id"]
        link = mutations.get_person_links(s.workspace).get(helper_id)
        if link is not None:
            ui.label(
                "Propojen s: "
                + "; ".join(f"{r['name']} ({r['season']}, {r['email'] or 'bez e-mailu'})" for r in link["records"])
            )

            async def unlink() -> None:
                if await dialogs.confirm(
                    dialogs.ConfirmSpec(
                        title="Zrušit propojení?",
                        ok_label="Zrušit propojení",
                        intro=f"Pomocník **{helper['name']}** přestane být propojen se svými dřívějšími záznamy.",
                    )
                ):
                    await s.act(lambda: mutations.unlink_helper(s.workspace, helper_id))

            ui.button("Zrušit propojení", on_click=unlink).props("flat")
        else:
            ui.label("Není propojen s žádným dřívějším záznamem.")
        own_person = helper.get("person_id")
        persons = {p["person_id"]: p for p in mutations.list_persons(s.workspace) if p["person_id"] != own_person}
        if not persons:
            return
        target = ui.select(
            {
                pid: f"{p['name']} — {', '.join(p['seasons'])} — {', '.join(p['emails']) or 'bez e-mailu'}"
                for pid, p in sorted(persons.items(), key=lambda item: item[1]["name"].lower())
            },
            with_input=True,
            label="Propojit s dřívější osobou",
        ).classes("w-full")

        async def link_to() -> None:
            if target.value is None:
                return
            if await s.act(lambda: mutations.link_helper(s.workspace, helper_id, target.value)) is not None:
                tag_import.queue_late_link_offer(s, helper_id)
                s.refresh()

        ui.button("Propojit s touto osobou", on_click=link_to).bind_enabled_from(target, "value", lambda v: v is not None)


# ---------------------------------------------------------------------- add dialogs
async def add_helper(session: UiSession) -> None:
    """The "Add helper" dialog: a name and a contact are required, everything
    else optional (blank, like an unanswered survey row)."""
    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full"):
        ui.label("Přidat pomocníka").classes("text-lg font-bold")
        with ui.row().classes("w-full gap-4 no-wrap"):
            name = ui.input("Jméno (povinné)").classes("grow")
            contact = ui.input("Kontakt (povinný)").classes("grow").tooltip(
                "E-mailová adresa umožní propojit s touto osobou pozdější odpověď ankety ze stejné adresy; "
                "cokoli jiného (třeba telefon) se uchová jen pro zobrazení a párování se vrátí ke jménu."
            )
        collisions = ui.column().classes("gap-0")

        def show_collisions() -> None:
            collisions.clear()
            if not ((name.value or "").strip() or (contact.value or "").strip()):
                return
            with collisions:
                for line in mutations.helper_collisions(session.state, name.value, contact.value):
                    ui.label(f"⚠️ {line}").classes("text-sm text-warning")

        name.on_value_change(show_collisions)
        contact.on_value_change(show_collisions)
        fields = HelperFields(session.state)

        async def submit() -> None:
            new_state = await session.act(
                lambda: mutations.add_helper(session.workspace, name.value, contact.value, **fields.values())
            )
            if new_state is not None:
                dialog.close()
                ui.notify(f"Přidán pomocník: {new_state['helpers'][-1]['name']}.", type="positive")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Zrušit", on_click=dialog.close).props("flat")
            ui.button("Přidat pomocníka", on_click=submit).props("color=primary")
    dialog.open()


async def add_organizer(session: UiSession) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full"):
        ui.label("Přidat organizátora").classes("text-lg font-bold")
        name = ui.input("Jméno (povinné)").classes("w-full")
        email = ui.input("E-mail (volitelný)").classes("w-full").tooltip(
            "E-mailová adresa zaznamenaná v dřívějším ročníku ho propojí s touto osobou."
        )

        async def submit() -> None:
            new_state = await session.act(lambda: mutations.add_organizer(session.workspace, name.value, email.value))
            if new_state is not None:
                dialog.close()
                ui.notify(f"Přidán organizátor: {new_state['organizers'][-1]['name']}.", type="positive")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Zrušit", on_click=dialog.close).props("flat")
            ui.button("Přidat organizátora", on_click=submit).props("color=primary")
    dialog.open()
