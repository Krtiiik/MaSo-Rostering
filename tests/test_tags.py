"""Tags: the per-Season tree of named, coloured labels, tagging Helpers with
them, and the effective (direct plus implied) Tags computed live from the tree.
Mutation-layer tests run against a temp-dir workspace seeded with synthetic
Helpers (never anything from data/)."""
import importlib
import io
from datetime import datetime

import pandas as pd
import pytest

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
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return Workspace(root=tmp_path / "workspace")


def _helper(helper_id: int, name: str, **extra) -> dict:
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": True,
        "can_bring_camera": True,
        "unresolved_friend_names": [],
        **extra,
    }


def _seed(workspace: Workspace, names=("Anna", "Petr", "Jana", "Eva")) -> None:
    state = workspace.load()
    state["helpers"] = [_helper(i, name) for i, name in enumerate(names, start=1)]
    workspace.save(state)
    mutations.put_config(workspace, CONFIG)


def _new_tag(workspace, name, parent_id=None, **kwargs) -> int:
    """Create a Tag and return its id."""
    state = mutations.add_tag(workspace, name, parent_id=parent_id, **kwargs)
    return next(t["id"] for t in state["tags"] if t["name"] == name)


def _direct(state, helper_id) -> list[int]:
    return mutations.helper_tags(state, helper_id)["direct"]


def _implied(state, helper_id) -> list[int]:
    return mutations.helper_tags(state, helper_id)["implied"]


# -- creating Tags ---------------------------------------------------------------


def test_a_new_tag_has_a_name_colour_and_note_and_no_parent(workspace):
    _seed(workspace)

    state = mutations.add_tag(workspace, "GCHD", colour="#3366cc", note="Gymnázium Christiana Dopplera")

    (tag,) = state["tags"]
    assert (tag["name"], tag["colour"], tag["note"], tag["parent_id"]) == (
        "GCHD",
        "#3366cc",
        "Gymnázium Christiana Dopplera",
        None,
    )
    assert mutations.get_state(workspace)["tags"] == state["tags"]  # persisted


def test_a_tag_gets_a_colour_of_its_own_when_none_is_given(workspace):
    _seed(workspace)
    mutations.add_tag(workspace, "A")
    state = mutations.add_tag(workspace, "B")

    first, second = state["tags"]
    assert first["colour"] and second["colour"] and first["colour"] != second["colour"]


def test_a_tag_needs_a_name(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError, match="název"):
        mutations.add_tag(workspace, "   ")

    assert mutations.get_state(workspace)["tags"] == []


def test_tag_names_are_unique_ignoring_case_and_surrounding_spaces(workspace):
    _seed(workspace)
    mutations.add_tag(workspace, "GCHD")

    with pytest.raises(mutations.RosteringError, match="už existuje"):
        mutations.add_tag(workspace, "  gchd ")

    assert len(mutations.get_state(workspace)["tags"]) == 1


def test_a_tag_colour_must_be_a_hex_colour(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError, match="Barva"):
        mutations.add_tag(workspace, "GCHD", colour="blue")


# -- the tree: parents, editing, cycles ---------------------------------------------


def test_a_tag_may_imply_one_parent_tag(workspace):
    _seed(workspace)
    gchd = _new_tag(workspace, "GCHD")

    state = mutations.add_tag(workspace, "8.M", parent_id=gchd)

    child = next(t for t in state["tags"] if t["name"] == "8.M")
    assert child["parent_id"] == gchd


def test_a_parent_must_be_an_existing_tag(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError, match="Takový štítek neexistuje"):
        mutations.add_tag(workspace, "8.M", parent_id=99)


def _tag(state, tag_id) -> dict:
    return next(t for t in state["tags"] if t["id"] == tag_id)


def test_editing_a_tag_changes_only_the_fields_given(workspace):
    _seed(workspace)
    gchd = _new_tag(workspace, "GCHD", colour="#3366cc", note="old")
    other = _new_tag(workspace, "Other")

    state = mutations.update_tag(workspace, gchd, name="Gymnázium", note="new", parent_id=other)

    tag = _tag(state, gchd)
    assert (tag["name"], tag["colour"], tag["note"], tag["parent_id"]) == ("Gymnázium", "#3366cc", "new", other)
    # Leaving the parent out keeps it; asking for None makes the Tag a root.
    assert _tag(mutations.update_tag(workspace, gchd, note="x"), gchd)["parent_id"] == other
    assert _tag(mutations.update_tag(workspace, gchd, parent_id=None), gchd)["parent_id"] is None


