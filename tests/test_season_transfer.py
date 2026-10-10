"""Export and import of Seasons as a .zip (``rostering.persistence.transfer``,
``Workspace.apply_import``, the Season-transfer section of ``mutations``),
against temp-dir workspaces with synthetic data."""
import importlib
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from rostering.persistence import transfer
from rostering.persistence.workspace import Workspace
from rostering.webapp import mutations

_NAME_HEADER = "Tvoje jméno a příjmení"


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.persistence import config_store as config_store_module

    importlib.reload(config_store_module)


def _survey(names) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame({_NAME_HEADER: list(names)}).to_excel(buffer, index=False)
    return buffer.getvalue()


def _make(root, seasons):
    """A Workspace at ``root`` holding ``{label: names}`` Seasons; the last one
    created stays open."""
    workspace = Workspace(root=root)
    for label, names in seasons.items():
        mutations.new_season(workspace)
        mutations.upload_responses(workspace, _survey(names), "s.xlsx", label=label)
    return workspace


@pytest.fixture
def src(tmp_path):
    return _make(tmp_path / "src" / "seasons", {"2025-podzim": ["Anna", "Petr"], "2026-jaro": ["Jana", "Karel", "Olga"]})


@pytest.fixture
def dst(tmp_path):
    return Workspace(root=tmp_path / "dst" / "seasons")


def _ids(workspace):
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def _names(workspace, label):
    state = workspace.stored_state(_ids(workspace)[label])
    return [h["name"] for h in state["helpers"]]


