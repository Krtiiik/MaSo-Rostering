"""Tab 3: the Season's Forced friends groups — named hard constraints on people,
each a list of rules that must all hold: share a Building / Room / Role, or
(not) be in some Buildings or Rooms, or (not) have some Roles (see
``CONTEXT.md``). One card per group with its rules, members and status badge;
New and Edit open a dialog with the rule list, Dissolve asks first. Groups are
applied by the next full Solve (or Place new registrants)."""
from __future__ import annotations

from typing import Any, Optional

from nicegui import ui

from rostering import forced_friends
from rostering.domain import Role
from rostering.webapp import forced_groups, mutations
from rostering.webapp.ui import dialogs, fix_focus
from rostering.webapp.ui.session import UiSession

_MEMBER_SUFFIX = {
    forced_groups.ACTIVE: ("", ""),
    forced_groups.CANT_ATTEND: (" (nemůže se zúčastnit, neaktivní)", "text-orange-700"),
    forced_groups.NOT_REGISTERED: (" (neregistrován)", "text-gray-500"),
    forced_groups.UNPLACED: (" (nezařazený organizátor, neaktivní)", "text-orange-700"),
}
_STATUS = {
    forced_groups.DORMANT: ("Nečinná", "pause", "orange"),
    forced_groups.VIOLATED: ("Porušena", "warning", "negative"),
}
_RULES_HELP = (
    "Všechna pravidla musí platit zároveň. „Sdílet“ znamená, že aktivní členové mají společnou budovu, místnost "
    "nebo roli (stačí dva). U „být v“ a „mít roli“ se pravidlo týká každého člena zvlášť a stačí jedna z "
    "vybraných hodnot. Organizátora role neomezují (žádnou nemá); organizátor vedoucí celou budovu nemá místnost, "
    "takže se u něj místnost posuzuje jen podle budovy."
)
# The operations a rule row offers: key -> (label, kind, must).
_OPS = {
    "share": ("musí sdílet", forced_friends.SHARE, True),
    "be_must": ("musí být v", forced_friends.BE, True),
    "be_not": ("nesmí být v", forced_friends.BE, False),
    "role_must": ("musí mít roli", forced_friends.BE, True),
    "role_not": ("nesmí mít roli", forced_friends.BE, False),
}
_PLACE_AXES = {forced_friends.BUILDING: "budově", forced_friends.ROOM: "místnosti"}
_SHARE_AXES = {forced_friends.BUILDING: "budovu", forced_friends.ROOM: "místnost", forced_friends.ROLE: "roli"}
_ROOM_SEP = "\x1f"


def _room_key(building: str, room: str) -> str:
    return f"{building}{_ROOM_SEP}{room}"


def _new_row() -> dict:
    return {"op": "share", "axis": forced_friends.ROOM, "values": []}


def _draft_from_rule(rule: dict) -> dict:
    """One row of the dialog's rule list from a saved rule."""
    if rule["kind"] == forced_friends.SHARE:
        return {"op": "share", "axis": rule["axis"], "values": []}
    must = rule.get("must", True)
    if rule["axis"] == forced_friends.ROLE:
        return {"op": "role_must" if must else "role_not", "axis": forced_friends.ROLE, "values": list(rule["values"])}
    values = [_room_key(*v) if rule["axis"] == forced_friends.ROOM else v for v in rule["values"]]
    return {"op": "be_must" if must else "be_not", "axis": rule["axis"], "values": values}


def _rule_from_draft(row: dict) -> dict:
    """The rule a dialog row stands for (validated on save)."""
    _label, kind, must = _OPS[row["op"]]
    if kind == forced_friends.SHARE:
        return {"kind": kind, "axis": row["axis"]}
    if row["op"].startswith("role"):
        return {"kind": kind, "must": must, "axis": forced_friends.ROLE, "values": list(row["values"])}
    values = [v.split(_ROOM_SEP, 1) if row["axis"] == forced_friends.ROOM else v for v in row["values"]]
    return {"kind": kind, "must": must, "axis": row["axis"], "values": values}


def _people_options(state: dict, group: Optional[dict]) -> dict:
    """Everyone registered this Season, plus the members of ``group`` who are not
    (kept, shown as not registered)."""
    labels = {
        o["person_id"]: o["name"] + (" (organizátor)" if o["kind"] == "organizer" else "")
        for o in forced_groups.member_options(state)
    }
    cant_attend = {r["person_id"] for r in (*state["helpers"], *state.get("organizers", [])) if r.get("cant_attend")}
    for member in group["members"] if group else []:
        labels.setdefault(member["person_id"], f"{member['name']} (neregistrován)")
    for person_id in cant_attend:
        if person_id in labels:
            labels[person_id] = f"{labels[person_id]} (nemůže se zúčastnit)"
    return dict(sorted(labels.items(), key=lambda item: item[1].lower()))


