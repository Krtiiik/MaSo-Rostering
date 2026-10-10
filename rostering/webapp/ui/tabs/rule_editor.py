"""The rule-list editor shared by Forced friends groups and Tags: one row per
rule, each saying what it demands (share a Building / Room / Role, be / not be
in some Buildings or Rooms, have / not have some Roles), with the add and remove
controls. Both a group's and a Tag's editor offer every row kind: "share" binds the
group's members, or all the carriers of the Tag, together (see
``rostering.forced_friends.tag_groups``).

The editor keeps its rows as drafts and turns them into saved rule dicts only on
``rules()``; validation happens in the mutation that saves them."""
from __future__ import annotations

from typing import Callable, Optional

from nicegui import ui

from rostering import placement_rules as pr
from rostering.domain import Role

# The operations a rule row offers: key -> (label, kind, must).
OPS = {
    "share": ("musí sdílet", pr.SHARE, True),
    "be_must": ("musí být v", pr.BE, True),
    "be_not": ("nesmí být v", pr.BE, False),
    "role_must": ("musí mít roli", pr.BE, True),
    "role_not": ("nesmí mít roli", pr.BE, False),
}
_PLACE_AXES = {pr.BUILDING: "budově", pr.ROOM: "místnosti"}
_SHARE_AXES = {pr.BUILDING: "budovu", pr.ROOM: "místnost", pr.ROLE: "roli"}
_ROOM_SEP = "\x1f"


def room_key(building: str, room: str) -> str:
    return f"{building}{_ROOM_SEP}{room}"


def draft_from_rule(rule: dict) -> dict:
    """One row of the editor from a saved rule."""
    if rule["kind"] == pr.SHARE:
        return {"op": "share", "axis": rule["axis"], "values": []}
    must = rule.get("must", True)
    if rule["axis"] == pr.ROLE:
        return {"op": "role_must" if must else "role_not", "axis": pr.ROLE, "values": list(rule["values"])}
    values = [room_key(*v) if rule["axis"] == pr.ROOM else v for v in rule["values"]]
    return {"op": "be_must" if must else "be_not", "axis": rule["axis"], "values": values}


def rule_from_draft(row: dict) -> dict:
    """The rule a row stands for (validated on save)."""
    _label, kind, must = OPS[row["op"]]
    if kind == pr.SHARE:
        return {"kind": kind, "axis": row["axis"]}
    if row["op"].startswith("role"):
        return {"kind": kind, "must": must, "axis": pr.ROLE, "values": list(row["values"])}
    values = [v.split(_ROOM_SEP, 1) if row["axis"] == pr.ROOM else v for v in row["values"]]
    return {"kind": kind, "must": must, "axis": row["axis"], "values": values}


class RuleEditor:
    """The rows of one rule list. Build it inside the container that should hold
    the rows (``build``); read the result with ``rules()``. ``on_change`` is told
    after every edit of the row structure (add, remove, another kind or axis)."""

    def __init__(
        self,
        layout: list[dict],
        rules: list[dict],
        *,
        allow_share: bool,
        new_op: Optional[str] = None,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self.allow_share = allow_share
        # What a freshly added row says; a group starts on "share", a Tag on "be_must".
        self.new_op = new_op or ("share" if allow_share else "be_must")
        self.on_change = on_change
        self.rows: list[dict] = [draft_from_rule(r) for r in rules]
        self._building_options = {b["name"]: b["name"] for b in layout}
        self._room_options = {room_key(b["name"], r["name"]): f"{r['name']} ({b['name']})" for b in layout for r in b["rooms"]}
        self._role_options = {role.name: role.value for role in Role}
        self._ops = {key: spec[0] for key, spec in OPS.items() if allow_share or key != "share"}
        self._list = None

    # ------------------------------------------------------------------ state
    def rules(self) -> list[dict]:
        return [rule_from_draft(row) for row in self.rows]

    def new_row(self) -> dict:
        if self.new_op == "share":
            return {"op": "share", "axis": pr.ROOM, "values": []}
        return {"op": "be_must", "axis": pr.BUILDING, "values": []}

    def _changed(self) -> None:
        self._list.refresh()
        if self.on_change is not None:
            self.on_change()

    def _remove(self, index: int) -> None:
        self.rows.pop(index)
        self._changed()

    def _add(self) -> None:
        self.rows.append(self.new_row())
        self._changed()

    def _set_op(self, row: dict, op: str) -> None:
        """Change what a row says; the fields that no longer fit are reset."""
        before = row["op"]
        if op == before:
            return
        row["op"] = op
        if op == "share":
            row["axis"] = row["axis"] if row["axis"] in _SHARE_AXES else pr.ROOM
            row["values"] = []
        elif op.startswith("role"):
            row["axis"] = pr.ROLE
            if not before.startswith("role"):
                row["values"] = []
        elif before == "share" or before.startswith("role"):
            row["axis"], row["values"] = pr.BUILDING, []
        self._changed()

    def _set_axis(self, row: dict, axis: str, clear: bool) -> None:
        if axis != row["axis"]:
            row["axis"] = axis
            if clear:
                row["values"] = []
        self._changed()

    # ------------------------------------------------------------------ drawing
    def build(self) -> None:
        @ui.refreshable
        def rule_list() -> None:
            for index, row in enumerate(self.rows):
                self._draw_row(index, row)

        self._list = rule_list
        rule_list()
        ui.button("Přidat pravidlo", icon="add", on_click=self._add).props("flat dense").mark("rule-add")

    def _draw_row(self, index: int, row: dict) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.select(
                self._ops,
                value=row["op"],
                on_change=lambda e, row=row: self._set_op(row, e.value),
            ).props("dense outlined").classes("w-44").mark(f"rule-op-{index}")
            if row["op"] == "share":
                ui.select(
                    _SHARE_AXES,
                    value=row["axis"],
                    on_change=lambda e, row=row: self._set_axis(row, e.value, clear=False),
                ).props("dense outlined").classes("w-32").mark(f"rule-axis-{index}")
            elif row["op"].startswith("role"):
                ui.select(
                    self._role_options,
                    multiple=True,
                    value=row["values"],
                    label="Některá z rolí",
                    on_change=lambda e, row=row: row.update(values=list(e.value or [])),
                ).props("dense outlined use-chips").classes("grow").mark(f"rule-values-{index}")
            else:
                ui.select(
                    _PLACE_AXES,
                    value=row["axis"],
                    on_change=lambda e, row=row: self._set_axis(row, e.value, clear=True),
                ).props("dense outlined").classes("w-32").mark(f"rule-axis-{index}")
                options = self._building_options if row["axis"] == pr.BUILDING else self._room_options
                # A value the layout lost stays listed so the rule can be seen and removed.
                held = {v: v.replace(_ROOM_SEP, " / ") for v in row["values"] if v not in options}
                ui.select(
                    {**options, **held},
                    multiple=True,
                    value=row["values"],
                    label="Některé z",
                    on_change=lambda e, row=row: row.update(values=list(e.value or [])),
                ).props("dense outlined use-chips").classes("grow").mark(f"rule-values-{index}")
            ui.button(icon="delete", on_click=lambda i=index: self._remove(i)).props("flat dense color=negative").mark(
                f"rule-remove-{index}"
            )
