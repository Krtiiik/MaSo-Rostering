"""Matching a Helper's Building preference to the configured Buildings."""
from __future__ import annotations

import pytest

from rostering import building_prefs
from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations
from rostering.webapp.mutations import RosteringError


def _building(name: str) -> dict:
    return {"name": name, "rooms": [{"name": "R1", "capacities": {}}], "capacities": {}}


def test_match_ignores_case_and_diacritics():
    assert building_prefs.match_buildings("Malá Strana", ["Mala Strana", "Karlov"]) == ["Mala Strana"]


def test_match_uses_aliases_both_ways():
    assert building_prefs.match_buildings("Karlín", ["Křižíkova", "Karlov"]) == ["Křižíkova"]
    assert building_prefs.match_buildings("Impakt + Troja", ["Impakt", "Troja", "Karlov"]) == ["Impakt", "Troja"]
    assert building_prefs.match_buildings("Troja", ["Impakt + Troja"]) == ["Impakt + Troja"]


def test_match_by_substring():
    assert building_prefs.match_buildings("Nové Město", ["Nové Město (Vinohrady)", "Karlov"]) == ["Nové Město (Vinohrady)"]
    assert building_prefs.match_buildings("Vinohrady NM budova", ["NM", "Karlov"]) == []  # too short to trust
    assert building_prefs.match_buildings("Neznámá", ["Karlov"]) == []


def test_resolve_prefers_exact_then_decision_then_match():
    names = ["Mala Strana", "Troja", "Impakt"]
    decisions = {"Dejvice": ["Troja", "Gone"]}
    out = building_prefs.resolve_preferences(["Mala Strana", "Malá Strana", "Dejvice", "Nic"], names, decisions)
    assert out == ["Mala Strana", "Nic", "Troja"]


def test_resolve_with_no_layout_changes_nothing():
    assert building_prefs.resolve_preferences(["Malá Strana"], []) == ["Malá Strana"]


def _state(prefs: list[list[str]], config: list[str]) -> dict:
    return {
        "config": [_building(n) for n in config],
        "helpers": [{"id": i, "name": f"H{i}", "building_preferences": p} for i, p in enumerate(prefs, 1)],
    }


def test_reconcile_and_unresolved():
    state = _state([["Malá Strana", "Impakt + Troja"], ["Dejvice"]], ["Mala Strana", "Troja"])
    assert building_prefs.reconcile(state) is True
    assert state["helpers"][0]["building_preferences"] == ["Mala Strana", "Troja"]
    assert state["helpers"][1]["building_preferences"] == ["Dejvice"]
    assert building_prefs.unresolved(state) == [{"name": "Dejvice", "helpers": ["H2"]}]
    assert building_prefs.reconcile(state) is False


def test_no_offers_without_a_layout():
    assert building_prefs.unresolved(_state([["Dejvice"]], [])) == []


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    ws = Workspace(tmp_path / "ws")
    return ws


def test_layout_change_rewrites_preferences_and_resolution_is_kept(workspace, tmp_path):
    state = workspace.load()
    state["helpers"] = [
        {"id": 1, "name": "Anna", "building_preferences": ["Malá Strana", "Dejvice"]},
    ]
    workspace.create_season("2026-jaro", state)
    mutations.put_config(workspace, [_building("Mala Strana"), _building("Nove")], config_path=tmp_path / "c.yaml")
    state = workspace.load()
    assert state["helpers"][0]["building_preferences"] == ["Dejvice", "Mala Strana"]
    offers = mutations.get_building_match_offers(workspace)
    assert [o["name"] for o in offers] == ["Dejvice"]
    assert offers[0]["candidates"] == ["Mala Strana", "Nove"]

    with pytest.raises(RosteringError):
        mutations.match_building(workspace, "Dejvice", [])
    mutations.match_building(workspace, "Dejvice", ["Nove"])
    assert workspace.load()["helpers"][0]["building_preferences"] == ["Mala Strana", "Nove"]
    assert mutations.get_building_match_offers(workspace) == []
