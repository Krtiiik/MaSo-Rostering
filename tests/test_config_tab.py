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


def _unsaved_note(tab):
    return [c.value for c in tab.caption if "Unsaved changes" in c.value]


def test_a_fresh_tab_has_no_unsaved_changes_note(tab):
    assert not tab.exception
    assert _unsaved_note(tab) == []


def test_editing_shows_the_unsaved_note_and_save_config_clears_it(tab):
    tab.number_input(key="w_cost_zaloha").set_value(9).run()
    assert _unsaved_note(tab)

    tab.button(key="save_config").click().run()

    assert not tab.exception
    assert _unsaved_note(tab) == []


def test_save_config_saves_the_solver_settings_too(tab):

    tab.number_input(key="w_cost_zaloha").set_value(9).run()
    tab.number_input(key="w_time_limit").set_value(42).run()
    tab.button(key="save_config").click().run()

    saved = tab.session_state["workspace_state"]["solver_config"]
    assert solver_config_from_dict(saved).role_costs.zaloha == 9
    assert saved["time_limit_seconds"] == 42


def test_editing_the_layout_after_saving_is_unsaved_again(tab):
    tab.button(key="save_config").click().run()
    assert _unsaved_note(tab) == []

    tab.button(key="add_room_0").click().run()

    assert _unsaved_note(tab)
    # The saved layout was not changed through a shared reference.
    draft_rooms = len(tab.session_state["config_draft"][0]["rooms"])
    saved_rooms = len(tab.session_state["workspace_state"]["config"][0]["rooms"])
    assert draft_rooms == saved_rooms + 1
