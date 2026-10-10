"""The roster grid's Tag pills and Tag filter. The grid component itself is
covered by the end-to-end smoke script; here the pure data it is handed: each
Helper's pills (direct and implied) and which Helpers the filter dims. Runs
against a temp-dir workspace seeded with synthetic Helpers (never data/)."""

import pytest

from rostering import tags as tag_tree
from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

CONFIG = [
    {
        "name": "B",
        "rooms": [{"name": "R1", "capacities": {"Zaloha": {"minimum": 0}}}],
        "capacities": {},
    }
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    return Workspace(root=tmp_path / "workspace")


def _helper(helper_id: int, name: str) -> dict:
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
    }


def _new_tag(workspace, name, parent_id=None, colour=None) -> int:
    kwargs = {"colour": colour} if colour else {}
    state = mutations.add_tag(workspace, name, parent_id=parent_id, **kwargs)
    return next(t["id"] for t in state["tags"] if t["name"] == name)


@pytest.fixture
def seeded(workspace):
    """Anna carries 8.M (which implies GCHD), Petr carries GCHD directly, Jana
    carries the unrelated Foto tag, Eva carries nothing."""
    state = workspace.load()
    state["helpers"] = [_helper(i, n) for i, n in enumerate(("Anna", "Petr", "Jana", "Eva"), start=1)]
    workspace.save(state)
    mutations.put_config(workspace, CONFIG)
    ids = {}
    ids["GCHD"] = _new_tag(workspace, "GCHD", colour="#3366cc")
    ids["8.M"] = _new_tag(workspace, "8.M", parent_id=ids["GCHD"], colour="#dc3912")
    ids["Foto"] = _new_tag(workspace, "Foto", colour="#109618")
    mutations.set_helper_tags(workspace, 1, [ids["8.M"]])
    mutations.set_helper_tags(workspace, 2, [ids["GCHD"]])
    mutations.set_helper_tags(workspace, 3, [ids["Foto"]])
    return workspace.load(), ids


# -- the pure filter -------------------------------------------------------------------


def _tags(*rows) -> list[tag_tree.Tag]:
    return [tag_tree.Tag(id=i, name=n, colour="#3366cc", parent_id=p) for i, n, p in rows]


TREE = _tags((1, "GCHD", None), (2, "8.M", 1), (3, "Foto", None))


def test_no_filter_matches_everyone():
    assert tag_tree.matches_filter(TREE, [], [], "all")
    assert tag_tree.matches_filter(TREE, [3], [], "any")


def test_any_of_matches_a_helper_carrying_at_least_one_filtered_tag():
    assert tag_tree.matches_filter(TREE, [3], [1, 3], "any")
    assert not tag_tree.matches_filter(TREE, [], [1, 3], "any")


def test_all_of_needs_every_filtered_tag():
    assert not tag_tree.matches_filter(TREE, [3], [1, 3], "all")
    assert tag_tree.matches_filter(TREE, [2, 3], [1, 3], "all")


def test_an_inherited_tag_counts_as_a_match():
    assert tag_tree.matches_filter(TREE, [2], [1], "any")
    assert tag_tree.matches_filter(TREE, [2], [1], "all")
    # ...but not the other way round: GCHD does not imply 8.M.
    assert not tag_tree.matches_filter(TREE, [1], [2], "any")


def test_a_filtered_tag_that_no_longer_exists_is_ignored():
    assert tag_tree.matches_filter(TREE, [], [99], "all")
    assert tag_tree.matches_filter(TREE, [3], [99, 3], "all")
    assert not tag_tree.matches_filter(TREE, [], [99, 3], "all")


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        tag_tree.matches_filter(TREE, [], [1], "some")


# -- what the grid is handed -----------------------------------------------------------


def test_each_helpers_pills_are_direct_tags_then_implied_ones(seeded):
    state, ids = seeded

    pills = mutations.grid_tag_pills(state)

    assert pills[1] == {
        "direct": [{"name": "8.M", "colour": "#dc3912"}],
        "implied": [{"name": "GCHD", "colour": "#3366cc"}],
    }
    assert pills[2] == {"direct": [{"name": "GCHD", "colour": "#3366cc"}], "implied": []}
    assert pills[4] == {"direct": [], "implied": []}


def test_pills_follow_the_tag_tree_the_moment_it_is_edited(seeded, workspace):
    state, ids = seeded
    mutations.update_tag(workspace, ids["8.M"], parent_id=None)

    assert mutations.grid_tag_pills(workspace.load())[1]["implied"] == []


def test_the_filter_dims_helpers_that_do_not_match_and_never_lists_matches(seeded):
    state, ids = seeded

    assert mutations.dimmed_helper_ids(state, [ids["Foto"]], "any") == [1, 2, 4]


def test_filtering_by_a_parent_tag_finds_helpers_who_carry_only_a_child(seeded):
    state, ids = seeded

    # Anna (8.M, implies GCHD) and Petr (GCHD) match; Jana and Eva are dimmed.
    assert mutations.dimmed_helper_ids(state, [ids["GCHD"]], "any") == [3, 4]


def test_all_of_versus_any_of_over_several_tags(seeded):
    state, ids = seeded
    both = [ids["GCHD"], ids["8.M"]]

    assert mutations.dimmed_helper_ids(state, both, "all") == [2, 3, 4]
    assert mutations.dimmed_helper_ids(state, [ids["Foto"], ids["8.M"]], "any") == [2, 4]


def test_an_empty_filter_dims_nobody(seeded):
    state, _ = seeded

    assert mutations.dimmed_helper_ids(state, [], "all") == []


def test_the_legend_lists_every_tag_on_the_grid_in_tree_order_with_counts(seeded):
    state, ids = seeded

    present = mutations.grid_tags_present(state)

    # Roots alphabetically, a child right after its parent; Anna implies GCHD, Petr carries it directly.
    assert [(t["name"], t["count"], t["direct"]) for t in present] == [
        ("Foto", 1, True),
        ("GCHD", 2, True),
        ("8.M", 1, True),
    ]


def test_a_tag_carried_only_by_implication_is_not_direct_and_an_unused_one_is_left_out(seeded, workspace):
    state, ids = seeded
    mutations.set_helper_tags(workspace, 2, [])  # Petr drops GCHD; only Anna still implies it
    mutations.add_tag(workspace, "Nikdo")

    present = {t["name"]: t for t in mutations.grid_tags_present(workspace.load())}

    assert present["GCHD"]["direct"] is False and present["GCHD"]["count"] == 1
    assert "Nikdo" not in present


def test_the_legend_ignores_people_who_cannot_attend(seeded, workspace):
    state, ids = seeded
    mutations.set_cant_attend(workspace, 3, True, confirmed=True)  # Jana, the only Foto carrier

    assert "Foto" not in [t["name"] for t in mutations.grid_tags_present(workspace.load())]
