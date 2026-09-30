"""Organizers in the People and Tags tabs (rendered headlessly with Streamlit's
AppTest against a temp-dir Season seeded with synthetic Helpers and Organizers,
never data/): the People tab lists them above the Helpers, their popup edits
and tags them through the mutation layer, and the Tags tab shows who carries a Tag."""
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


def _people_tab_app():
    from rostering.streamlit_app.tabs import people_tab

    people_tab.render()


# AppTest reruns the whole script on a widget change and so would not render a
# popup that a button opened; these render a popup's body directly, as the
# fragment a real popup is.
def _organizer_popup_app():
    import streamlit as st

    from rostering.streamlit_app.tabs import person_dialog

    st.fragment(person_dialog._organizer_body)(1)


def _helper_popup_app():
    import streamlit as st

    from rostering.streamlit_app.tabs import person_dialog

    st.fragment(person_dialog._helper_body)(1)


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


def test_the_people_tab_lists_organizers_and_helpers_with_an_open_button_per_row(seasons):
    at = AppTest.from_function(_people_tab_app, default_timeout=30).run()

    assert not at.exception
    assert any(s.value == "Organizátoři (1)" for s in at.subheader)
    assert any(s.value == "Pomocníci (1)" for s in at.subheader)
    labels = [b.label for b in at.button]
    assert labels.count("⚙️") == 2
    assert {"＋ Přidat organizátora", "＋ Přidat pomocníka"} <= set(labels)
    assert not {"Boss", "Anna"} & set(labels)  # a name is plain text, not a button
    assert {"Boss", "Anna"} <= {t.value for t in at.text}


def test_unmatched_friend_names_are_a_button_that_opens_the_popup_on_the_friends_tab(seasons):
    state = mutations.get_state(seasons)
    state["helpers"][0]["unresolved_friend_names"] = ["Terka"]
    seasons.save(state)
    at = AppTest.from_function(_people_tab_app, default_timeout=30).run()

    assert not at.exception
    button = next(b for b in at.button if b.label == "⚠️ k přiřazení: 1")

    button.click().run()

    assert not at.exception
    assert any(t.label == "Kamarádi" for t in at.tabs)  # the popup's tab strip


def test_a_helper_without_unmatched_friend_names_has_no_friends_button(seasons):
    at = AppTest.from_function(_people_tab_app, default_timeout=30).run()

    assert not any("k přiřazení" in b.label for b in at.button)


def _cant_attend_box(at, label):
    return next(c for c in at.checkbox if c.label == label)


def test_the_people_tab_has_a_cant_attend_checkbox_per_person(seasons):
    at = AppTest.from_function(_people_tab_app, default_timeout=30).run()

    assert not at.exception
    assert {c.label for c in at.checkbox} == {"Nemůže se zúčastnit: Boss", "Nemůže se zúčastnit: Anna"}
    assert not any(c.value for c in at.checkbox)


def test_ticking_a_helpers_checkbox_flags_them(seasons):
    at = AppTest.from_function(_people_tab_app, default_timeout=30).run()

    _cant_attend_box(at, "Nemůže se zúčastnit: Anna").check().run()

    assert not at.exception
    assert mutations.get_state(seasons)["helpers"][0]["cant_attend"] is True
    assert _cant_attend_box(at, "Nemůže se zúčastnit: Anna").value is True

    _cant_attend_box(at, "Nemůže se zúčastnit: Anna").uncheck().run()

    assert not at.exception
    assert not mutations.get_state(seasons)["helpers"][0].get("cant_attend")


def test_ticking_a_placed_organizers_checkbox_waits_for_confirmation(seasons):
    at = AppTest.from_function(_people_tab_app, default_timeout=30).run()

    _cant_attend_box(at, "Nemůže se zúčastnit: Boss").check().run()

    assert not at.exception
    assert not mutations.get_state(seasons)["organizers"][0].get("cant_attend")
    assert any(b.label == "Označit jako Nemůže se zúčastnit" for b in at.button)  # the confirmation dialog
    # The table shows what is saved, not the refused tick.
    assert _cant_attend_box(at, "Nemůže se zúčastnit: Boss").value is False


