"""Stored Seasons and the open Workspace, exercised through the mutation layer
against a temp-dir workspace with synthetic data (no real ``data/`` is ever
read or written)."""
import importlib
import io
import json
from datetime import datetime

import pandas as pd
import pytest

from rostering.persistence.workspace import Workspace
from rostering.streamlit_app import mutations

_NAME_HEADER = "Tvoje jméno a příjmení"

SMALL_CONFIG = [
    {
        "name": "B",
        "rooms": [{"name": "R1", "capacities": {"Opravovatel": {"minimum": 0}, "Zaloha": {"minimum": 0}}}],
        "capacities": {},
    }
]
OTHER_CONFIG = [{"name": "Z", "rooms": [{"name": "Q1", "capacities": {}}], "capacities": {}}]


@pytest.fixture
def seasons_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)
    return tmp_path / "seasons"


@pytest.fixture
def workspace(seasons_root):
    return Workspace(root=seasons_root)


def _survey(names, stamps=None, header="Časová značka") -> bytes:
    data = {_NAME_HEADER: names}
    if stamps is not None:
        data = {header: stamps, **data}
    buffer = io.BytesIO()
    pd.DataFrame(data).to_excel(buffer, index=False)
    return buffer.getvalue()


def _jaro_survey(names=("Anna", "Petr")) -> bytes:
    return _survey(list(names), [datetime(2026, 2, 1 + i) for i in range(len(names))])


def _podzim_survey(names=("Anna", "Petr")) -> bytes:
    return _survey(list(names), [datetime(2025, 9, 1 + i) for i in range(len(names))])


def _create(workspace, label, names=("Anna", "Petr")):
    return mutations.upload_responses(workspace, _survey(list(names)), "s.xlsx", label=label)


def _ids_by_label(workspace):
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


# -- creating a Season on upload ---------------------------------------------


def test_fresh_workspace_has_no_seasons_and_none_open(workspace, seasons_root):
    assert mutations.list_seasons(workspace) == []
    assert mutations.get_open_season(workspace) is None
    assert mutations.get_state(workspace)["helpers"] == []
    assert mutations.list_versions(workspace) == []
    # Nothing but the (empty) root exists: no Season, nothing personal.
    assert list(seasons_root.iterdir()) == []


def test_upload_with_no_season_open_creates_and_opens_a_season(workspace):
    state = _create(workspace, "2026-jaro")
    assert [h["name"] for h in state["helpers"]] == ["Anna", "Petr"]
    assert state["season"]["label"] == "2026-jaro"

    seasons = mutations.list_seasons(workspace)
    assert len(seasons) == 1
    assert seasons[0]["label"] == "2026-jaro"
    assert seasons[0]["helper_count"] == 2
    assert seasons[0]["open"] is True
    assert mutations.get_open_season(workspace) == {"id": seasons[0]["id"], "label": "2026-jaro"}


