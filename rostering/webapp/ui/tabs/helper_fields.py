"""The Helper fields shared by the "Add helper" dialog and a Helper's Details:
Role preferences as star ratings, the acceptable Buildings, equipment, T-shirt
size and (in the add form) the friends picker. A hand-added Helper is an ordinary
Helper, so nothing here marks one as different."""
from __future__ import annotations

from typing import Any, Optional

from nicegui import ui

from rostering.domain import TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE, Preference, Role

_ROLES = [r for r in Role if r != Role.Zaloha]  # Záloha is not a survey Preference
_UNSET_TEXT = "— (bez odpovědi, počítá se jako Nevadí)"  # no stars: the Role reads as Nevadí
PREFERENCE_LABELS = {
    Preference.Ano: "Ano",
    Preference.Klidne: "Klidně",
    Preference.Nevadi: "Nevadí",
    Preference.Spise_ne: "Spíš ne",
    Preference.Ne: "Ne",
}
# Five stars is Ano, one is Ne; no stars is no answer.
_PREF_BY_STARS = {5 - i: pref for i, pref in enumerate(PREFERENCE_LABELS)}
_STARS_BY_NAME = {pref.name: stars for stars, pref in _PREF_BY_STARS.items()}
SIZE_OPTIONS = [*TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE]


def friend_key(ref: int | dict) -> str:
    """A friend reference (a Helper id, or ``{"organizer_id": n}``) as the
    "h<id>" / "o<id>" option key of the friends pickers."""
    return f"o{ref['organizer_id']}" if isinstance(ref, dict) else f"h{ref}"


def friend_ref(key: str) -> int | dict:
    return {"organizer_id": int(key[1:])} if key[0] == "o" else int(key[1:])


def friend_labels(state: dict, own_id: Optional[int]) -> dict[str, str]:
    """Every person a Helper can name as a friend, by option key: the other
    Helpers and all Organizers (marked as such), sorted by name."""
    labels = {f"h{h['id']}": h["name"] for h in state["helpers"] if h["id"] != own_id}
    labels.update({f"o{o['id']}": f"{o['name']} (organizátor)" for o in state["organizers"]})
    return dict(sorted(labels.items(), key=lambda item: item[1].lower()))


def friends_select(state: dict, own_id: Optional[int], current: list, **kwargs: Any) -> ui.select:
    """The "Kamarádi" multi-select over every Helper and Organizer."""
    labels = friend_labels(state, own_id)
    return ui.select(
        labels,
        multiple=True,
        with_input=True,
        label="Kamarádi (pomocníci nebo organizátoři, se kterými chce sdílet místnost)",
        value=[k for k in map(friend_key, current) if k in labels],
        **kwargs,
    ).props("use-chips").classes("w-full")


class HelperFields:
    """The optional Helper inputs, prefilled from ``helper`` when editing;
    :meth:`values` returns them as the keyword arguments of ``add_helper`` /
    ``update_helper``."""

    def __init__(self, state: dict, helper: Optional[dict] = None, *, with_friends: bool = True) -> None:
        helper = helper or {}
        self._ratings: dict[str, ui.rating] = {}
        ui.label(
            "Preference rolí (hvězdičky: 5 = Ano … 1 = Ne; bez hvězdiček se role počítá jako Nevadí)"
        ).classes("text-sm text-gray-600")
        current = helper.get("role_preferences", {})
        with ui.grid(columns="auto auto 1fr").classes("items-center gap-x-4 gap-y-0"):
            for role in _ROLES:
                ui.label(role.value)
                stars = ui.rating(value=_STARS_BY_NAME.get(current.get(role.name), 0), max=5).props("size=1.4em")
                meaning = ui.label().classes("text-sm")
                stars.on_value_change(lambda e, m=meaning: self._describe(m, e.value))
                self._describe(meaning, stars.value)
                self._ratings[role.name] = stars
        buildings = [b["name"] for b in state["config"]]
        self.buildings = ui.select(
            buildings,
            multiple=True,
            label="Přijatelné budovy (nevybráno nic: libovolná)",
            value=[b for b in helper.get("building_preferences", []) if b in buildings],
        ).props("use-chips").classes("w-full")
        with ui.row().classes("items-center gap-6"):
            self.notebook = ui.checkbox("Může přinést notebook", value=bool(helper.get("can_bring_notebook")))
            self.camera = ui.checkbox("Může přinést fotoaparát", value=bool(helper.get("can_bring_camera")))
            self.size = ui.select(
                SIZE_OPTIONS, label="Velikost trička", value=helper.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE
            ).classes("min-w-[10rem]")
        self.friends = friends_select(state, helper.get("id"), helper.get("friends", [])) if with_friends else None

    @staticmethod
    def _describe(label: ui.label, stars: Optional[float]) -> None:
        pref = _PREF_BY_STARS.get(int(stars or 0))
        label.text = PREFERENCE_LABELS[pref] if pref else _UNSET_TEXT
        label.classes(replace="text-sm" + ("" if pref else " text-gray-500"))

    def values(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "role_preferences": {
                role: _PREF_BY_STARS[int(r.value)].name for role, r in self._ratings.items() if r.value
            },
            "building_preferences": list(self.buildings.value or []),
            "can_bring_notebook": bool(self.notebook.value),
            "can_bring_camera": bool(self.camera.value),
            "tshirt_size": self.size.value,
        }
        if self.friends is not None:
            fields["friends"] = [friend_ref(k) for k in self.friends.value or []]
        return fields
