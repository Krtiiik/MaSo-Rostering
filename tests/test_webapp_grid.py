"""The roster grid's view model and HTML (rostering.webapp.ui.grid): what the
grid draws is decided in Python, so it is tested here without a browser."""
import json
import re

import pytest

from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations
from rostering.webapp.ui.grid import data, render

CONFIG = [
    {
        "name": "Karlín",
        "capacities": {},
        "rooms": [
            {"name": "K1", "capacities": {"Opravovatel": {"minimum": 0}}},
            {"name": "K2", "capacities": {}},
        ],
    },
    {"name": "Troja", "capacities": {}, "rooms": [{"name": "T1", "capacities": {}}]},
]


def _helper(helper_id, name, **extra):
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": False,
        "can_bring_camera": False,
        "unresolved_friend_names": [],
        **extra,
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    workspace = Workspace()
    state = workspace.load()
    state["helpers"] = [
        _helper(1, "Anna", friends=[2, 3], role_preferences={"Opravovatel": "Ne"}, building_preferences=["Troja"]),
        _helper(2, "Bára", friends=[1], can_bring_camera=True),
        _helper(3, "Cyril"),
        _helper(4, "Dana", cant_attend=True),
        _helper(5, "<Eva & spol.>"),
    ]
    workspace.save(state)
    workspace.create_season("2026-jaro")
    mutations.put_config(workspace, CONFIG, config_path=tmp_path / "buildings-config.yaml")
    mutations.move_helper(workspace, 1, "Karlín", "K1", "Opravovatel")
    mutations.move_helper(workspace, 2, "Karlín", "K1", "Menic")
    mutations.move_helper(workspace, 3, "Troja", "T1", "Menic")
    return workspace


def _view(workspace, overlays=("friends",), tags=(), mode="all"):
    return data.build_view(mutations.get_state(workspace), list(overlays), list(tags), mode)


def test_acceptable_buildings_follow_the_building_preference_set():
    config = [{"name": "Karlín", "rooms": []}, {"name": "Troja", "rooms": []}]
    assert data.acceptable_buildings([], config) == ["Karlín", "Troja"]  # no preference: every Building suits
    assert data.acceptable_buildings(["Troja"], config) == ["Troja"]
    assert data.acceptable_buildings(["Impakt + Troja"], config) == ["Troja"]  # matched like the solver does
    assert data.acceptable_buildings(["Nowhere"], config) == []


def test_the_grid_lists_attending_organizers_and_which_ones_wait_unplaced(workspace):
    placed = mutations.add_organizer(workspace, "Placed")["organizers"][-1]["id"]
    waiting = mutations.add_organizer(workspace, "Waiting")["organizers"][-1]["id"]
    absent = mutations.add_organizer(workspace, "Absent")["organizers"][-1]["id"]
    mutations.assign_organizer(workspace, placed, "VedouciBudovy", "Karlín")
    mutations.set_organizer_cant_attend(workspace, absent, True)
    state = mutations.get_state(workspace)

    listed = data.grid_organizers(state, {}, [waiting], {placed: ["rule broken"]})

    assert [(o["id"], o["placed"], o["dimmed"], o["broken"]) for o in listed] == [
        (placed, True, False, ["rule broken"]),
        (waiting, False, True, []),
    ]


def test_rows_put_the_leadership_slots_first_and_mark_the_organizer_rows():
    rows = data.grid_rows()
    keys = [r.key for r in rows]
    assert keys[:3] == ["VedouciBudovy", "PravaRuka", "VedouciMistnosti"]
    assert keys[-1] == "TechnickaPodpora"
    assert [r.key for r in rows if r.organizer] == ["VedouciBudovy", "PravaRuka", "VedouciMistnosti", "TechnickaPodpora"]
    assert [r.key for r in rows if r.duplicate_drop] == ["UvadeciUcastniku", "FoceniPredavaniCen", "Registrace"]
    assert {r.key for r in rows if r.single_entry} == {"VedouciBudovy", "PravaRuka", "VedouciMistnosti"}


def test_a_helper_who_cannot_attend_is_not_on_the_grid_at_all(workspace):
    view = _view(workspace)
    assert 4 not in view.helpers
    assert "Dana" not in view.helper_names


def test_friend_requests_are_judged_by_shared_room_from_what_each_helper_wrote(workspace):
    view = _view(workspace)
    # Anna named Bára (same Room: K1) and Cyril (Troja): one each way.
    assert view.friend_status[1] == {2: True, 3: False}
    assert view.unsatisfied(1)
    assert not view.unsatisfied(2)
    # Who named Cyril, though he named no one himself.
    assert view.requesters[3] == [1]


