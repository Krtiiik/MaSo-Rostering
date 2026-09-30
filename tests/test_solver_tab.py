"""The solver tab's role cost fields (rendered headlessly with Streamlit's AppTest)."""
import pytest
from streamlit.testing.v1 import AppTest

from rostering.persistence.serialize import solver_config_from_dict, solver_config_to_dict
from rostering.solver.model import MAX_PREFERENCE_COST, SolverConfig


def _app():
    from rostering.streamlit_app.tabs import solver_tab

    solver_tab.render()


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
        widget = tab.number_input(key=key) if field == "zaloha" else tab.slider(key=key)
        assert widget.value == getattr(defaults.role_costs, field)


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


def test_the_five_preference_costs_are_sliders_from_zero_to_the_fixed_maximum(tab):
    for field in ("ano", "klidne", "nevadi", "spise_ne", "ne"):
        slider = tab.slider(key=_COST_KEYS[field])
        assert (slider.min, slider.max, slider.step) == (0, MAX_PREFERENCE_COST, 1)
    assert MAX_PREFERENCE_COST == 20
    assert not [n for n in tab.number_input if n.key in {_COST_KEYS[f] for f in _COST_KEYS if f != "zaloha"}]

    tab.slider(key="w_cost_ne").set_value(20).run()

    assert solver_config_from_dict(tab.session_state["solver_config_draft"]).role_costs.ne == 20


def test_a_saved_cost_above_the_maximum_is_shown_at_the_top_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state["solver_config_draft"] = {
        **solver_config_to_dict(SolverConfig()),
        "role_costs": {**solver_config_to_dict(SolverConfig())["role_costs"], "ne": 99},
    }
    at.run()

    assert not at.exception
    assert at.slider(key="w_cost_ne").value == MAX_PREFERENCE_COST