def _zip_names(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return set(archive.namelist())


def _rewrite_manifest(data, **changes):
    """The same zip with manifest fields replaced."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "manifest.json":
                manifest = json.loads(content)
                manifest.update(changes)
                content = json.dumps(manifest).encode()
            target.writestr(item.filename, content)
    return out.getvalue()


def _replace_member(data, name, content: bytes):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item.filename, content if item.filename == name else source.read(item.filename))
    return out.getvalue()


# -- export ------------------------------------------------------------------


def test_export_is_a_zip_with_a_manifest_and_a_folder_per_season(src):
    data = mutations.export_seasons(src)
    names = _zip_names(data)
    assert "manifest.json" in names
    assert "seasons/2025-podzim/state.json" in names
    assert "seasons/2026-jaro/state.json" in names
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    assert manifest["schema_version"] == transfer.SCHEMA_VERSION
    assert manifest["exported_at"]
    assert manifest["open_season_id"] == _ids(src)["2026-jaro"]
    by_label = {s["label"]: s for s in manifest["seasons"]}
    assert by_label["2026-jaro"]["helper_count"] == 3
    assert by_label["2026-jaro"]["id"] == _ids(src)["2026-jaro"]


def test_export_of_a_subset_holds_only_the_ticked_seasons(src):
    data = mutations.export_seasons(src, season_ids=[_ids(src)["2025-podzim"]])
    names = _zip_names(data)
    assert "seasons/2025-podzim/state.json" in names
    assert "seasons/2026-jaro/state.json" not in names
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    assert [s["label"] for s in manifest["seasons"]] == ["2025-podzim"]
    # The open Season was left out, so the file does not claim one.
    assert manifest["open_season_id"] is None


def test_export_includes_versions_unless_switched_off(src):
    mutations.save_version(src, "before")
    with_versions = _zip_names(mutations.export_seasons(src))
    assert any(n.startswith("seasons/2026-jaro/versions/") for n in with_versions)
    lean = _zip_names(mutations.export_seasons(src, include_versions=False))
    assert not any("/versions/" in n for n in lean)


def test_export_with_an_unknown_season_id_is_refused(src):
    with pytest.raises(mutations.RosteringError):
        mutations.export_seasons(src, season_ids=["nope"])


def test_export_of_nothing_is_refused(src):
    with pytest.raises(mutations.RosteringError):
        mutations.export_seasons(src, season_ids=[])


def test_export_leaves_hand_placed_files_out(src):
    (src.root / "2026-jaro" / "raw-response.xlsx").write_bytes(b"raw")
    assert not any("raw-response" in n for n in _zip_names(mutations.export_seasons(src)))


# -- reading a package -------------------------------------------------------


def test_a_file_that_is_not_a_zip_is_refused(dst):
    with pytest.raises(mutations.RosteringError, match="zip"):
        mutations.preview_import(dst, b"definitely not a zip")


def test_a_zip_without_a_manifest_is_refused(dst):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(mutations.RosteringError, match="manifest"):
        mutations.preview_import(dst, out.getvalue())


def test_a_file_from_a_newer_schema_is_refused(src, dst):
    data = _rewrite_manifest(mutations.export_seasons(src), schema_version=transfer.SCHEMA_VERSION + 1)
    with pytest.raises(mutations.RosteringError, match="novější"):
        mutations.preview_import(dst, data)


def test_an_older_schema_is_accepted(src, dst):
    data = _rewrite_manifest(mutations.export_seasons(src), schema_version=0)
    assert len(mutations.preview_import(dst, data)["seasons"]) == 2


def test_a_state_whose_identity_disagrees_with_the_manifest_is_refused(src, dst):
    data = mutations.export_seasons(src)
    state = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("seasons/2026-jaro/state.json"))
    state["season"]["id"] = "someone-else"
    data = _replace_member(data, "seasons/2026-jaro/state.json", json.dumps(state).encode())
    with pytest.raises(mutations.RosteringError):
        mutations.preview_import(dst, data)


def test_a_season_listed_but_missing_from_the_zip_is_refused(src, dst):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(mutations.export_seasons(src))) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            if item.filename != "seasons/2026-jaro/state.json":
                target.writestr(item.filename, source.read(item.filename))
    with pytest.raises(mutations.RosteringError):
        mutations.preview_import(dst, out.getvalue())


def test_an_unreadable_state_is_refused(src, dst):
    data = _replace_member(mutations.export_seasons(src), "seasons/2026-jaro/state.json", b"{not json")
    with pytest.raises(mutations.RosteringError):
        mutations.preview_import(dst, data)


# -- preview -----------------------------------------------------------------


def test_preview_into_an_empty_workspace_lists_everything_as_new(src, dst):
    preview = mutations.preview_import(dst, mutations.export_seasons(src))
    assert preview["into_empty"] is True
    assert {s["label"]: s["status"] for s in preview["seasons"]} == {"2025-podzim": "new", "2026-jaro": "new"}
    jaro = next(s for s in preview["seasons"] if s["label"] == "2026-jaro")
    assert jaro["helper_count"] == 3
    assert jaro["local"] is None
    assert jaro["diff"] == []


def test_preview_changes_nothing_on_disk(src, dst):
    mutations.preview_import(dst, mutations.export_seasons(src))
    assert mutations.list_seasons(dst) == []
    assert not (dst.root.parent / "backups").exists()


def test_preview_flags_a_season_with_a_known_id_and_lists_the_differences(src, dst):
    data = mutations.export_seasons(src)
    mutations.import_seasons(dst, data, {})  # same file into an empty workspace
    mutations.add_helper(dst, "Zdenka", "z@x.cz")  # local edit of the open Season
    preview = mutations.preview_import(dst, data)
    jaro = next(s for s in preview["seasons"] if s["label"] == "2026-jaro")
    assert jaro["status"] == "same_id"
    assert jaro["local"]["label"] == "2026-jaro"
    helpers = next(c for c in jaro["diff"] if c["key"] == "helpers")
    assert helpers["removed"] == ["Zdenka"]  # present locally, absent in the file
    untouched = next(s for s in preview["seasons"] if s["label"] == "2025-podzim")
    assert untouched["status"] == "identical"
    assert untouched["diff"] == []


def test_preview_flags_the_same_label_under_a_different_id(src, tmp_path, dst):
    other = _make(tmp_path / "other" / "seasons", {"2026-jaro": ["Jiný"]})
    preview = mutations.preview_import(src, mutations.export_seasons(other))
    only = preview["seasons"][0]
    assert only["status"] == "label_clash"
    assert only["local"] == {"id": _ids(src)["2026-jaro"], "label": "2026-jaro"}
    assert any(c["key"] == "helpers" for c in only["diff"])


def test_preview_suggests_a_free_label_for_keeping_both(src, tmp_path):
    other = _make(tmp_path / "other" / "seasons", {"2026-jaro": ["Jiný"]})
    only = mutations.preview_import(src, mutations.export_seasons(other))["seasons"][0]
    assert only["suggested_label"] == "2026-podzim"
    both = _make(tmp_path / "both" / "seasons", {"2026-podzim": ["Q"]})
    mutations.import_seasons(src, mutations.export_seasons(both), {})
    only = mutations.preview_import(src, mutations.export_seasons(other))["seasons"][0]
    assert only["suggested_label"] == "2027-jaro"


def test_preview_into_a_populated_workspace_is_not_into_empty(src):
    assert mutations.preview_import(src, mutations.export_seasons(src))["into_empty"] is False


# -- importing: new Seasons --------------------------------------------------


def test_round_trip_into_an_empty_workspace_carries_everything_unchanged(src, dst):
    mutations.save_version(src, "before")
    originals = {label: src.stored_state(sid) for label, sid in _ids(src).items()}
    report = mutations.import_seasons(dst, mutations.export_seasons(src), {})
    assert sorted(report["added"]) == ["2025-podzim", "2026-jaro"]
    assert _ids(dst) == _ids(src)  # ids survive
    for label, sid in _ids(dst).items():
        assert dst.stored_state(sid) == originals[label]
    assert mutations.get_open_season(dst) == {"id": _ids(src)["2026-jaro"], "label": "2026-jaro"}
    assert [v["name"] for v in mutations.list_versions(dst)] == ["before"]


def test_a_lean_export_brings_no_versions(src, dst):
    mutations.save_version(src, "before")
    mutations.import_seasons(dst, mutations.export_seasons(src, include_versions=False), {})
    assert mutations.list_versions(dst) == []


def test_person_ids_are_kept_as_they_arrive(src, dst):
    before = {h["person_id"] for h in src.stored_state(_ids(src)["2026-jaro"])["helpers"]}
    mutations.import_seasons(dst, mutations.export_seasons(src), {})
    after = {h["person_id"] for h in dst.stored_state(_ids(dst)["2026-jaro"])["helpers"]}
    assert after == before


def test_a_populated_workspace_keeps_its_open_season(src, tmp_path):
    other = _make(tmp_path / "other" / "seasons", {"2024-jaro": ["Stará"]})
    open_before = mutations.get_open_season(src)
    mutations.import_seasons(src, mutations.export_seasons(other), {})
    assert mutations.get_open_season(src) == open_before
    assert "2024-jaro" in _ids(src)


def test_new_seasons_can_be_unticked_with_skip(src, dst):
    ids = _ids(src)
    report = mutations.import_seasons(dst, mutations.export_seasons(src), {ids["2025-podzim"]: {"action": "skip"}})
    assert report["added"] == ["2026-jaro"]
    assert report["skipped"] == ["2025-podzim"]
    assert list(_ids(dst)) == ["2026-jaro"]


def test_the_open_season_is_not_restored_when_it_was_skipped(src, dst):
    ids = _ids(src)
    mutations.import_seasons(dst, mutations.export_seasons(src), {ids["2026-jaro"]: {"action": "skip"}})
    assert mutations.get_open_season(dst) is None


def test_importing_into_a_workspace_with_an_unsaved_draft_does_not_open_a_season(src, dst):
    mutations.new_season(dst)
    dst._draft = {"helpers": [{"id": 1, "name": "Rozpracovaný"}]}
    mutations.import_seasons(dst, mutations.export_seasons(src), {})
    assert mutations.get_open_season(dst) is None


# -- importing: conflicts ----------------------------------------------------


def _edited_copy(src, tmp_path, name="copy"):
    """A second workspace holding the same Seasons (same ids) as ``src`` plus a
    hand-added Helper in the open one — the colleague's edit."""
    colleague = Workspace(root=tmp_path / name / "seasons")
    mutations.import_seasons(colleague, mutations.export_seasons(src), {})
    mutations.add_helper(colleague, "Nový", "n@x.cz")
    return colleague


def test_a_conflicting_season_needs_an_explicit_choice(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    data = mutations.export_seasons(colleague)
    with pytest.raises(mutations.RosteringError, match="2026-jaro"):
        mutations.import_seasons(src, data, {})
    assert "Nový" not in _names(src, "2026-jaro")  # nothing applied


def test_skip_leaves_the_local_season_alone(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2026-jaro"]
    mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "skip"}})
    assert "Nový" not in _names(src, "2026-jaro")


