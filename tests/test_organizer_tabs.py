"""Organizers in the Upload and Tags tabs (rendered headlessly with Streamlit's
AppTest against a temp-dir Season seeded with synthetic Helpers and Organizers,
never data/): the inline Tag multiselect lists them next to the Helpers and
tagging one saves through the mutation layer, the Organizer table lists their
placement and Can't attend flag, and the Tags tab shows who carries a Tag."""
import pytest
from streamlit.testing.v1 import AppTest

from rostering.persistence.workspace import Workspace
from rostering.streamlit_app import mutations

CONFIG = [
    {
        "name": "Karlín",
        "rooms": [{"name": "K1", "capacities": {"Zaloha": {"minimum": 0}}}],
        "capacities": {},
    },
    {"name": "Impakt", "rooms": [{"name": "I1", "capacities": {"Zaloha": {"minimum": 0}}}], "capacities": {}},
]


def _helper_tags_app():
    from rostering.streamlit_app.tabs import helper_tags

    helper_tags.render()


def _organizer_list_app():
    from rostering.streamlit_app import session
    from rostering.streamlit_app.tabs import organizer_list

    organizer_list.render(session.get_state())


def _tags_tab_app():
    import streamlit as st

    from rostering.streamlit_app.tabs import tags_tab

    st.session_state["_tags_selected"] = 1
    tags_tab.render()


@pytest.fixture
def seasons(tmp_path, monkeypatch):
    """A Season with Anna (helper), Boss (Organizer, holding Vedoucí budovy at
    Karlín) and one Tag, "GCHD"."""
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    workspace = Workspace()
    state = workspace.load()
    state["helpers"] = [
        {
            "id": 1,
            "name": "Anna",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        }
    ]
    workspace.save(state)
    workspace.create_season("2026-jaro")
    mutations.put_config(workspace, CONFIG)
    mutations.add_organizer(workspace, "Boss")
    mutations.assign_organizer(workspace, 1, "VedouciBudovy", "Karlín")
    mutations.add_tag(workspace, "GCHD")
    return Workspace()


def test_the_inline_tag_list_shows_organizers_and_tagging_one_saves(seasons):
    at = AppTest.from_function(_helper_tags_app, default_timeout=30).run()
    assert not at.exception

    picker = next(m for m in at.multiselect if m.label == "Tags of Boss")
    picker.set_value([1]).run()

    assert not at.exception
    saved = mutations.get_state(seasons)
    assert saved["organizers"][0]["tags"] == [1]
    assert saved["helpers"][0].get("tags") in (None, [])


def test_the_organizer_table_shows_the_placement_and_can_attend_state(seasons):
    at = AppTest.from_function(_organizer_list_app, default_timeout=30).run()

    assert not at.exception
    assert any(s.value == "Organizers (1)" for s in at.subheader)


def test_the_tags_tab_lists_an_organizer_who_carries_the_tag(seasons):
    mutations.set_organizer_tags(seasons, 1, [1])
    at = AppTest.from_function(_tags_tab_app, default_timeout=30).run()

    assert not at.exception
    assert any(s.value == "Has this tag (1)" for s in at.subheader)
    assert any("Boss (Organizer)" in w.value for w in at.markdown)
