"""The sidebar's Season export / import, driven with NiceGUI's user simulation
against temp-dir Seasons (never data/)."""
import asyncio
import io
import json
import zipfile

import pytest
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user_simulation import user_simulation

from rostering.persistence.workspace import Workspace
from rostering.webapp import labels, mutations
from rostering.webapp.ui import season_transfer
from rostering.webapp.ui.app import root


def _helper(helper_id, name):
    return {
        "id": helper_id,
        "name": name,
        "role_preferences": {},
        "building_preferences": [],
        "friends": [],
        "can_bring_notebook": False,
        "can_bring_camera": False,
        "unresolved_friend_names": [],
    }


def _make(root_dir, seasons):
    """A Workspace holding ``{label: [names]}`` Seasons, the last one open."""
    workspace = Workspace(root=root_dir)
    for label, names in seasons.items():
        state = workspace.empty_state()
        state["helpers"] = [_helper(i + 1, n) for i, n in enumerate(names)]
        state["next_helper_id"] = len(names) + 1
        workspace.create_season(label, state)
    return workspace


@pytest.fixture
def seasons(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_SEASONS_DIR", str(tmp_path / "seasons"))
    _make(tmp_path / "seasons", {"2025-podzim": ["Anna", "Petr"], "2026-jaro": ["Jana"]})
    return Workspace()


@pytest.fixture
async def user(seasons):
    async with user_simulation(root=root) as user:
        await user.open("/")
        yield user


@pytest.fixture
def sent(monkeypatch):
    """What the export dialog hands to the browser as a download."""
    captured = []
    monkeypatch.setattr(season_transfer, "_send", lambda data, filename: captured.append((data, filename)))
    return captured


def _ids(workspace):
    return {s["label"]: s["id"] for s in mutations.list_seasons(workspace)}


def _names(workspace, label):
    return [h["name"] for h in workspace.stored_state(_ids(workspace)[label])["helpers"]]


async def _upload(user, data: bytes, name="export.zip"):
    uploader = user.find(marker="import-seasons-upload").elements.pop()
    await uploader.handle_uploads([SmallFileUpload(name=name, content_type="", _data=data)])
    await asyncio.sleep(0.2)


# -- labels --------------------------------------------------------------------


def test_diff_lines_name_what_was_added_removed_and_changed():
    category = {
        "key": "helpers",
        "added": ["Jana"],
        "removed": ["Petr"],
        "changed": [{"label": "Anna", "fields": ["tshirt_size", "unknown_field"]}],
    }
    assert labels.diff_category_title(category) == "Pomocníci"
    assert labels.diff_category_lines(category) == [
        "+ Jana",
        "− Petr",
        "~ Anna (velikost trička, unknown_field)",
    ]


def test_a_part_reported_as_a_whole_reads_as_changed():
    category = {"key": "solver_config", "added": [], "removed": [], "changed": [{"label": "solver_config", "fields": []}]}
    assert labels.diff_category_lines(category) == ["~ změněno"]


# -- export --------------------------------------------------------------------


async def test_export_offers_every_season_ticked_and_downloads_a_zip(user, seasons, sent):
    user.find(marker="export-seasons").click()
    await user.should_see(marker="export-ok")
    assert len(user.find(marker="export-season").elements) == 2
    assert all(e.value for e in user.find(marker="export-season").elements)
    user.find(marker="export-ok").click()
    await asyncio.sleep(0.2)
    (data, filename), = sent
    assert filename.startswith("rostering-export-") and filename.endswith(".zip")
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    assert sorted(s["label"] for s in manifest["seasons"]) == ["2025-podzim", "2026-jaro"]


async def test_export_can_leave_seasons_and_versions_out(user, seasons, sent):
    mutations.save_version(seasons, "v1")
    user.find(marker="export-seasons").click()
    await user.should_see(marker="export-ok")
    for box in user.find(marker="export-season").elements:
        if "2025-podzim" in box.text:
            box.value = False
    user.find(marker="export-versions").elements.pop().value = False
    user.find(marker="export-ok").click()
    await asyncio.sleep(0.2)
    (data, _), = sent
    archive = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(archive.read("manifest.json"))
    assert [s["label"] for s in manifest["seasons"]] == ["2026-jaro"]
    assert not any("/versions/" in n for n in archive.namelist())


async def test_export_is_disabled_with_nothing_ticked(user, seasons, sent):
    user.find(marker="export-seasons").click()
    await user.should_see(marker="export-ok")
    for box in user.find(marker="export-season").elements:
        box.value = False
    assert user.find(marker="export-ok").elements.pop().enabled is False


# -- import --------------------------------------------------------------------


async def test_importing_a_file_of_new_seasons_adds_them(user, seasons, tmp_path):
    other = _make(tmp_path / "other" / "seasons", {"2024-jaro": ["Stará"]})
    await _upload(user, mutations.export_seasons(other))
    await user.should_see(marker="import-ok")
    assert user.find(marker="import-ok").elements.pop().enabled is True
    user.find(marker="import-ok").click()
    await asyncio.sleep(0.3)
    assert "2024-jaro" in _ids(seasons)
    assert _names(seasons, "2024-jaro") == ["Stará"]
    assert (seasons.root.parent / "backups").is_dir()  # the existing Seasons were backed up first


async def test_a_new_season_can_be_unticked(user, seasons, tmp_path):
    other = _make(tmp_path / "other" / "seasons", {"2024-jaro": ["Stará"]})
    await _upload(user, mutations.export_seasons(other))
    await user.should_see(marker="import-ok")
    user.find(marker="import-take").elements.pop().value = False
    user.find(marker="import-ok").click()
    await asyncio.sleep(0.3)
    assert "2024-jaro" not in _ids(seasons)


async def test_a_conflict_blocks_import_until_a_choice_is_made(user, seasons, tmp_path):
    colleague = Workspace(root=tmp_path / "colleague" / "seasons")
    mutations.import_seasons(colleague, mutations.export_seasons(seasons), {})
    mutations.add_helper(colleague, "Nový", "n@x.cz")
    await _upload(user, mutations.export_seasons(colleague))
    await user.should_see(marker="import-ok")
    assert user.find(marker="import-ok").elements.pop().enabled is False
    # The differences are listed.
    await user.should_see("+ Nový")

    choices = user.find(marker="import-choice").elements
    open_choice = next(c for c in choices if c.props.get("data-label") == "2026-jaro")
    assert len(choices) == 1  # 2025-podzim is identical to the stored one: nothing to decide
    open_choice.value = "replace"
    assert user.find(marker="import-ok").elements.pop().enabled is True
    user.find(marker="import-ok").click()
    await asyncio.sleep(0.3)
    assert "Nový" in _names(seasons, "2026-jaro")
    # The open Season was replaced, so the page shows its new contents.
    assert "Nový" in [h["name"] for h in mutations.get_state(seasons)["helpers"]]


async def test_keep_both_needs_a_label_and_adds_a_copy(user, seasons, tmp_path):
    colleague = Workspace(root=tmp_path / "colleague" / "seasons")
    mutations.import_seasons(colleague, mutations.export_seasons(seasons), {})
    mutations.add_helper(colleague, "Nový", "n@x.cz")
    await _upload(user, mutations.export_seasons(colleague))
    await user.should_see(marker="import-ok")
    choices = user.find(marker="import-choice").elements
    next(c for c in choices if c.props.get("data-label") == "2026-jaro").value = "keep_both"
    await asyncio.sleep(0.1)
    label_field = user.find(marker="import-new-label").elements.pop()
    assert label_field.value == "2026-podzim"  # the suggestion
    label_field.value = ""
    assert user.find(marker="import-ok").elements.pop().enabled is False
    label_field.value = "2027-jaro"
    assert user.find(marker="import-ok").elements.pop().enabled is True
    user.find(marker="import-ok").click()
    await asyncio.sleep(0.3)
    assert _names(seasons, "2027-jaro") == ["Jana", "Nový"]
    assert _names(seasons, "2026-jaro") == ["Jana"]


async def test_a_file_that_is_not_an_export_is_refused_with_a_message(user, seasons):
    await _upload(user, b"not a zip", name="x.zip")
    user.notify.contains("zip")
    assert len(_ids(seasons)) == 2