def test_replace_swaps_the_season_state_and_versions_wholesale(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    mutations.save_version(src, "local only")  # made after the colleague's copy
    mutations.save_version(colleague, "theirs")
    sid = _ids(src)["2026-jaro"]
    report = mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "replace"}})
    assert report["replaced"] == ["2026-jaro"]
    assert "Nový" in _names(src, "2026-jaro")
    assert _ids(src)["2026-jaro"] == sid
    assert [v["name"] for v in mutations.list_versions(src)] == ["theirs"]


def test_replacing_the_open_season_reloads_it_and_reports_that(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2026-jaro"]
    report = mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "replace"}})
    assert report["open_season_changed"] is True
    assert "Nový" in [h["name"] for h in mutations.get_state(src)["helpers"]]
    assert mutations.get_open_season(src)["id"] == sid


def test_replacing_a_season_that_is_not_open_does_not_report_a_change(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2025-podzim"]
    mutations.add_helper(colleague, "Ignoruj", "i@x.cz")
    report = mutations.import_seasons(
        src,
        mutations.export_seasons(colleague),
        {_ids(src)["2026-jaro"]: {"action": "skip"}, sid: {"action": "replace"}},
    )
    assert report["open_season_changed"] is False


def test_a_file_without_versions_leaves_the_local_versions_alone(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    mutations.save_version(src, "local only")
    sid = _ids(src)["2026-jaro"]
    data = mutations.export_seasons(colleague, include_versions=False)
    jaro = next(s for s in mutations.preview_import(src, data)["seasons"] if s["label"] == "2026-jaro")
    assert not any(c["key"] == "versions" for c in jaro["diff"])  # nothing claimed about Versions
    mutations.import_seasons(src, data, {sid: {"action": "replace"}})
    assert "Nový" in _names(src, "2026-jaro")
    assert [v["name"] for v in mutations.list_versions(src)] == ["local only"]


def test_a_file_without_versions_keeps_them_through_a_rename_too(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    mutations.rename_season(colleague, _ids(colleague)["2026-jaro"], "2027-jaro")
    mutations.save_version(src, "local only")
    sid = _ids(src)["2026-jaro"]
    data = mutations.export_seasons(colleague, include_versions=False)
    mutations.import_seasons(src, data, {sid: {"action": "replace"}})
    assert mutations.get_open_season(src)["label"] == "2027-jaro"
    assert [v["name"] for v in mutations.list_versions(src)] == ["local only"]


def test_a_season_renamed_elsewhere_is_a_difference_not_identical(src, tmp_path):
    colleague = Workspace(root=tmp_path / "copy" / "seasons")
    mutations.import_seasons(colleague, mutations.export_seasons(src), {})
    mutations.rename_season(colleague, _ids(colleague)["2026-jaro"], "2027-jaro")
    seasons = {s["id"]: s for s in mutations.preview_import(src, mutations.export_seasons(colleague))["seasons"]}
    renamed = seasons[_ids(src)["2026-jaro"]]
    assert renamed["status"] == "same_id"
    assert renamed["diff"][0]["key"] == "label"
    assert renamed["diff"][0]["changed"][0]["label"] == "2026-jaro → 2027-jaro"


def test_replace_keeps_hand_placed_files_in_the_directory(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    (src.root / "2026-jaro" / "raw-response.xlsx").write_bytes(b"raw")
    sid = _ids(src)["2026-jaro"]
    mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "replace"}})
    assert (src.root / "2026-jaro" / "raw-response.xlsx").read_bytes() == b"raw"


def test_replace_follows_a_rename_made_on_the_other_machine(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    mutations.rename_season(colleague, _ids(colleague)["2026-jaro"], "2027-jaro")
    sid = _ids(src)["2026-jaro"]
    mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "replace"}})
    assert _ids(src)["2027-jaro"] == sid
    assert "2026-jaro" not in _ids(src)
    assert mutations.get_open_season(src) == {"id": sid, "label": "2027-jaro"}
    assert "Nový" in [h["name"] for h in mutations.get_state(src)["helpers"]]


