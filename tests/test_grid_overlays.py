"""The Roster tab's Overlays pills and the Tag filter they gate (rendered headlessly with AppTest)."""
from streamlit.testing.v1 import AppTest

# (grid_tab registers the grid component on import, which needs the Streamlit
# runtime, so the app function imports it, not this module.)
_OVERLAYS_KEY = "_grid_overlays"
_TAG_FILTER_KEY = "_grid_tag_filter"
_STATE = {"tags": [{"id": 1, "name": "Vedoucí", "colour": "#ff0000", "note": "", "parent_id": None}]}


def _app():
    import streamlit as st

    from rostering.streamlit_app.tabs import grid_tab
    from tests.test_grid_overlays import _STATE

    overlays, filter_ids, mode = grid_tab._render_overlay_controls(_STATE)
    st.session_state["_result"] = (overlays, filter_ids, mode)


def _run(overlays=None) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    if overlays is not None:
        at.session_state[_OVERLAYS_KEY] = overlays
    return at.run()


def _filter_shown(at: AppTest) -> bool:
    return any(m.label == "Filtrovat podle štítků" for m in at.multiselect)


def test_friends_is_on_to_begin_with_and_the_tag_filter_is_hidden():
    at = _run()

    assert not at.exception
    assert at.session_state["_result"][0] == ["friends"]
    assert not _filter_shown(at)


def test_the_tags_overlay_shows_the_tag_filter():
    at = _run(["friends", "tags"])

    assert not at.exception
    assert at.session_state["_result"][0] == ["friends", "tags"]
    assert _filter_shown(at)


def test_the_filter_dims_no_one_while_tags_is_off():
    at = _run(["friends"])
    at.session_state[_TAG_FILTER_KEY] = [1]
    at.run()

    assert at.session_state["_result"][1] == []


def test_no_overlay_selected_means_plain_chips():
    at = _run([])

    assert not at.exception
    assert at.session_state["_result"][0] == []