def test_tagging_an_organizer_in_their_popup_saves(seasons):
    at = AppTest.from_function(_organizer_popup_app, default_timeout=30).run()
    assert not at.exception

    next(m for m in at.multiselect if m.label == "Štítky (přímé)").set_value([1]).run()

    assert not at.exception
    saved = mutations.get_state(seasons)
    assert saved["organizers"][0]["tags"] == [1]
    assert saved["helpers"][0].get("tags") in (None, [])


def test_editing_a_helper_in_their_popup_saves(seasons):
    at = AppTest.from_function(_helper_popup_app, default_timeout=30).run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Jméno").set_value("Anna K.").run()
    next(b for b in at.button if b.label == "Uložit změny").click().run()

    assert not at.exception
    assert mutations.get_state(seasons)["helpers"][0]["name"] == "Anna K."


def test_the_add_organizer_form_creates_one(seasons):
    def app():
        from rostering.streamlit_app.tabs import person_dialog

        person_dialog._add_organizer_body()

    at = AppTest.from_function(app, default_timeout=30).run()
    next(t for t in at.text_input if t.label == "Jméno (povinné)").set_value("Nova").run()
    next(b for b in at.button if b.label == "Přidat organizátora").click().run()

    assert not at.exception
    assert [o["name"] for o in mutations.get_state(seasons)["organizers"]] == ["Boss", "Nova"]


def test_the_add_helper_form_creates_one(seasons):
    def app():
        from rostering.streamlit_app.tabs import helper_forms

        helper_forms.render_add_form()

    at = AppTest.from_function(app, default_timeout=30).run()
    next(t for t in at.text_input if t.label == "Jméno (povinné)").set_value("Nova Helper").run()
    next(t for t in at.text_input if t.label == "Kontakt (povinný)").set_value("nova@example.com").run()
    next(b for b in at.button if b.label == "Přidat pomocníka").click().run()

    assert not at.exception
    assert [h["name"] for h in mutations.get_state(seasons)["helpers"]] == ["Anna", "Nova Helper"]


def test_deleting_a_helper_in_their_popup_removes_them(seasons):
    at = AppTest.from_function(_helper_popup_app, default_timeout=30).run()
    next(b for b in at.button if b.label == "Smazat pomocníka").click().run()

    assert not at.exception
    assert mutations.get_state(seasons)["helpers"] == []


def test_the_friend_names_tab_lists_the_names_a_helper_wrote(seasons):
    state = seasons.load()
    state["helpers"][0]["unresolved_friend_names"] = ["Terka"]
    state["helpers"][0]["friend_name_order"] = ["Terka"]
    seasons.save(state)

    at = AppTest.from_function(_helper_popup_app, default_timeout=30).run()

    assert not at.exception
    assert any("Terka" in w.value for w in at.markdown)


def test_the_tags_tab_lists_an_organizer_who_carries_the_tag(seasons):
    mutations.set_organizer_tags(seasons, 1, [1])
    at = AppTest.from_function(_tags_tab_app, default_timeout=30).run()

    assert not at.exception
    assert any(s.value == "Kdo štítek nese (1)" for s in at.subheader)
    assert at.multiselect(key="tag_people_1_0").value == ["o1"]
    assert "Boss (organizátor)" in at.multiselect(key="tag_people_1_0").options


def test_the_tags_tab_multiselect_adds_and_removes_carriers_in_one_save(seasons):
    mutations.set_organizer_tags(seasons, 1, [1])
    at = AppTest.from_function(_tags_tab_app, default_timeout=30).run()

    at.multiselect(key="tag_people_1_0").set_value(["h1"]).run()
    at.button(key="tag_people_save_1").click().run()

    assert not at.exception
    state = mutations.get_state(seasons)
    assert mutations.helper_tags(state, 1)["direct"] == [1]
    assert mutations.organizer_tags(state, 1)["direct"] == []
    assert any(s.value == "Kdo štítek nese (1)" for s in at.subheader)