def test_replace_that_would_take_another_seasons_label_is_refused(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    # The colleague moved their 2026-jaro onto the label our 2025-podzim has.
    mutations.rename_season(colleague, _ids(colleague)["2025-podzim"], "2024-jaro")
    mutations.rename_season(colleague, _ids(colleague)["2026-jaro"], "2025-podzim")
    sid = _ids(src)["2026-jaro"]
    with pytest.raises(mutations.RosteringError, match="2025-podzim"):
        mutations.import_seasons(
            src,
            mutations.export_seasons(colleague),
            {
                sid: {"action": "replace"},
                _ids(src)["2025-podzim"]: {"action": "skip"},
            },
        )
    assert _names(src, "2026-jaro") == ["Jana", "Karel", "Olga"]


def test_keep_both_adds_a_copy_with_a_new_id_and_the_label_given(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2026-jaro"]
    report = mutations.import_seasons(
        src, mutations.export_seasons(colleague), {sid: {"action": "keep_both", "label": "2026-podzim"}}
    )
    assert report["kept_both"] == ["2026-podzim"]
    ids = _ids(src)
    assert ids["2026-jaro"] == sid
    assert ids["2026-podzim"] != sid
    assert "Nový" in _names(src, "2026-podzim")
    assert "Nový" not in _names(src, "2026-jaro")
    assert src.stored_state(ids["2026-podzim"])["season"] == {"id": ids["2026-podzim"], "label": "2026-podzim"}


def test_keep_both_needs_a_free_valid_label(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    data = mutations.export_seasons(colleague)
    sid = _ids(src)["2026-jaro"]
    for decision in (
        {"action": "keep_both"},
        {"action": "keep_both", "label": "nonsense"},
        {"action": "keep_both", "label": "2025-podzim"},  # taken
    ):
        with pytest.raises(mutations.RosteringError):
            mutations.import_seasons(src, data, {sid: decision})
    assert len(_ids(src)) == 2


def test_keep_both_labels_must_differ_from_each_other(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    mutations.add_helper(colleague, "Zase", "z@x.cz")
    data = mutations.export_seasons(colleague)
    ids = _ids(src)
    with pytest.raises(mutations.RosteringError, match="2030-jaro"):
        mutations.import_seasons(
            src,
            data,
            {
                ids["2026-jaro"]: {"action": "keep_both", "label": "2030-jaro"},
                ids["2025-podzim"]: {"action": "keep_both", "label": "2030-jaro"},
            },
        )


def test_a_label_clash_can_be_replaced_or_kept_alongside(src, tmp_path):
    other = _make(tmp_path / "other" / "seasons", {"2026-jaro": ["Jiný"]})
    data = mutations.export_seasons(other)
    incoming_id = _ids(other)["2026-jaro"]
    local_id = _ids(src)["2026-jaro"]

    kept = mutations.import_seasons(src, data, {incoming_id: {"action": "keep_both", "label": "2026-podzim"}})
    assert kept["kept_both"] == ["2026-podzim"]
    assert _ids(src)["2026-jaro"] == local_id
    assert _names(src, "2026-podzim") == ["Jiný"]

    replaced = mutations.import_seasons(src, data, {incoming_id: {"action": "replace"}})
    assert replaced["replaced"] == ["2026-jaro"]
    assert _ids(src)["2026-jaro"] == incoming_id  # the incoming Season took the label and the id
    assert _names(src, "2026-jaro") == ["Jiný"]
    assert replaced["open_season_changed"] is True  # the one that was open is gone
    assert mutations.get_open_season(src) == {"id": incoming_id, "label": "2026-jaro"}


def test_identical_seasons_default_to_skip_and_need_no_choice(src):
    report = mutations.import_seasons(src, mutations.export_seasons(src), {})
    assert report["added"] == [] and report["replaced"] == []
    assert sorted(report["skipped"]) == ["2025-podzim", "2026-jaro"]


def test_add_is_refused_for_a_season_that_already_exists(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2026-jaro"]
    with pytest.raises(mutations.RosteringError):
        mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "add"}})


def test_an_unknown_action_is_refused(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2026-jaro"]
    with pytest.raises(mutations.RosteringError):
        mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "merge"}})


