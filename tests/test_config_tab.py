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


def _unsaved_note(tab):
    return [c.value for c in tab.caption if "Unsaved changes" in c.value]


def test_a_fresh_tab_has_no_unsaved_changes_note(tab):
    assert not tab.exception
    assert _unsaved_note(tab) == []


def test_editing_shows_the_unsaved_note_and_save_config_clears_it(tab):
    tab.button(key="add_building").click().run()
    assert _unsaved_note(tab)

    tab.button(key="save_config").click().run()

    assert not tab.exception
    assert _unsaved_note(tab) == []


def test_editing_the_layout_after_saving_is_unsaved_again(tab):
    tab.button(key="save_config").click().run()
    assert _unsaved_note(tab) == []

    tab.button(key="add_room_0").click().run()

    assert _unsaved_note(tab)
    # The saved layout was not changed through a shared reference.
    draft_rooms = len(tab.session_state["config_draft"][0]["rooms"])
    saved_rooms = len(tab.session_state["workspace_state"]["config"][0]["rooms"])
    assert draft_rooms == saved_rooms + 1
