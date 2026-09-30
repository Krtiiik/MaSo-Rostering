"""The Buildings tab (rendered headlessly with Streamlit's AppTest)."""
import pytest
from streamlit.testing.v1 import AppTest


def _app():
    from rostering.streamlit_app.tabs import config_tab

    config_tab.render()


@pytest.fixture
def tab(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    return AppTest.from_function(_app, default_timeout=30).run()


def test_add_building_button_appends_a_uniquely_named_building(tab):
    before = len(tab.session_state["config_draft"])

    tab.button(key="add_building").click().run()
    tab.button(key="add_building").click().run()

    assert not tab.exception
    names = [b["name"] for b in tab.session_state["config_draft"]]
    assert len(names) == before + 2
    assert len(set(names)) == len(names)
    assert tab.session_state["config_draft"][-1]["rooms"] == []