def test_created_season_is_stored_and_reopened_by_a_fresh_workspace(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    again = Workspace(root=seasons_root)  # e.g. after an app restart
    assert mutations.get_open_season(again)["label"] == "2026-jaro"
    assert [h["name"] for h in mutations.get_state(again)["helpers"]] == ["Anna", "Petr"]


def test_upload_prefills_the_label_from_submission_timestamps(workspace):
    state = mutations.upload_responses(workspace, _jaro_survey(), "s.xlsx")
    assert state["season"]["label"] == "2026-jaro"


@pytest.mark.parametrize(
    "stamps, expected",
    [
        ([datetime(2026, 1, 3), datetime(2026, 1, 20)], "2026-jaro"),
        ([datetime(2026, 6, 30)], "2026-jaro"),
        ([datetime(2025, 7, 1)], "2025-podzim"),
        ([datetime(2025, 12, 31)], "2025-podzim"),
        # The median submission decides, so late stragglers don't flip it.
        ([datetime(2026, 2, 1)] * 5 + [datetime(2026, 8, 1)], "2026-jaro"),
    ],
)
def test_suggested_label_is_year_plus_jaro_or_podzim(stamps, expected):
    survey = _survey([f"H{i}" for i in range(len(stamps))], stamps)
    assert mutations.suggest_season_label(survey, "s.xlsx") == expected


def test_suggested_label_is_none_when_timestamps_cannot_be_read():
    assert mutations.suggest_season_label(_survey(["Anna"]), "s.xlsx") is None
    unreadable = _survey(["Anna", "Petr"], ["soon", "later"])
    assert mutations.suggest_season_label(unreadable, "s.xlsx") is None


def test_the_prefilled_label_is_editable(workspace):
    state = mutations.upload_responses(workspace, _jaro_survey(), "s.xlsx", label="2025-podzim")
    assert state["season"]["label"] == "2025-podzim"


def test_label_is_asked_for_when_timestamps_cannot_be_read(workspace):
    with pytest.raises(mutations.SeasonLabelRequired) as excinfo:
        mutations.upload_responses(workspace, _survey(["Anna"]), "s.xlsx")
    assert excinfo.value.suggested_label is None
    assert isinstance(excinfo.value, mutations.RosteringError)
    # Nothing was created or loaded.
    assert mutations.list_seasons(workspace) == []
    assert mutations.get_state(workspace)["helpers"] == []

    mutations.upload_responses(workspace, _survey(["Anna"]), "s.xlsx", label="2026-jaro")
    assert mutations.get_open_season(workspace)["label"] == "2026-jaro"


@pytest.mark.parametrize("bad", ["2026", "jaro", "2026-leto", "spring 2026", "26-jaro"])
def test_a_malformed_label_is_rejected_and_nothing_is_created(workspace, bad):
    with pytest.raises(mutations.RosteringError):
        mutations.upload_responses(workspace, _jaro_survey(), "s.xlsx", label=bad)
    assert mutations.list_seasons(workspace) == []


@pytest.mark.parametrize("typed", ["2026-JARO", " 2026 jaro ", "2026_Jaro"])
def test_a_label_is_normalized_to_year_dash_half(workspace, typed):
    state = mutations.upload_responses(workspace, _jaro_survey(), "s.xlsx", label=typed)
    assert state["season"]["label"] == "2026-jaro"


# -- labels are unique and order Seasons in time ----------------------------


def test_duplicate_label_is_blocked_with_a_message(workspace):
    _create(workspace, "2026-jaro")
    mutations.new_season(workspace)
    with pytest.raises(mutations.RosteringError, match="2026-jaro"):
        _create(workspace, "2026-jaro")
    # A case/whitespace variant is the same label.
    with pytest.raises(mutations.RosteringError):
        _create(workspace, " 2026-JARO ")
    assert len(mutations.list_seasons(workspace)) == 1
    # The blocked upload left the Workspace blank rather than half-created.
    assert mutations.get_open_season(workspace) is None


def test_a_prefilled_duplicate_label_is_blocked_too(workspace):
    mutations.upload_responses(workspace, _jaro_survey(), "s.xlsx")
    mutations.new_season(workspace)
    with pytest.raises(mutations.RosteringError, match="2026-jaro"):
        mutations.upload_responses(workspace, _jaro_survey(), "s.xlsx")


def test_seasons_are_listed_in_time_order_most_recent_first(workspace):
    for label in ["2025-podzim", "2024-jaro", "2026-jaro", "2025-jaro"]:
        _create(workspace, label)
        mutations.new_season(workspace)
    assert [s["label"] for s in mutations.list_seasons(workspace)] == [
        "2026-jaro",
        "2025-podzim",
        "2025-jaro",
        "2024-jaro",
    ]


# -- one Season per directory; the pointer names the open one ---------------


def test_each_season_lives_in_its_own_directory_named_by_its_label(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    assert (seasons_root / "2026-jaro").is_dir()
    mutations.save_version(workspace, "Draft")
    assert len(list((seasons_root / "2026-jaro" / "versions").glob("*.json"))) == 1


def test_a_season_directory_without_a_saved_state_is_ignored(workspace, seasons_root):
    hand_placed = seasons_root / "2023-podzim"
    hand_placed.mkdir(parents=True)
    (hand_placed / "raw-response.xlsx").write_bytes(b"not really an export")
    (hand_placed / "config.yaml").write_text("{}", encoding="utf-8")
    assert mutations.list_seasons(workspace) == []


def test_creating_a_season_adopts_a_hand_placed_directory_and_keeps_its_files(workspace, seasons_root):
    hand_placed = seasons_root / "2026-jaro"
    hand_placed.mkdir(parents=True)
    (hand_placed / "raw-response.xlsx").write_bytes(b"hand placed")
    _create(workspace, "2026-jaro")
    assert (hand_placed / "raw-response.xlsx").read_bytes() == b"hand placed"
    assert [s["label"] for s in mutations.list_seasons(workspace)] == ["2026-jaro"]


def test_a_pointer_to_a_vanished_season_means_no_season_is_open(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    (seasons_root / "2026-jaro" / "state.json").unlink()
    assert mutations.get_open_season(workspace) is None
    assert mutations.get_state(workspace)["helpers"] == []


# -- re-upload, New Season, Start over, opening ----------------------------


def test_upload_while_a_season_is_open_is_always_a_reupload(workspace):
    _create(workspace, "2026-jaro", names=("Anna", "Petr"))
    season_id = mutations.get_open_season(workspace)["id"]

    # Even a podzim export, and even with a label passed, goes into the open Season.
    state = mutations.upload_responses(workspace, _podzim_survey(("Klara",)), "s.xlsx", label="2030-jaro")
    assert [h["name"] for h in state["helpers"]] == ["Klara"]
    assert mutations.get_open_season(workspace) == {"id": season_id, "label": "2026-jaro"}
    assert len(mutations.list_seasons(workspace)) == 1


def test_new_season_opens_a_blank_workspace_and_keeps_the_old_season_stored(workspace):
    _create(workspace, "2026-jaro")
    state = mutations.new_season(workspace)
    assert state["helpers"] == []
    assert "season" not in state
    assert mutations.get_open_season(workspace) is None
    seasons = mutations.list_seasons(workspace)
    assert [(s["label"], s["open"], s["helper_count"]) for s in seasons] == [("2026-jaro", False, 2)]

    _create(workspace, "2026-podzim", names=("Klara",))
    assert [(s["label"], s["open"]) for s in mutations.list_seasons(workspace)] == [
        ("2026-podzim", True),
        ("2026-jaro", False),
    ]


def test_edits_made_before_a_season_exists_carry_into_it(workspace):
    mutations.new_season(workspace)
    mutations.put_config(workspace, SMALL_CONFIG)
    state = _create(workspace, "2026-jaro")
    assert state["config"][0]["name"] == "B"


def test_start_over_empties_the_state_but_keeps_label_id_and_versions(workspace):
    _create(workspace, "2026-jaro")
    season = mutations.get_open_season(workspace)
    version = mutations.save_version(workspace, "Before")

    state = mutations.reset_workspace(workspace)
    assert state["helpers"] == []
    assert state["season"] == season
    assert mutations.get_open_season(workspace) == season
    assert [v["slug"] for v in mutations.list_versions(workspace)] == [version["slug"]]
    # ...and the Season still counts as stored, now with no Helpers.
    assert [(s["label"], s["helper_count"]) for s in mutations.list_seasons(workspace)] == [("2026-jaro", 0)]


def test_opening_a_stored_season_replaces_the_workspace_contents(workspace):
    _create(workspace, "2026-jaro", names=("Anna", "Petr"))
    mutations.new_season(workspace)
    _create(workspace, "2026-podzim", names=("Klara",))
    ids = _ids_by_label(workspace)

    state = mutations.open_season(workspace, ids["2026-jaro"])
    assert [h["name"] for h in state["helpers"]] == ["Anna", "Petr"]
    assert mutations.get_open_season(workspace) == {"id": ids["2026-jaro"], "label": "2026-jaro"}
    assert [s["label"] for s in mutations.list_seasons(workspace) if s["open"]] == ["2026-jaro"]

    # An old Season can be corrected in place: edits go to it, not to the other.
    mutations.put_config(workspace, SMALL_CONFIG)
    other = mutations.open_season(workspace, ids["2026-podzim"])
    assert [h["name"] for h in other["helpers"]] == ["Klara"]
    assert other["config"][0]["name"] != "B"
    assert mutations.open_season(workspace, ids["2026-jaro"])["config"][0]["name"] == "B"


def test_opening_an_unknown_season_raises(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.open_season(workspace, "nope")


# -- rename -------------------------------------------------------------


def test_rename_renames_the_directory_and_keeps_the_season_id(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    season_id = mutations.get_open_season(workspace)["id"]
    mutations.save_version(workspace, "V")

    renamed = mutations.rename_season(workspace, season_id, "2027-jaro")
    assert renamed == {"id": season_id, "label": "2027-jaro"}
    assert (seasons_root / "2027-jaro").is_dir()
    assert not (seasons_root / "2026-jaro").exists()
    assert mutations.get_open_season(workspace) == {"id": season_id, "label": "2027-jaro"}
    assert mutations.get_state(workspace)["season"] == {"id": season_id, "label": "2027-jaro"}
    assert [s["label"] for s in mutations.list_seasons(workspace)] == ["2027-jaro"]
    # Versions travel with the directory.
    assert len(mutations.list_versions(workspace)) == 1
    # Still open after a restart.
    assert Workspace(root=seasons_root).open_season() == {"id": season_id, "label": "2027-jaro"}


def test_a_stored_season_can_be_renamed_without_opening_it(workspace):
    _create(workspace, "2026-jaro")
    mutations.new_season(workspace)
    _create(workspace, "2026-podzim")
    ids = _ids_by_label(workspace)

    mutations.rename_season(workspace, ids["2026-jaro"], "2025-jaro")
    assert _ids_by_label(workspace)["2025-jaro"] == ids["2026-jaro"]
    assert mutations.get_open_season(workspace)["label"] == "2026-podzim"


def test_rename_to_an_existing_label_is_blocked_but_to_its_own_is_fine(workspace):
    _create(workspace, "2026-jaro")
    mutations.new_season(workspace)
    _create(workspace, "2026-podzim")
    ids = _ids_by_label(workspace)

    with pytest.raises(mutations.RosteringError, match="2026-jaro"):
        mutations.rename_season(workspace, ids["2026-podzim"], "2026-jaro")
    with pytest.raises(mutations.RosteringError):
        mutations.rename_season(workspace, ids["2026-podzim"], "autumn")
    assert mutations.rename_season(workspace, ids["2026-podzim"], "2026-podzim")["label"] == "2026-podzim"
    assert set(_ids_by_label(workspace)) == {"2026-jaro", "2026-podzim"}


def test_rename_reorders_seasons_in_time(workspace):
    _create(workspace, "2025-jaro")
    mutations.new_season(workspace)
    _create(workspace, "2026-jaro")
    ids = _ids_by_label(workspace)
    mutations.rename_season(workspace, ids["2025-jaro"], "2027-podzim")
    assert [s["label"] for s in mutations.list_seasons(workspace)] == ["2027-podzim", "2026-jaro"]


def test_rename_refuses_to_clobber_a_hand_placed_folder(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    (seasons_root / "2027-jaro").mkdir()
    (seasons_root / "2027-jaro" / "raw-response.xlsx").write_bytes(b"x")
    with pytest.raises(mutations.RosteringError):
        mutations.rename_season(workspace, mutations.get_open_season(workspace)["id"], "2027-jaro")
    assert mutations.get_open_season(workspace)["label"] == "2026-jaro"


def test_rename_unknown_season_raises(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.rename_season(workspace, "nope", "2026-jaro")


# -- delete ---------------------------------------------------------------


def test_the_open_season_cannot_be_deleted(workspace):
    _create(workspace, "2026-jaro")
    with pytest.raises(mutations.RosteringError):
        mutations.delete_season(workspace, mutations.get_open_season(workspace)["id"])
    assert len(mutations.list_seasons(workspace)) == 1


def test_deleting_a_stored_season_deletes_its_versions_too(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    mutations.save_version(workspace, "V1")
    mutations.save_version(workspace, "V2")
    mutations.new_season(workspace)
    _create(workspace, "2026-podzim")
    mutations.save_version(workspace, "Other")
    ids = _ids_by_label(workspace)

    mutations.delete_season(workspace, ids["2026-jaro"])
    assert [s["label"] for s in mutations.list_seasons(workspace)] == ["2026-podzim"]
    assert not (seasons_root / "2026-jaro").exists()
    # The other Season and its own Versions are untouched.
    assert [v["name"] for v in mutations.list_versions(workspace)] == ["Other"]
    with pytest.raises(mutations.RosteringError):
        mutations.open_season(workspace, ids["2026-jaro"])


def test_deleting_a_season_leaves_hand_placed_files_alone(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    (seasons_root / "2026-jaro" / "raw-response.xlsx").write_bytes(b"hand placed")
    mutations.new_season(workspace)
    _create(workspace, "2026-podzim")

    mutations.delete_season(workspace, _ids_by_label(workspace)["2026-jaro"])
    assert (seasons_root / "2026-jaro" / "raw-response.xlsx").read_bytes() == b"hand placed"
    assert [s["label"] for s in mutations.list_seasons(workspace)] == ["2026-podzim"]  # dir alone is ignored


def test_delete_unknown_season_raises(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.delete_season(workspace, "nope")


# -- Versions ---------------------------------------------------------------


def test_versions_belong_to_their_season(workspace):
    _create(workspace, "2026-jaro")
    mutations.save_version(workspace, "In jaro")
    mutations.new_season(workspace)
    assert mutations.list_versions(workspace) == []
    _create(workspace, "2026-podzim")
    assert mutations.list_versions(workspace) == []
    mutations.open_season(workspace, _ids_by_label(workspace)["2026-jaro"])
    assert [v["name"] for v in mutations.list_versions(workspace)] == ["In jaro"]


def test_saving_a_version_with_no_season_open_is_refused(workspace):
    with pytest.raises(mutations.RosteringError):
        mutations.save_version(workspace, "Nope")


def test_restoring_a_version_never_rolls_back_the_season_identity(workspace):
    _create(workspace, "2026-jaro")
    season_id = mutations.get_open_season(workspace)["id"]
    mutations.put_config(workspace, SMALL_CONFIG)
    mutations.solve(workspace)
    version = mutations.save_version(workspace, "Solved")

    # Change the state and the label after the snapshot.
    mutations.put_config(workspace, OTHER_CONFIG)
    mutations.rename_season(workspace, season_id, "2027-podzim")
    mutations.reset_workspace(workspace)

    restored = mutations.restore_version(workspace, version["slug"])
    assert [h["name"] for h in restored["helpers"]] == ["Anna", "Petr"]
    assert len(restored["assignments"]) == 2
    assert restored["config"][0]["name"] == "B"
    assert restored["season"] == {"id": season_id, "label": "2027-podzim"}
    assert mutations.get_open_season(workspace) == {"id": season_id, "label": "2027-podzim"}


def test_a_version_snapshot_contains_no_identity(workspace, seasons_root):
    _create(workspace, "2026-jaro")
    version = mutations.save_version(workspace, "V")
    path = seasons_root / "2026-jaro" / "versions" / f"{version['slug']}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "season" not in saved
    assert [h["name"] for h in saved["helpers"]] == ["Anna", "Petr"]


# -- buildings layout ---------------------------------------------------------


def test_the_saved_layout_seeds_each_new_season_and_survives_start_over(workspace):
    _create(workspace, "2026-jaro")
    mutations.put_config(workspace, SMALL_CONFIG)  # also saved as the default layout
    mutations.new_season(workspace)
    seeded = _create(workspace, "2026-podzim")
    assert seeded["config"][0]["name"] == "B"

    assert mutations.reset_workspace(workspace)["config"][0]["name"] == "B"


def test_each_season_keeps_its_own_snapshot_of_the_layout_it_used(workspace):
    _create(workspace, "2026-jaro")
    mutations.put_config(workspace, SMALL_CONFIG)
    ids = _ids_by_label(workspace)
    mutations.new_season(workspace)
    _create(workspace, "2026-podzim")
    mutations.put_config(workspace, OTHER_CONFIG)

    assert mutations.open_season(workspace, ids["2026-jaro"])["config"][0]["name"] == "B"
    assert mutations.get_state(workspace)["config"][0]["name"] == "B"


# -- migration of the pre-Seasons single saved state --------------------------


@pytest.fixture
def legacy_root(tmp_path):
    return tmp_path / "workspace"


@pytest.fixture
def migrating(seasons_root, legacy_root):
    return Workspace(root=seasons_root, legacy_root=legacy_root)


def _write_legacy(legacy_root, helpers=("Anna", "Petr"), export_timestamps=None, versions=()):
    legacy_root.mkdir(parents=True, exist_ok=True)
    state = Workspace(root=legacy_root.parent / "scratch-seasons").empty_state()
    state["helpers"] = [
        {
            "id": i,
            "name": name,
            "role_preferences": {},
            "building_preferences": [],
            "friends": [],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        }
        for i, name in enumerate(helpers, start=1)
    ]
    if export_timestamps is not None:
        state["export_timestamps"] = export_timestamps
    (legacy_root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (legacy_root / "versions").mkdir(exist_ok=True)
    for slug, name in versions:
        snapshot = {**state, "_meta": {"name": name, "created_at": f"2026-03-0{len(slug)}T10:00:00+00:00"}}
        (legacy_root / "versions" / f"{slug}.json").write_text(json.dumps(snapshot), encoding="utf-8")


def test_nothing_to_migrate_on_a_fresh_install(migrating):
    assert mutations.migrate_legacy_workspace(migrating) is None
    assert mutations.list_seasons(migrating) == []


def test_a_legacy_state_with_export_timestamps_is_labelled_silently(migrating, legacy_root, seasons_root):
    _write_legacy(
        legacy_root,
        export_timestamps=["2025-09-10", "2025-09-12", "2025-10-01"],
        versions=[("aaa", "Draft one"), ("bbbb", "Draft two")],
    )
    season = mutations.migrate_legacy_workspace(migrating)
    assert season["label"] == "2025-podzim"

    # Opened, with everything it had.
    assert mutations.get_open_season(migrating) == season
    assert [h["name"] for h in mutations.get_state(migrating)["helpers"]] == ["Anna", "Petr"]
    assert sorted(v["name"] for v in mutations.list_versions(migrating)) == ["Draft one", "Draft two"]
    assert (seasons_root / "2025-podzim").is_dir()
    # Moved, not copied: it is not migrated a second time.
    assert not (legacy_root / "state.json").exists()
    assert list((legacy_root / "versions").glob("*.json")) == []
    assert mutations.migrate_legacy_workspace(migrating) is None
    assert len(mutations.list_seasons(migrating)) == 1


def test_a_legacy_state_without_a_derivable_label_asks_once(migrating, legacy_root):
    _write_legacy(legacy_root, versions=[("aaa", "Draft")])
    with pytest.raises(mutations.SeasonLabelRequired) as excinfo:
        mutations.migrate_legacy_workspace(migrating)
    # Nothing moved yet.
    assert (legacy_root / "state.json").exists()
    assert mutations.list_seasons(migrating) == []
    # The suggestion (from the file's last-modified date) is a valid label.
    assert excinfo.value.suggested_label is not None

    season = mutations.migrate_legacy_workspace(migrating, label="2026-jaro")
    assert season["label"] == "2026-jaro"
    assert [v["name"] for v in mutations.list_versions(migrating)] == ["Draft"]
    assert not (legacy_root / "state.json").exists()


def test_a_bad_answer_to_the_migration_question_asks_again(migrating, legacy_root):
    _write_legacy(legacy_root)
    with pytest.raises(mutations.SeasonLabelRequired):
        mutations.migrate_legacy_workspace(migrating, label="whenever")
    assert (legacy_root / "state.json").exists()


def test_a_migrated_label_that_is_already_stored_asks_for_another(migrating, legacy_root):
    _create(migrating, "2025-podzim")
    mutations.new_season(migrating)
    _write_legacy(legacy_root, export_timestamps=["2025-10-01"])
    with pytest.raises(mutations.SeasonLabelRequired, match="2025-podzim"):
        mutations.migrate_legacy_workspace(migrating)
    assert (legacy_root / "state.json").exists()
    assert mutations.migrate_legacy_workspace(migrating, label="2025-jaro")["label"] == "2025-jaro"


def test_an_empty_legacy_state_is_not_migrated(migrating, legacy_root):
    _write_legacy(legacy_root, helpers=())
    assert mutations.migrate_legacy_workspace(migrating) is None
    assert mutations.list_seasons(migrating) == []


def test_upload_records_the_export_timestamps_that_later_label_a_migration(migrating):
    # A state saved by this version carries its export timestamps, so were it
    # ever the "unlabeled" one (e.g. a Season directory lost its identity) the
    # label can be derived from it.
    state = mutations.upload_responses(migrating, _jaro_survey(("A", "B", "C")), "s.xlsx")
    assert state["export_timestamps"] == ["2026-02-01", "2026-02-02", "2026-02-03"]


def test_the_default_workspace_keeps_everything_under_the_gitignored_data_dir(monkeypatch, tmp_path):
    from rostering.persistence import workspace as workspace_module

    monkeypatch.delenv("ROSTERING_SEASONS_DIR", raising=False)
    monkeypatch.delenv("ROSTERING_WORKSPACE_DIR", raising=False)
    assert workspace_module.default_seasons_root().parts[0] == "data"
    assert workspace_module.default_legacy_root().parts[0] == "data"

    # An isolated run (only the workspace dir overridden) stays inside it.
    monkeypatch.setenv("ROSTERING_WORKSPACE_DIR", str(tmp_path / "iso"))
    assert workspace_module.default_seasons_root() == tmp_path / "iso" / "seasons"
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "s"))
    assert workspace_module.default_seasons_root() == tmp_path / "s"
