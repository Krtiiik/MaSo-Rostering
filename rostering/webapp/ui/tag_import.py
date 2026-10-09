"""The Tag import offer (see CONTEXT.md "Tag import") and Class promotion.

The import dialog lists the sections the import will bring (Tags, then Forced
friends groups, with one tick per group) and opens from the Tags tab and from the
to-do panel's banner (shown while the Season has no Tags and an earlier one has
some). Its result is kept on the session and shown until hidden. After a link is
confirmed, the to-do panel asks whether to apply that Person's Tags from an
already-imported Season. Class promotion's dialog opens from the Tags tab and by
itself after an import that crossed a school year into podzim."""
from __future__ import annotations

from nicegui import ui

from rostering.czech import count_helpers
from rostering.webapp import mutations
from rostering.webapp.ui import dialogs
from rostering.webapp.ui.session import UiSession

_GROUPS_KEY = "forced_groups"  # the Forced friends section of the offer (see forced_groups)


def _source_label(source: dict) -> str:
    return f"{source['label']} · {count_helpers(source['helper_count'])} · štítků: {source['tag_count']}"


async def open_import(session: UiSession, where: str) -> None:
    """The "Import from an earlier Season" dialog; ``where`` is the place whose
    summary area shows the result ("tags" or "todo")."""
    workspace = session.workspace
    offer = mutations.tag_import_offer(workspace)
    sources = {s["id"]: s for s in offer["sources"]}
    with dialogs.page_dialog(client=session.client) as dialog, ui.card().classes("w-[44rem] max-w-full"):
        ui.label("Import z dřívějšího ročníku").classes("text-lg font-bold")
        if not sources:
            ui.label("Zatím není uložen žádný dřívější ročník, takže není co importovat.")
            ui.button("Zavřít", on_click=dialog.close).props("flat")
        else:
            source = ui.select(
                {sid: _source_label(s) for sid, s in sources.items()},
                value=offer["default_source_id"],
                label="Zdrojový ročník",
            ).classes("w-full").tooltip(
                "Vždy jeden ročník; předvybrán je nejnovější dřívější ročník. Další import z jiného ročníku "
                "přidává k tomu, co už je."
            )
            ui.label(
                "Importuje: "
                + ", ".join(section["title"] for section in offer["sections"])
                + ". Strom štítků se zkopíruje i s omezeními a každý vracející se pomocník nebo organizátor "
                "propojený potvrzenou shodou dostane své štítky zpět. Vynucené skupinky kamarádů následují lidi v "
                "nich. Ve zdrojovém ročníku se nic nemění."
            ).classes("text-sm text-gray-600")
            ticks: dict[int, ui.checkbox] = {}

            @ui.refreshable
            def overview() -> None:
                ticks.clear()
                for section in mutations.import_overview(workspace, source.value)["sections"]:
                    if section["key"] == _GROUPS_KEY:
                        _groups_overview(section, ticks)

            overview()
            source.on_value_change(overview.refresh)

            async def run_import() -> None:
                selections = {_GROUPS_KEY: [gid for gid, box in ticks.items() if box.value]}
                try:
                    summary = mutations.import_from_season(workspace, source.value, selections)
                except mutations.RosteringError as exc:
                    ui.notify(str(exc), type="negative")
                    return
                dialog.close()
                session.view.import_summary = {"where": where, "summary": summary}
                session.reload()
                if summary["promotion_prompt"]:
                    await open_promotion(session)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Zrušit", on_click=dialog.close).props("flat")
                ui.button("Importovat", on_click=run_import).props("color=primary")
    dialog.open()


def _groups_overview(section: dict, ticks: dict[int, ui.checkbox]) -> None:
    """One tick per Forced friends group of the source Season with its returning
    and missing members. A group with nobody returning cannot be ticked, and one
    already in this Season is ticked but skipped by the import."""
    ui.label(section["title"]).classes("font-bold mt-2")
    if not section["groups"]:
        ui.label("Zdrojový ročník nemá žádné vynucené skupinky kamarádů.").classes("text-sm text-gray-600")
        return
    ui.label(
        "Každá skupinka jde se svými lidmi; člen, který v tomto ročníku není registrován, v ní zůstane jako "
        "zašedlá zástupka a ožije, pokud se později zaregistruje."
    ).classes("text-sm text-gray-600")
    for group in section["groups"]:
        box = ui.checkbox(f"{group['name']} ({'; '.join(group['rule_texts'])})", value=group["importable"])
        if not group["importable"] or group["already_present"]:
            box.disable()
        ticks[group["group_id"]] = box
        parts = [f"Vracejí se: {', '.join(group['returning']) or 'nikdo'}"]
        if group["missing"]:
            parts.append(f"Chybí: {', '.join(group['missing'])}")
        if not group["importable"]:
            parts.append("nikdo se nevrací, proto se neimportuje")
        elif group["already_present"]:
            parts.append("už v tomto ročníku je, proto se přeskočí")
        ui.label(" · ".join(parts)).classes("text-xs text-gray-600 pl-8 -mt-2")


