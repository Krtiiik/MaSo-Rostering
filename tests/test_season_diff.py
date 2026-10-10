"""The list of differences shown when an incoming Season matches a stored one
(``rostering.season_diff``): pure functions of two saved states and the two
sets of Version slugs."""
import copy

from rostering.season_diff import diff_seasons


def _state():
    return {
        "helpers": [
            {"id": 1, "name": "Anna", "email": "a@x.cz", "tshirt_size": "M", "person_id": "p1"},
            {"id": 2, "name": "Petr", "email": "p@x.cz", "tshirt_size": "L", "person_id": "p2"},
        ],
        "organizers": [{"id": 1, "name": "Olga", "person_id": "p3", "building": "B", "room": None}],
        "assignments": [
            {"helper_id": 1, "helper_name": "Anna", "building": "B", "room": "R1", "role": "Opravovatel"},
            {"helper_id": 2, "helper_name": "Petr", "building": "B", "room": "R1", "role": "Zaloha"},
        ],
        "tags": [{"id": 1, "name": "GCHD", "colour": "#ff0000", "note": "", "parent_id": None}],
        "forced_groups": [{"id": 1, "name": "Rodina", "rules": [], "members": []}],
        "config": [{"name": "B", "rooms": [{"name": "R1", "capacities": {}}], "capacities": {}}],
        "manual_roles": {"structural": [], "duplicates": []},
        "solver_config": {"time_limit": 30},
        "cell_merges": {},
        "row_merges": [],
    }


def _by_key(diff):
    return {c["key"]: c for c in diff}


def test_identical_states_and_versions_have_no_differences():
    assert diff_seasons(_state(), _state(), [], []) == []


def test_helpers_added_removed_and_changed_are_listed_by_name():
    local, incoming = _state(), _state()
    incoming["helpers"].append({"id": 3, "name": "Jana", "person_id": "p4"})
    del incoming["helpers"][1]  # Petr
    incoming["helpers"][0]["tshirt_size"] = "XL"
    helpers = _by_key(diff_seasons(local, incoming, [], []))["helpers"]
    assert helpers["added"] == ["Jana"]
    assert helpers["removed"] == ["Petr"]
    assert helpers["changed"] == [{"label": "Anna", "fields": ["tshirt_size"]}]


def test_organizers_tags_and_forced_groups_each_get_a_category():
    local, incoming = _state(), _state()
    incoming["organizers"].append({"id": 2, "name": "Pavel", "person_id": "p9"})
    incoming["tags"][0]["colour"] = "#00ff00"
    incoming["forced_groups"] = []
    diff = _by_key(diff_seasons(local, incoming, [], []))
    assert diff["organizers"]["added"] == ["Pavel"]
    assert diff["tags"]["changed"] == [{"label": "GCHD", "fields": ["colour"]}]
    assert diff["forced_groups"]["removed"] == ["Rodina"]


def test_assignments_are_compared_per_helper():
    local, incoming = _state(), _state()
    incoming["assignments"][0]["room"] = "R2"
    del incoming["assignments"][1]
    assignments = _by_key(diff_seasons(local, incoming, [], []))["assignments"]
    assert assignments["removed"] == ["Petr"]
    assert assignments["changed"] == [{"label": "Anna", "fields": ["room"]}]
    assert assignments["added"] == []


def test_a_changed_lock_is_its_own_category_not_an_assignment_change():
    local, incoming = _state(), _state()
    incoming["assignments"][0]["locked"] = True
    diff = _by_key(diff_seasons(local, incoming, [], []))
    assert "assignments" not in diff
    assert diff["locks"]["changed"] == [{"label": "Anna", "fields": ["locked"]}]


def test_cant_attend_is_a_flag_not_a_helper_edit():
    local, incoming = _state(), _state()
    incoming["helpers"][1]["cant_attend"] = True
    diff = _by_key(diff_seasons(local, incoming, [], []))
    assert "helpers" not in diff
    assert diff["flags"]["changed"] == [{"label": "Petr", "fields": ["cant_attend"]}]


def test_layout_names_added_and_removed_buildings_and_rooms():
    local, incoming = _state(), _state()
    incoming["config"][0]["rooms"].append({"name": "R2", "capacities": {}})
    incoming["config"].append({"name": "C", "rooms": [], "capacities": {}})
    layout = _by_key(diff_seasons(local, incoming, [], []))["layout"]
    assert sorted(layout["added"]) == ["B / R2", "C"]
    assert layout["removed"] == []


def test_a_changed_capacity_is_a_layout_change():
    local, incoming = _state(), _state()
    incoming["config"][0]["rooms"][0]["capacities"] = {"Opravovatel": {"minimum": 2}}
    layout = _by_key(diff_seasons(local, incoming, [], []))["layout"]
    assert layout["changed"] == [{"label": "B / R1", "fields": ["capacities"]}]


def test_versions_present_on_only_one_side_are_listed_by_slug():
    diff = _by_key(diff_seasons(_state(), _state(), ["a", "b"], ["b", "c"]))
    assert diff["versions"]["added"] == ["c"]
    assert diff["versions"]["removed"] == ["a"]


def test_manual_roles_solver_settings_and_merges_are_reported_once_each():
    local, incoming = _state(), _state()
    incoming["manual_roles"]["structural"].append({"role": "VedouciBudovy", "building": "B"})
    incoming["solver_config"]["time_limit"] = 60
    incoming["cell_merges"] = {"Opravovatel": {"B": [["R1", "R2"]]}}
    diff = _by_key(diff_seasons(local, incoming, [], []))
    assert diff["manual_roles"]["changed"] == [{"label": "manual_roles", "fields": []}]
    assert diff["solver_config"]["changed"] == [{"label": "solver_config", "fields": []}]
    assert diff["merges"]["changed"] == [{"label": "cell_merges", "fields": []}]


def test_the_inputs_are_not_modified():
    local, incoming = _state(), _state()
    incoming["helpers"][0]["name"] = "Anička"
    before = copy.deepcopy((local, incoming))
    diff_seasons(local, incoming, [], [])
    assert (local, incoming) == before


def test_categories_come_out_in_a_fixed_order():
    local, incoming = _state(), _state()
    incoming["tags"] = []
    incoming["helpers"][0]["name"] = "X"
    keys = [c["key"] for c in diff_seasons(local, incoming, [], ["v"])]
    assert keys == ["helpers", "tags", "versions"]