class ForcedFriendsTab:
    def __init__(self, session: UiSession) -> None:
        self.session = session

    def render(self) -> None:
        s = self.session
        if mutations.get_open_season(s.workspace) is None:
            ui.label("Než přidáte vynucené skupinky kamarádů, otevřete ročník (nebo nahráním odpovědí nějaký vytvořte).")
            return
        state = s.state
        ui.label(
            "Vynucená skupinka kamarádů jsou lidé, na které platí seznam pravidel: musí sdílet budovu, místnost nebo "
            "roli, musí (nebo nesmí) být v určité budově či místnosti, musí (nebo nesmí) mít určitou roli. Pravidla "
            "platí všechna zároveň, na rozdíl od přání být s kamarádem, které je jen přáním. Člověk může být ve více "
            "skupinkách. Řešení drží skupinku pohromadě, kdykoli to jde; pravidlo, které splnit nejde, se hlásí jako "
            "porušené pravidlo. Změna skupinek po sestavení nikoho nepřesouvá a rozdělení pomocníků je do dalšího "
            "sestavení neaktuální."
        ).classes("text-sm text-gray-600")
        fix = fix_focus.render_callout(s, "forced_friends")
        with ui.row().classes("w-full items-center"):
            groups = forced_groups.list_groups(state)
            ui.label(f"Skupinky ({len(groups)})").classes("text-lg font-bold grow")
            if forced_groups.member_options(state):
                ui.button("Nová skupinka", icon="add", on_click=lambda: self._edit(None)).props("color=primary")
            else:
                ui.label("Nejdřív nahrajte odpovědi: skupinka se skládá z registrovaných lidí.").classes(
                    "text-sm text-gray-500"
                )
        if not groups:
            ui.label("Zatím žádné vynucené skupinky kamarádů.").classes("text-gray-600")
            return
        # The group a "Go fix" pointed at, for as long as that rule is still broken.
        focused = fix.group_id if fix is not None else None
        for group in groups:
            self._card(group, focused == group["id"])

    def _card(self, group: dict, focused: bool) -> None:
        card = ui.card().classes("w-full" + (" ring-2 ring-primary" if focused else ""))
        with card:
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(group["name"]).classes("font-bold text-base")
                label, icon, colour = _STATUS.get(group["status"], ("Aktivní", "check", "positive"))
                with ui.badge(color=colour).classes("px-2"):
                    ui.icon(icon).classes("mr-1")
                    ui.label(label)
                ui.space()
                ui.button("Upravit", icon="edit", on_click=lambda g=group: self._edit(g)).props("flat dense")
                ui.button("Rozpustit", icon="group_off", on_click=lambda g=group: self._dissolve(g)).props(
                    "flat dense color=negative"
                )
            with ui.column().classes("gap-0"):
                for text in group["rule_texts"]:
                    ui.label(f"• Členové {text}").classes("text-sm")
            with ui.row().classes("gap-x-2 gap-y-0 flex-wrap"):
                if not group["members"]:
                    ui.label("Žádní členové").classes("text-gray-500")
                for i, member in enumerate(group["members"]):
                    suffix, cls = _MEMBER_SUFFIX[member["state"]]
                    comma = "," if i + 1 < len(group["members"]) else ""
                    ui.label(f"{member['name'] or '?'}{suffix}{comma}").classes(cls)
            if group["status"] == forced_groups.DORMANT:
                ui.label(group["reason"]).classes("text-sm text-gray-600")
            for line in group["violations"]:
                ui.label(line).classes("text-sm text-negative")
            for note in [*group["badges"], *group["missing_places"]]:
                with ui.row().classes("items-center gap-1 text-orange-800"):
                    ui.icon("warning", size="xs")
                    ui.label(note).classes("text-sm")
        if focused:
            ui.run_javascript(f"getElement({card.id}).$el.scrollIntoView({{behavior: 'smooth', block: 'center'}})")

    async def _edit(self, group: Optional[dict]) -> None:
        s = self.session
        layout = s.state["config"]
        building_options = {b["name"]: b["name"] for b in layout}
        room_options = {_room_key(b["name"], r["name"]): f"{r['name']} ({b['name']})" for b in layout for r in b["rooms"]}
        role_options = {role.name: role.value for role in Role}
        rows: list[dict] = [_draft_from_rule(r) for r in group["rules"]] if group else [_new_row()]
        with dialogs.page_dialog(client=self.session.client) as dialog, ui.card().classes("w-[44rem] max-w-full"):
            ui.label("Nová skupinka" if group is None else f"Upravit {group['name']}").classes("text-lg font-bold")
            name = ui.input("Název", value=group["name"] if group else "").classes("w-full").mark("group-name")
            people = ui.select(
                _people_options(s.state, group),
                multiple=True,
                with_input=True,
                label="Lidé",
                value=[m["person_id"] for m in group["members"]] if group else [],
            ).props("use-chips").classes("w-full").mark("group-people")
            ui.label("Pravidla: členové skupinky").classes("text-sm mt-2 font-bold")
            ui.label(_RULES_HELP).classes("text-xs text-gray-600")

            def changed() -> None:
                rule_list.refresh()
                notes.refresh()

            def remove(index: int) -> None:
                rows.pop(index)
                changed()

            def add() -> None:
                rows.append(_new_row())
                changed()

            def set_op(row: dict, op: str) -> None:
                """Change what a row says; the fields that no longer fit are reset."""
                before = row["op"]
                if op == before:
                    return
                row["op"] = op
                if op == "share":
                    row["axis"] = row["axis"] if row["axis"] in _SHARE_AXES else forced_friends.ROOM
                    row["values"] = []
                elif op.startswith("role"):
                    row["axis"] = forced_friends.ROLE
                    if not before.startswith("role"):
                        row["values"] = []
                elif before == "share" or before.startswith("role"):
                    row["axis"], row["values"] = forced_friends.BUILDING, []
                changed()

            def set_axis(row: dict, axis: str, clear: bool) -> None:
                if axis != row["axis"]:
                    row["axis"] = axis
                    if clear:
                        row["values"] = []
                changed()

            @ui.refreshable
            def rule_list() -> None:
                for index, row in enumerate(rows):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.select(
                            {key: spec[0] for key, spec in _OPS.items()},
                            value=row["op"],
                            on_change=lambda e, row=row: set_op(row, e.value),
                        ).props("dense outlined").classes("w-44").mark(f"rule-op-{index}")
                        if row["op"] == "share":
                            ui.select(
                                _SHARE_AXES,
                                value=row["axis"],
                                on_change=lambda e, row=row: set_axis(row, e.value, clear=False),
                            ).props("dense outlined").classes("w-32").mark(f"rule-axis-{index}")
                        elif row["op"].startswith("role"):
                            ui.select(
                                role_options,
                                multiple=True,
                                value=row["values"],
                                label="Některá z rolí",
                                on_change=lambda e, row=row: row.update(values=list(e.value or [])),
                            ).props("dense outlined use-chips").classes("grow").mark(f"rule-values-{index}")
                        else:
                            ui.select(
                                _PLACE_AXES,
                                value=row["axis"],
                                on_change=lambda e, row=row: set_axis(row, e.value, clear=True),
                            ).props("dense outlined").classes("w-32").mark(f"rule-axis-{index}")
                            options = building_options if row["axis"] == forced_friends.BUILDING else room_options
                            # A value the layout lost stays listed so the rule can be seen and removed.
                            held = {v: v.replace(_ROOM_SEP, " / ") for v in row["values"] if v not in options}
                            ui.select(
                                {**options, **held},
                                multiple=True,
                                value=row["values"],
                                label="Některé z",
                                on_change=lambda e, row=row: row.update(values=list(e.value or [])),
                            ).props("dense outlined use-chips").classes("grow").mark(f"rule-values-{index}")
                        ui.button(icon="delete", on_click=lambda i=index: remove(i)).props("flat dense color=negative").mark(
                            f"rule-remove-{index}"
                        )

            @ui.refreshable
            def notes() -> None:
                axes = [forced_friends.Rule.share(row["axis"]) for row in rows if row.get("axis")]
                for line in forced_groups.organizer_notes(s.state, list(people.value or []), axes):
                    with ui.row().classes("items-center gap-1 text-orange-800"):
                        ui.icon("warning", size="xs")
                        ui.label(line).classes("text-sm")

            rule_list()
            ui.button("Přidat pravidlo", icon="add", on_click=add).props("flat dense").mark("rule-add")
            notes()
            people.on_value_change(lambda _e: notes.refresh())

            async def submit() -> None:
                rules = [_rule_from_draft(row) for row in rows]
                if group is None:
                    done = await s.act(
                        lambda: forced_groups.add_group(s.workspace, name.value, list(people.value or []), rules),
                        success=f"Vytvořeno: {(name.value or '').strip()}.",
                    )
                else:
                    done = await s.act(
                        lambda: forced_groups.update_group(
                            s.workspace, group["id"], name=name.value, person_ids=list(people.value or []), rules=rules
                        ),
                        success=f"Změny uloženy: {(name.value or '').strip()}.",
                    )
                if done is not None:
                    dialog.close()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Zrušit", on_click=dialog.close).props("flat")
                ui.button("Vytvořit skupinku" if group is None else "Uložit změny", on_click=submit).props(
                    "color=primary"
                ).mark("group-save")
        dialog.open()

    async def _dissolve(self, group: dict) -> None:
        s = self.session
        if await dialogs.confirm(
            dialogs.ConfirmSpec(
                title="Rozpustit skupinku?",
                ok_label="Rozpustit skupinku",
                intro=f"Rozpustit skupinku **{group['name']}**? Její členové zůstanou, jen už nebudou vynuceně spolu.",
            ),
            client=self.session.client,
        ):
            await s.act(lambda: forced_groups.dissolve_group(s.workspace, group["id"]), success=f"Rozpuštěno: {group['name']}.")