def render_summary(session: UiSession, where: str) -> None:
    """The result of the import started from ``where``, until hidden."""
    shown = session.view.import_summary
    if not shown or shown["where"] != where:
        return
    summary = shown["summary"]

    def hide() -> None:
        session.view.import_summary = None
        session.refresh()

    with ui.card().classes("w-full bg-green-50"):
        with ui.row().classes("w-full items-center"):
            ui.label(f"Importováno z ročníku {summary['source']['label']}.").classes("font-bold grow")
            ui.button("Skrýt", on_click=hide).props("flat dense")
        for section in summary["sections"]:
            ui.label(section["title"]).classes("font-bold")
            for line in section.get("lines", []):
                ui.label(f"• {line}").classes("text-sm")


def banner_visible(session: UiSession) -> bool:
    if session.view.import_banner_dismissed or mutations.get_open_season(session.workspace) is None:
        return False
    offer = session.cached("tag_import_offer", lambda: mutations.tag_import_offer(session.workspace))
    return bool(offer["banner"])


def render_banner(session: UiSession) -> None:
    """While the Season has no Tags and an earlier Season has some."""
    if not banner_visible(session):
        return

    def dismiss() -> None:
        session.view.import_banner_dismissed = True
        session.refresh()

    with ui.card().classes("w-full"):
        ui.markdown(
            "**Tento ročník zatím nemá žádné štítky.** Importujte štítky z dřívějšího ročníku a znovu je "
            "přiřaďte vracejícím se pomocníkům."
        )
        with ui.row().classes("gap-2"):
            ui.button("Import z dřívějšího ročníku", icon="download", on_click=lambda: open_import(session, "todo"))
            ui.button("Teď ne", on_click=dismiss).props("flat")


def queue_late_link_offer(session: UiSession, helper_id: int) -> None:
    """A link was just confirmed: ask whether to apply the Helper's Tags from an
    already-imported Season (only if there are any)."""
    if mutations.late_link_tag_offer(session.workspace, helper_id) is not None:
        session.view.late_link_helper_id = helper_id


def late_link_offer(session: UiSession):
    helper_id = session.view.late_link_helper_id
    if helper_id is None:
        return None
    try:
        offer = mutations.late_link_tag_offer(session.workspace, helper_id)
    except mutations.RosteringError:
        offer = None
    if offer is None:
        session.view.late_link_helper_id = None
    return offer


def queue_late_link_organizer_offer(session: UiSession, organizer_id: int) -> None:
    """A link of an Organizer was just confirmed: ask whether to apply their Tags
    from an already-imported Season (only if there are any)."""
    if mutations.late_link_organizer_tag_offer(session.workspace, organizer_id) is not None:
        session.view.late_link_organizer_id = organizer_id


def late_link_organizer_offer(session: UiSession):
    organizer_id = session.view.late_link_organizer_id
    if organizer_id is None:
        return None
    try:
        offer = mutations.late_link_organizer_tag_offer(session.workspace, organizer_id)
    except mutations.RosteringError:
        offer = None
    if offer is None:
        session.view.late_link_organizer_id = None
    return offer


def _late_link_card(session: UiSession, name: str, tags: list[dict], apply, skip) -> None:
    with ui.card().classes("w-full"):
        ui.markdown(f"**{name}** je nyní propojen(a). Použít jejich štítky?")
        ui.label(", ".join(f"{tag['name']} (z ročníku {tag['source']})" for tag in tags))
        with ui.row().classes("gap-2"):
            ui.button("Použít jejich štítky", on_click=apply)
            ui.button("Ne, děkuji", on_click=skip).props("flat")


def _notify_applied(name: str, result: dict) -> None:
    skipped = [f"{item['tag']}: {item['reason']}" for item in result["skipped"]]
    ui.notify(
        f"Použito u {name}: {', '.join(result['applied']) or 'žádné štítky'}."
        + "".join(f" Přeskočeno: {line}." for line in skipped),
        type="warning" if skipped else "positive",
        multi_line=True,
    )