# -- safety ------------------------------------------------------------------


def test_a_backup_of_the_current_workspace_is_written_before_applying(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    sid = _ids(src)["2026-jaro"]
    report = mutations.import_seasons(src, mutations.export_seasons(colleague), {sid: {"action": "replace"}})
    backup = report["backup"]
    assert backup is not None
    assert Path(backup).parent == src.root.parent / "backups"
    restored = Workspace(root=tmp_path / "restored" / "seasons")
    mutations.import_seasons(restored, open(backup, "rb").read(), {})
    assert _names(restored, "2026-jaro") == ["Jana", "Karel", "Olga"]  # as it was before the replace


def test_no_backup_is_written_into_an_empty_workspace(src, dst):
    report = mutations.import_seasons(dst, mutations.export_seasons(src), {})
    assert report["backup"] is None
    assert not (dst.root.parent / "backups").exists()


def test_a_failure_while_applying_leaves_the_workspace_as_it_was(src, tmp_path, monkeypatch):
    other = _make(tmp_path / "other" / "seasons", {"2024-jaro": ["A"], "2024-podzim": ["B"]})
    colleague = _edited_copy(src, tmp_path)
    data = mutations.export_seasons(colleague)
    sid = _ids(src)["2026-jaro"]
    before = {label: src.stored_state(i) for label, i in _ids(src).items()}

    real = transfer.write_staged_season
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(transfer, "write_staged_season", flaky)
    both = _zip_merge(data, mutations.export_seasons(other))
    with pytest.raises(mutations.RosteringError):
        mutations.import_seasons(
            src,
            both,
            {sid: {"action": "replace"}, _ids(src)["2025-podzim"]: {"action": "skip"}},
        )
    assert {label: src.stored_state(i) for label, i in _ids(src).items()} == before
    assert sorted(_ids(src)) == ["2025-podzim", "2026-jaro"]
    leftovers = [p.name for p in src.root.iterdir() if p.name.startswith(".import")]
    assert leftovers == []


def test_a_failure_while_moving_files_in_rolls_everything_back(src, tmp_path, monkeypatch):
    from rostering.persistence import workspace as workspace_module

    mutations.save_version(src, "keep me")
    colleague = _edited_copy(src, tmp_path)
    data = mutations.export_seasons(colleague)
    sid = _ids(src)["2026-jaro"]
    before = {label: src.stored_state(i) for label, i in _ids(src).items()}
    open_before = mutations.get_open_season(src)

    real = workspace_module._move
    calls = {"n": 0}

    def flaky(source, target):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("locked")
        return real(source, target)

    monkeypatch.setattr(workspace_module, "_move", flaky)
    with pytest.raises(mutations.RosteringError):
        mutations.import_seasons(src, data, {sid: {"action": "replace"}})
    monkeypatch.setattr(workspace_module, "_move", real)

    assert calls["n"] >= 3
    assert {label: src.stored_state(i) for label, i in _ids(src).items()} == before
    assert [v["name"] for v in mutations.list_versions(src)] == ["keep me"]
    assert mutations.get_open_season(src) == open_before
    assert [p.name for p in src.root.iterdir() if p.name.startswith(".import")] == []


def _zip_merge(a: bytes, b: bytes) -> bytes:
    """One package holding the Seasons of both (b's manifest entries appended)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(a)) as za, zipfile.ZipFile(io.BytesIO(b)) as zb, zipfile.ZipFile(out, "w") as target:
        manifest = json.loads(za.read("manifest.json"))
        manifest["seasons"] += json.loads(zb.read("manifest.json"))["seasons"]
        for item in za.infolist():
            if item.filename != "manifest.json":
                target.writestr(item.filename, za.read(item.filename))
        for item in zb.infolist():
            if item.filename != "manifest.json":
                target.writestr(item.filename, zb.read(item.filename))
        target.writestr("manifest.json", json.dumps(manifest))
    return out.getvalue()


def test_a_bad_file_applies_nothing(src):
    before = {label: src.stored_state(i) for label, i in _ids(src).items()}
    with pytest.raises(mutations.RosteringError):
        mutations.import_seasons(src, b"garbage", {})
    assert {label: src.stored_state(i) for label, i in _ids(src).items()} == before
    assert not (src.root.parent / "backups").exists()


def test_the_open_pointer_survives_a_failed_import(src, tmp_path):
    colleague = _edited_copy(src, tmp_path)
    before = mutations.get_open_season(src)
    with pytest.raises(mutations.RosteringError):
        mutations.import_seasons(src, mutations.export_seasons(colleague), {})
    assert mutations.get_open_season(src) == before
