"""The rule model shared by Forced friends groups and Tags (see ``CONTEXT.md``:
Forced friends group, Tag constraint).

A rule is one of

- ``share``: the members (of a Tag: everyone carrying it) must share a
  Building, a Room or a Role (never negated);
- ``be``: every member must (or must not) be in one of some Buildings or Rooms,
  or have one of some Roles (``values`` is the set, "any of"). A group and a Tag
  both state these, so the same rule reads, is validated and is worded the same
  wherever it is written.

Pure: no I/O, and it imports neither the solver nor the rest of the domain.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from rostering.domain import Role

BUILDING = "building"
ROOM = "room"
ROLE = "role"
AXES = (BUILDING, ROOM, ROLE)

SHARE = "share"
BE = "be"

AXIS_LABELS = {BUILDING: "Budova", ROOM: "Místnost", ROLE: "Role"}
# "Split across ..." takes the accusative plural.
_PLURALS = {BUILDING: "budovy", ROOM: "místnosti", ROLE: "role"}
# "musí sdílet ..." takes the accusative singular.
_SHARE_OBJECT = {BUILDING: "budovu", ROOM: "místnost", ROLE: "roli"}

RuleValue = Union[str, tuple[str, str]]  # a Building name, a Role.name or a (Building, Room)


def _joined(labels: Sequence[str], last: str = "a") -> str:
    """``A``, ``A a B``, ``A, B a C`` (``last`` is the word before the final one)."""
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" {last} " + labels[-1]


def value_label(axis: str, value: RuleValue) -> str:
    """How a rule value is shown: a Building name, ``N4 (Troja)``, a Role's name."""
    if axis == ROLE:
        return Role[str(value)].value
    if axis == ROOM:
        building, room = value
        return f"{room} ({building})"
    return str(value)


def _canonical_values(axis: str, values: Iterable[Any]) -> tuple[RuleValue, ...]:
    """The values of a ``be`` rule, validated, without repeats, in a fixed order
    (Roles in the Roles' order, the rest by name), so two rules naming the same
    set are equal. ``ValueError`` (Czech) for a malformed or empty list."""
    found: list[RuleValue] = []
    for value in values or []:
        if axis == ROLE:
            name = value.name if isinstance(value, Role) else str(value or "").strip()
            if name not in Role.__members__:
                raise ValueError(f"Taková role neexistuje: {name or '?'}.")
            found.append(name)
        elif axis == ROOM:
            if isinstance(value, Mapping):
                value = (value.get("building"), value.get("room"))
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("Místnost se uvádí jako budova a název místnosti.")
            building, room = (str(part or "").strip() for part in value)
            if not building or not room:
                raise ValueError("Místnost se uvádí jako budova a název místnosti.")
            found.append((building, room))
        else:
            name = str(value or "").strip()
            if name:
                found.append(name)
    if not found:
        raise ValueError("Pravidlo musí uvádět alespoň jednu hodnotu.")
    unique = list(dict.fromkeys(found))
    if axis == ROLE:
        order = list(Role.__members__)
        return tuple(sorted(unique, key=order.index))
    return tuple(sorted(unique))


@dataclass(frozen=True)


class Rule:
    """One rule of a group. ``share``: ``axis`` is shared by the members (``must``
    is always True, ``values`` empty). ``be``: every member must (``must``) or
    must not be in one of the Buildings / Rooms, or have one of the Roles
    (``axis`` ``ROLE``), in ``values``."""

    kind: str
    axis: str
    must: bool = True
    values: tuple[RuleValue, ...] = ()

    @staticmethod
    def share(axis: str) -> "Rule":
        if axis not in AXES:
            raise ValueError(f"Neznámá osa: {axis!r}")
        return Rule(SHARE, axis)

    @staticmethod
    def be(axis: str, values: Iterable[Any], must: bool = True) -> "Rule":
        if axis not in AXES:
            raise ValueError(f"Neznámá osa: {axis!r}")
        return Rule(BE, axis, bool(must), _canonical_values(axis, values))

    @property
    def key(self) -> str:
        """Identity within a group (a group never holds two equal rules)."""
        if self.kind == SHARE:
            return f"share:{self.axis}"
        shown = "|".join("/".join(v) if isinstance(v, tuple) else v for v in self.values)
        return f"{'must' if self.must else 'not'}:{self.axis}:{shown}"

    def text(self) -> str:
        """The rule in words: ``musí sdílet místnost``, ``nesmí být v budově Troja ani Impakt``."""
        if self.kind == SHARE:
            return f"musí sdílet {_SHARE_OBJECT[self.axis]}"
        labels = [value_label(self.axis, v) for v in self.values]
        joined = _joined(labels, "nebo" if self.must else "ani")
        verb = "musí" if self.must else "nesmí"
        if self.axis == ROLE:
            return f"{verb} mít roli {joined}"
        place = "v budově" if self.axis == BUILDING else "v místnosti"
        return f"{verb} být {place} {joined}"

    def to_dict(self) -> dict[str, Any]:
        if self.kind == SHARE:
            return {"kind": SHARE, "axis": self.axis}
        values = [list(v) if isinstance(v, tuple) else v for v in self.values]
        return {"kind": BE, "must": self.must, "axis": self.axis, "values": values}

    @staticmethod
    def from_dict(data: Union["Rule", str, Mapping[str, Any]]) -> "Rule":
        if isinstance(data, Rule):
            return data
        if isinstance(data, str):  # a bare axis name is a rule to share it
            return Rule.share(data)
        kind = data.get("kind")
        axis = data.get("axis")
        if kind == SHARE:
            return Rule.share(axis)
        if kind == BE:
            return Rule.be(axis, data.get("values") or [], data.get("must", True))
        raise ValueError(f"Neznámý druh pravidla: {kind!r}")


def violates_be(rule: Rule, values: Sequence[RuleValue], building: str, room: str, role: str) -> bool:
    """Whether a Helper placed at (``building``, ``room``, ``role`` as a
    ``Role.name``) breaks the ``be`` ``rule`` over its effective ``values``."""
    if rule.axis == BUILDING:
        inside = building in values
    elif rule.axis == ROOM:
        inside = (building, room) in values
    else:
        inside = role in values
    return inside != rule.must


def effective_values(rule: Rule, buildings: Optional[Mapping[str, Iterable[str]]]) -> tuple[RuleValue, ...]:
    """The values of a ``be`` rule that this Season's layout (Building name ->
    its Room names) still has; the rest are inert. Without a layout, all."""
    if buildings is None or rule.axis == ROLE:
        return rule.values
    known = {name: set(rooms) for name, rooms in buildings.items()}
    if rule.axis == BUILDING:
        return tuple(v for v in rule.values if v in known)
    return tuple(v for v in rule.values if v[0] in known and v[1] in known[v[0]])