def test_satisfaction_borders_follow_the_answers_only_with_their_overlay_on(workspace):
    off = _view(workspace)
    assert off.role_fit(1) is None and off.building_fit(1) is None
    on = _view(workspace, overlays=("role_fit", "building_fit"))
    assert on.role_fit(1) is False  # Anna rated Opravovatel Ne
    assert on.building_fit(1) is False  # and only accepts Troja
    assert on.role_fit(2) is True  # no answer counts as Nevadí
    assert on.building_fit(3) is True  # no preference: every Building


def test_the_tag_filter_dims_only_while_the_tags_overlay_is_on(workspace):
    tag_id = mutations.add_tag(workspace, "Vedoucí")["tags"][-1]["id"]
    mutations.add_tag_to_helpers(workspace, tag_id, [1])
    assert _view(workspace, overlays=("friends",), tags=[tag_id]).dimmed_helper_ids == set()
    assert _view(workspace, overlays=("tags",), tags=[tag_id]).dimmed_helper_ids == {2, 3, 5}


def test_the_card_splits_friends_by_where_they_are(workspace):
    card = data.card_data(_view(workspace), 1)
    assert card["shared"] == ["Bára"]
    assert card["different"] == ["Cyril"]
    assert card["requested_by"] == ["Bára"]
    assert card["placed"] and not card["locked"]
    assert "Záloha" not in [label for label, _ in card["roles"]]


def test_a_typed_additional_role_name_becomes_the_matching_helper_or_stays_text(workspace):
    state = mutations.get_state(workspace)
    manual = data.apply_overlay_set(state, "Registrace", "Karlín", None, ["  anna ", "Host", "Dana", ""])
    entries = [e for e in manual["overlay"] if e["role"] == "Registrace"]
    assert [(e["helper_id"], e["helper_name"]) for e in entries] == [
        (1, None),
        (None, "Host"),
        (None, "Dana"),  # can't attend: stays text, never points a role at her
    ]


def test_the_html_escapes_names_and_carries_what_the_browser_needs(workspace):
    html = render.render(_view(workspace), {})
    assert "<Eva & spol.>" not in html
    assert "&lt;Eva &amp; spol.&gt;" in html
    # Anna's chip: draggable, where she is placed and her friends' status.
    chip = re.search(r'<div [^>]*data-hid="1"[^>]*>', html).group(0)
    assert 'draggable="true"' in chip and 'data-building="Karlín"' in chip and 'data-room="K1"' in chip
    assert 'data-friends="2:1,3:0"' in chip
    assert "unsatisfied" in chip
    # One solver-Role cell per Room and Role, and the Organizer slots take Organizers only.
    assert html.count('data-drop="role"') == 3 * 6
    assert 'data-drop="org"' in html and 'data-drop="dup"' in html


def test_a_merged_row_spans_its_rooms_and_offers_to_split(workspace):
    mutations.set_cell_merges(workspace, "Opravovatel", "Karlín", [["K1", "K2"]], True)
    state = mutations.get_state(workspace)
    html = render.render(_view(workspace), state["cell_merges"])
    merged = re.search(r'<td [^>]*colspan="2"[^>]*data-role="Opravovatel"[^>]*>', html)
    assert merged is not None
    unmerge = re.search(r'class="cell-unmerge-handle"[^>]*data-merge="([^"]*)"', html).group(1)
    assert json.loads(unmerge.replace("&quot;", '"')) == [["K1", "K2"]]
    # Other rows of the same Rooms stay split.
    assert len(re.findall(r'data-role="Menic"', html)) == 3


def test_a_single_holder_slot_takes_no_more_names_once_held(workspace):
    boss = mutations.add_organizer(workspace, "Boss")["organizers"][-1]["id"]
    mutations.assign_organizer(workspace, boss, "VedouciBudovy", "Karlín")
    html = render.render(_view(workspace), {})
    cell = re.search(r'<td [^>]*data-key="VedouciBudovy"[^>]*data-building="Karlín"[^>]*>', html).group(0)
    assert "data-edit" not in cell
    assert re.search(r'data-oid="%d"' % boss, html)


def test_details_card_flipped_above_is_anchored_by_its_bottom_edge():
    from rostering.webapp.ui.grid.card import CURSOR_OFFSET, card_position

    below = card_position(100, 100, 1200, 800)
    assert below.startswith(f"top:{100 + CURSOR_OFFSET}px")
    above = card_position(100, 780, 1200, 800)
    assert above.startswith(f"bottom:{800 - (780 - CURSOR_OFFSET)}px")