def test_renaming_a_tag_keeps_names_unique_but_lets_it_keep_its_own(workspace):
    _seed(workspace)
    gchd = _new_tag(workspace, "GCHD")
    _new_tag(workspace, "8.M")

    with pytest.raises(mutations.RosteringError, match="už existuje"):
        mutations.update_tag(workspace, gchd, name="8.m")

    mutations.update_tag(workspace, gchd, name="gchd")  # its own name in another case is fine
    assert _tag(mutations.get_state(workspace), gchd)["name"] == "gchd"


def test_a_tag_cannot_imply_itself(workspace):
    _seed(workspace)
    gchd = _new_tag(workspace, "GCHD")

    with pytest.raises(mutations.RosteringError, match="předkem"):
        mutations.update_tag(workspace, gchd, parent_id=gchd)


def test_a_tag_cannot_be_given_one_of_its_own_descendants_as_parent(workspace):
    _seed(workspace)
    a = _new_tag(workspace, "A")
    b = _new_tag(workspace, "B", parent_id=a)
    c = _new_tag(workspace, "C", parent_id=b)

    with pytest.raises(mutations.RosteringError, match="předkem"):
        mutations.update_tag(workspace, a, parent_id=c)

    assert _tag(mutations.get_state(workspace), a)["parent_id"] is None  # nothing changed
    mutations.update_tag(workspace, c, parent_id=a)  # moving it up a level is fine


# -- tagging Helpers, effective Tags ---------------------------------------------------


def _tree(workspace):
    """GCHD <- 8.M <- 8.M-lab, plus an unrelated root; returns their ids."""
    gchd = _new_tag(workspace, "GCHD")
    eightm = _new_tag(workspace, "8.M", parent_id=gchd)
    lab = _new_tag(workspace, "8.M-lab", parent_id=eightm)
    other = _new_tag(workspace, "Photographers")
    return gchd, eightm, lab, other


def test_a_helper_carries_the_tags_assigned_to_them_directly(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)

    state = mutations.set_helper_tags(workspace, 1, [eightm, other])

    assert _direct(state, 1) == [eightm, other]
    assert _direct(mutations.get_state(workspace), 1) == [eightm, other]  # persisted
    assert _direct(state, 2) == []


def test_effective_tags_are_the_direct_ones_plus_every_ancestor(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)

    state = mutations.set_helper_tags(workspace, 1, [lab, other])

    tags = mutations.helper_tags(state, 1)
    assert tags["direct"] == [lab, other]
    assert tags["implied"] == [eightm, gchd]  # nearest ancestor first
    assert tags["effective"] == [lab, other, eightm, gchd]


def test_a_tag_that_is_both_direct_and_implied_counts_as_direct(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)

    state = mutations.set_helper_tags(workspace, 1, [lab, gchd])

    tags = mutations.helper_tags(state, 1)
    assert tags["direct"] == [lab, gchd]
    assert tags["implied"] == [eightm]


def test_effective_tags_follow_the_tree_the_moment_it_is_edited(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm])
    assert _implied(mutations.get_state(workspace), 1) == [gchd]

    state = mutations.update_tag(workspace, eightm, parent_id=other)

    assert _implied(state, 1) == [other]
    # ... and nothing was ever copied onto the Helper, so a Helper record
    # holds only the direct Tag.
    assert next(h for h in state["helpers"] if h["id"] == 1)["tags"] == [eightm]


def test_setting_a_helpers_tags_replaces_them_and_ignores_repeats(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm, other])

    state = mutations.set_helper_tags(workspace, 1, [gchd, gchd])

    assert _direct(state, 1) == [gchd]
    assert _direct(mutations.set_helper_tags(workspace, 1, []), 1) == []