def render_late_link_prompt(session: UiSession) -> None:
    """"Apply their Tags?" for the Helper (and, below it, the Organizer) whose
    link was just confirmed."""
    offer = late_link_offer(session)
    if offer is not None:
        helper_id = session.view.late_link_helper_id

        async def apply() -> None:
            try:
                result = mutations.apply_late_link_tags(session.workspace, helper_id)
            except mutations.RosteringError as exc:
                ui.notify(str(exc), type="negative")
                return
            session.view.late_link_helper_id = None
            _notify_applied(offer["helper_name"], result)
            session.reload()

        def skip() -> None:
            session.view.late_link_helper_id = None
            session.refresh()

        _late_link_card(session, offer["helper_name"], offer["tags"], apply, skip)

    organizer_offer = late_link_organizer_offer(session)
    if organizer_offer is not None:
        organizer_id = session.view.late_link_organizer_id

        async def apply_organizer() -> None:
            try:
                result = mutations.apply_late_link_organizer_tags(session.workspace, organizer_id)
            except mutations.RosteringError as exc:
                ui.notify(str(exc), type="negative")
                return
            session.view.late_link_organizer_id = None
            _notify_applied(organizer_offer["organizer_name"], result)
            session.reload()

        def skip_organizer() -> None:
            session.view.late_link_organizer_id = None
            session.refresh()

        _late_link_card(session, organizer_offer["organizer_name"], organizer_offer["tags"], apply_organizer, skip_organizer)


async def open_promotion(session: UiSession) -> None:
    """The Class promotion dialog: tick the suggested renames, add others by hand,
    and Apply them all at once."""
    workspace = session.workspace
    try:
        offer = mutations.class_promotion_offer(workspace)
    except mutations.RosteringError as exc:
        ui.notify(str(exc), type="negative")
        return
    others = {t["tag_id"]: t for t in offer["other_tags"]}
    suggestion_ticks: dict[int, tuple[ui.checkbox, str]] = {}
    extra_names: dict[int, ui.input] = {}

    def renames() -> dict[int, str]:
        chosen = {tag_id: target for tag_id, (box, target) in suggestion_ticks.items() if box.value}
        chosen.update({tag_id: field.value or "" for tag_id, field in extra_names.items()})
        return chosen

    with dialogs.page_dialog(client=session.client) as dialog, ui.card().classes("w-[44rem] max-w-full"):
        ui.label("Zestárnutí třídy").classes("text-lg font-bold")
        if offer["nothing_to_promote"]:
            ui.label("Teď není co zestárnout: žádný štítek třídy nezaostává o školní rok.")
        else:
            ui.label(
                "Štítky tříd se posunou o školní rok. Zaškrtněte ty, které se mají přejmenovat; nic se nezmění, "
                "dokud nestisknete Použít."
            ).classes("text-sm text-gray-600")
        for suggestion in offer["suggestions"]:
            box = ui.checkbox(f"{suggestion['name']}  →  {suggestion['target']}", value=True)
            box.on_value_change(lambda: problems_view())
            suggestion_ticks[suggestion["tag_id"]] = (box, suggestion["target"])

        extras_box = ui.column().classes("w-full gap-1")
        if others:
            picker = ui.select(
                {tag_id: t["name"] for tag_id, t in others.items()},
                multiple=True,
                label="Přejmenovat i další štítky",
            ).props("use-chips").classes("w-full").tooltip(
                "Pro třídu, kterou vzor názvu nepozná (nebo která nemá dřívější ročník, od kterého by se počítalo). "
                "Nový název začíná jako ten současný."
            )

            def extras_changed() -> None:
                picked = list(picker.value or [])
                for tag_id in list(extra_names):
                    if tag_id not in picked:
                        extra_names.pop(tag_id).delete()
                with extras_box:
                    for tag_id in picked:
                        if tag_id not in extra_names:
                            field = ui.input(f"Nový název pro {others[tag_id]['name']}", value=others[tag_id]["target"])
                            field.on_value_change(lambda: problems_view())
                            extra_names[tag_id] = field
                problems_view()

            picker.on_value_change(extras_changed)

        problems_box = ui.column().classes("gap-0")

        def problems_view() -> None:
            current = renames()
            problems = mutations.class_promotion_conflicts(workspace, current)
            problems_box.clear()
            with problems_box:
                for problem in problems:
                    ui.label(problem).classes("text-negative text-sm")
            apply_button.set_enabled(not problems and bool(offer["suggestions"] or current))

        async def apply() -> None:
            current = renames()
            try:
                state = mutations.apply_class_promotion(workspace, current)
            except mutations.RosteringError as exc:
                ui.notify(str(exc), type="negative")
                return
            dialog.close()
            session.apply(state)
            ui.notify(f"Přejmenováno štítků: {len(current)}.", type="positive")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Zatím přeskočit", on_click=dialog.close).props("flat")
            apply_button = ui.button("Použít", on_click=apply).props("color=primary")
        problems_view()
    dialog.open()
