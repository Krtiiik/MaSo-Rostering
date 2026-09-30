"""The config tab's role cost fields (rendered headlessly with Streamlit's AppTest)."""
import pytest
from streamlit.testing.v1 import AppTest

from rostering.persistence.serialize import solver_config_from_dict
from rostering.solver.model import SolverConfig


def _app():
    from rostering.streamlit_app.tabs import config_tab

    config_tab.render()


@pytest.fixture
def tab(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    return AppTest.from_function(_app, default_timeout=30).run()


_COST_KEYS = {
    "ano": "w_cost_ano",
    "klidne": "w_cost_klidne",
    "nevadi": "w_cost_nevadi",
    "zaloha": "w_cost_zaloha",
    "spise_ne": "w_cost_spise_ne",
    "ne": "w_cost_ne",
}


def test_the_tab_shows_the_unit_and_six_costs_with_the_solver_defaults(tab):
    defaults = SolverConfig()

    assert not tab.exception
    assert tab.number_input(key="w_role_cost_unit").value == defaults.weights.role_preference
    for field, key in _COST_KEYS.items():
        assert tab.number_input(key=key).value == getattr(defaults.role_costs, field)


def test_add_building_button_appends_a_uniquely_named_building(tab):
    before = len(tab.session_state["config_draft"])

    tab.button(key="add_building").click().run()
    tab.button(key="add_building").click().run()

    assert not tab.exception
    names = [b["name"] for b in tab.session_state["config_draft"]]
    assert len(names) == before + 2
    assert len(set(names)) == len(names)
    assert tab.session_state["config_draft"][-1]["rooms"] == []


def test_editing_the_fields_updates_the_draft_and_restore_defaults_undoes_it(tab):
    tab.number_input(key="w_role_cost_unit").set_value(3).run()
    tab.number_input(key="w_cost_zaloha").set_value(9).run()

    edited = solver_config_from_dict(tab.session_state["solver_config_draft"])
    assert edited.weights.role_preference == 3
    assert edited.role_costs.zaloha == 9

    tab.button(key="w_restore_role_costs").click().run()

    assert not tab.exception
    assert solver_config_from_dict(tab.session_state["solver_config_draft"]) == SolverConfig()
    assert tab.number_input(key="w_role_cost_unit").value == 1
    assert tab.number_input(key="w_cost_zaloha").value == 4