def test_tagging_refuses_an_unknown_helper_or_tag_and_changes_nothing(workspace):
    _seed(workspace)
    gchd, *_ = _tree(workspace)

    with pytest.raises(mutations.RosteringError, match="Takový pomocník neexistuje"):
        mutations.set_helper_tags(workspace, 99, [gchd])
    with pytest.raises(mutations.RosteringError, match="Takový štítek neexistuje"):
        mutations.set_helper_tags(workspace, 1, [gchd, 99])

    assert _direct(mutations.get_state(workspace), 1) == []


def test_adding_a_tag_to_several_helpers_keeps_what_they_already_carry(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 2, [other])

    state = mutations.add_tag_to_helpers(workspace, eightm, [1, 2, 3])

    assert _direct(state, 1) == [eightm]
    assert _direct(state, 2) == [other, eightm]
    assert _direct(state, 3) == [eightm]
    assert _direct(state, 4) == []
    # Adding again is harmless.
    assert _direct(mutations.add_tag_to_helpers(workspace, eightm, [1]), 1) == [eightm]


def test_removing_a_tag_from_a_helper_drops_only_the_direct_tag(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm, other])

    state = mutations.remove_tag_from_helper(workspace, eightm, 1)

    assert _direct(state, 1) == [other]
    assert _implied(state, 1) == []


def test_a_tags_carriers_are_everyone_with_it_directly_or_through_a_child_tag(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [gchd])
    mutations.set_helper_tags(workspace, 2, [eightm])
    state = mutations.set_helper_tags(workspace, 3, [lab])

    carriers = mutations.tag_carriers(state, gchd)

    assert [(c["name"], c["via"]) for c in carriers] == [("Anna", None), ("Jana", lab), ("Petr", eightm)]
    assert mutations.tag_carriers(state, other) == []


def test_helper_counts_include_helpers_who_carry_a_tag_by_implication(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm])
    state = mutations.set_helper_tags(workspace, 2, [lab])

    assert mutations.tag_helper_counts(state) == {gchd: 2, eightm: 2, lab: 1, other: 0}


# -- deleting a Tag ---------------------------------------------------------------------


def test_deleting_a_tag_nobody_uses_needs_no_confirmation(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)

    state = mutations.delete_tag(workspace, other)

    assert [t["name"] for t in state["tags"]] == ["GCHD", "8.M", "8.M-lab"]
    assert mutations.tag_delete_impact(mutations.get_state(workspace), lab) == {
        "helpers": [],
        "organizers": [],
        "children": [],
    }


def test_deleting_a_tag_in_use_warns_first_naming_the_helpers_and_child_tags(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm])
    mutations.set_helper_tags(workspace, 2, [eightm, other])
    state = mutations.set_helper_tags(workspace, 3, [lab])  # carries 8.M only by implication

    impact = mutations.tag_delete_impact(state, eightm)
    assert impact["helpers"] == ["Anna", "Petr"]  # who it is stripped from
    assert impact["children"] == ["8.M-lab"]

    with pytest.raises(mutations.ConfirmationRequired) as raised:
        mutations.delete_tag(workspace, eightm)

    warning = " ".join(raised.value.lines)
    assert "Anna" in warning and "Petr" in warning and "8.M-lab" in warning
    assert "Jana" not in warning  # a Helper who only has a child Tag keeps everything they were given
    assert [t["name"] for t in mutations.get_state(workspace)["tags"]] == ["GCHD", "8.M", "8.M-lab", "Photographers"]
    assert _direct(mutations.get_state(workspace), 1) == [eightm]  # nothing changed


def test_confirming_the_delete_strips_the_tag_and_reparents_its_children_to_its_parent(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm, other])
    state = mutations.set_helper_tags(workspace, 2, [lab])

    state = mutations.delete_tag(workspace, eightm, confirmed=True)

    assert eightm not in [t["id"] for t in state["tags"]]
    assert _tag(state, lab)["parent_id"] == gchd  # 8.M's parent takes over its child
    assert _direct(state, 1) == [other]
    assert _direct(state, 2) == [lab]
    assert _implied(state, 2) == [gchd]  # still implied, now straight from GCHD
    assert mutations.get_state(workspace)["tags"] == state["tags"]


def test_deleting_a_root_tag_makes_its_children_roots(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)

    state = mutations.delete_tag(workspace, gchd, confirmed=True)

    assert _tag(state, eightm)["parent_id"] is None
    assert _tag(state, lab)["parent_id"] == eightm


def test_a_deleted_tags_id_is_not_handed_to_a_new_tag(workspace):
    _seed(workspace)
    gchd, eightm, lab, other = _tree(workspace)
    mutations.delete_tag(workspace, other)

    assert _new_tag(workspace, "New") > other


def test_deleting_an_unknown_tag_is_refused(workspace):
    _seed(workspace)

    with pytest.raises(mutations.RosteringError, match="Takový štítek neexistuje"):
        mutations.delete_tag(workspace, 42)


# -- the Season's lifecycle -------------------------------------------------------------


def test_tags_and_assignments_are_saved_in_versions_and_restored_with_them(workspace):
    _seed(workspace)
    workspace.create_season("2026-jaro")
    gchd, eightm, lab, other = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm])
    version = mutations.save_version(workspace, "tagged")
    mutations.delete_tag(workspace, eightm, confirmed=True)
    mutations.add_tag(workspace, "Later")
    mutations.set_helper_tags(workspace, 2, [gchd])

    restored = mutations.restore_version(workspace, version["slug"])

    assert [t["name"] for t in restored["tags"]] == ["GCHD", "8.M", "8.M-lab", "Photographers"]
    assert _direct(restored, 1) == [eightm]
    assert _direct(restored, 2) == []
    assert _implied(restored, 1) == [gchd]


def test_start_over_clears_the_tags(workspace):
    _seed(workspace)
    workspace.create_season("2026-jaro")
    _, eightm, *_ = _tree(workspace)
    mutations.set_helper_tags(workspace, 1, [eightm])

    state = mutations.reset_workspace(workspace)

    assert state["tags"] == []
    assert state["helpers"] == []


def test_a_state_saved_before_tags_existed_has_none(workspace):
    _seed(workspace)
    state = workspace.load()
    state.pop("tags", None)
    workspace.save(state)

    assert mutations.tag_helper_counts(mutations.get_state(workspace)) == {}
    assert mutations.helper_tags(mutations.get_state(workspace), 1) == {"direct": [], "implied": [], "effective": []}
    assert _tag_names(mutations.add_tag(workspace, "GCHD")) == ["GCHD"]  # and one can be added


def _tag_names(state) -> list[str]:
    return [t["name"] for t in state["tags"]]


def test_each_season_has_its_own_tags(workspace):
    _seed(workspace)
    workspace.create_season("2025-podzim")
    mutations.add_tag(workspace, "GCHD")

    mutations.new_season(workspace)
    state = mutations.upload_responses(workspace, _survey([("Anna", "anna@example.test")]), "s.xlsx", label="2026-jaro")

    assert state["tags"] == []
    assert _tag_names(mutations.open_season(workspace, mutations.list_seasons(workspace)[1]["id"])) == ["GCHD"]


_NAME = "Tvoje jméno a příjmení"
_EMAIL = "E-mailová adresa"


def _survey(rows) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "Časová značka": [datetime(2026, 2, 1)] * len(rows),
            _NAME: [name for name, _ in rows],
            _EMAIL: [email for _, email in rows],
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


def test_tags_survive_a_re_upload_even_when_the_rows_change_position(workspace):
    state = mutations.upload_responses(
        workspace,
        _survey([("Anna Nováková", "anna@example.test"), ("Petr Svoboda", "petr@example.test")]),
        "s.xlsx",
        label="2026-jaro",
    )
    gchd = _new_tag(workspace, "GCHD")
    eightm = _new_tag(workspace, "8.M", parent_id=gchd)
    anna = next(h["id"] for h in state["helpers"] if h["name"] == "Anna Nováková")
    mutations.set_helper_tags(workspace, anna, [eightm])

    state = mutations.upload_responses(
        workspace,
        _survey([("Petr Svoboda", "petr@example.test"), ("Anna Nováková", "anna@example.test")]),
        "s.xlsx",
    )

    assert _tag_names(state) == ["GCHD", "8.M"]
    by_name = {h["name"]: h["id"] for h in state["helpers"]}
    assert _direct(state, by_name["Anna Nováková"]) == [eightm]
    assert _implied(state, by_name["Anna Nováková"]) == [gchd]
    assert _direct(state, by_name["Petr Svoboda"]) == []
