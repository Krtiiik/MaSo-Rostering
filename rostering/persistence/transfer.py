"""The Season export file: a .zip that carries stored Seasons between machines.

Layout::

    manifest.json
    seasons/<label>/state.json
    seasons/<label>/versions/<slug>.json      (only when Versions were included)

``manifest.json`` says what the file is (``format``, ``schema_version``,
``app_version``, ``exported_at``), which Season was open, and lists each Season
(``id``, ``label``, ``dir``, counts, ``modified_at``) so an import can preview
the file without parsing every state. Raw uploads, hand-placed files and the
app-wide default layout are not part of it: a Season's saved state already holds
everything parsed from them.

Reading is strict and happens in full before anything is applied; this module
does no I/O beyond the archive bytes (and the staging writer), so the Workspace
decides what to do with a valid package.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from rostering.persistence.season_label import label_sort_key, normalize_label

FORMAT = "rostering-export"

# Bumped when the files in the archive change shape incompatibly. A file from a
# newer schema is refused; an older one is read, its states migrating on load
# like any stored Season's.
SCHEMA_VERSION = 1

# A cap on what an archive may unpack to, so a hostile or corrupt file cannot
# exhaust memory (real exports are a few megabytes).
MAX_UNPACKED_BYTES = 512 * 1024 * 1024

_DIR_RE = re.compile(r"^[\w.\- ]+$")


class TransferError(Exception):
    """A file that cannot be read as a Season export, or an export that cannot
    be made. The message is meant to be shown to the user."""


@dataclass
class SeasonExport:
    """One Season going into a file."""

    id: str
    label: str
    state: dict[str, Any]
    versions: dict[str, dict[str, Any]] = field(default_factory=dict)  # slug -> the Version's JSON
    modified_at: Optional[str] = None


@dataclass
class PackageSeason:
    """One Season read from a file."""

    id: str
    label: str
    state: dict[str, Any]
    versions: dict[str, dict[str, Any]]
    modified_at: Optional[str]


@dataclass
class Package:
    schema_version: int
    app_version: str
    exported_at: Optional[str]
    open_season_id: Optional[str]
    includes_versions: bool
    seasons: list[PackageSeason]


def app_version() -> str:
    try:
        from importlib.metadata import version

        return version("rostering")
    except Exception:  # not installed as a distribution (a source checkout)
        return ""


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_package(
    seasons: list[SeasonExport], open_season_id: Optional[str], include_versions: bool
) -> bytes:
    """The archive for ``seasons``. The open Season is recorded only when it is
    one of them."""
    ordered = sorted(seasons, key=lambda s: label_sort_key(s.label))
    exported_ids = {s.id for s in ordered}
    manifest = {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": app_version(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "open_season_id": open_season_id if open_season_id in exported_ids else None,
        "include_versions": include_versions,
        "seasons": [
            {
                "id": s.id,
                "label": s.label,
                "dir": s.label,
                "helper_count": len(s.state.get("helpers", [])),
                "organizer_count": len(s.state.get("organizers", [])),
                "assignment_count": len(s.state.get("assignments", [])),
                "version_count": len(s.versions) if include_versions else 0,
                "modified_at": s.modified_at,
            }
            for s in ordered
        ],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _dumps(manifest))
        for s in ordered:
            archive.writestr(f"seasons/{s.label}/state.json", _dumps(s.state))
            if include_versions:
                for slug, version in s.versions.items():
                    archive.writestr(f"seasons/{s.label}/versions/{slug}.json", _dumps(version))
    return out.getvalue()


def _fail_json(name: str) -> TransferError:
    return TransferError(f"Soubor {name} v archivu nelze přečíst.")


def read_package(data: bytes) -> Package:
    """Parse and validate an export file in full, or raise
    :class:`TransferError` saying what is wrong with it."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise TransferError("Soubor není platný archiv zip s exportem ročníků.") from exc
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED_BYTES:
            raise TransferError("Archiv je po rozbalení příliš velký.")
        names = set(archive.namelist())
        if "manifest.json" not in names:
            raise TransferError("V archivu chybí manifest.json — nejde o export ročníků.")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except ValueError as exc:
            raise _fail_json("manifest.json") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise TransferError("manifest.json nepopisuje export ročníků.")
        schema = manifest.get("schema_version")
        if not isinstance(schema, int) or isinstance(schema, bool):
            raise TransferError("V manifest.json chybí verze formátu.")
        if schema > SCHEMA_VERSION:
            raise TransferError(
                "Soubor vytvořila novější verze aplikace "
                f"({manifest.get('app_version') or 'neznámá'}); aktualizujte aplikaci a zkuste to znovu."
            )
        listed = manifest.get("seasons")
        if not isinstance(listed, list):
            raise TransferError("V manifest.json chybí seznam ročníků.")

        seasons: list[PackageSeason] = []
        seen_ids: set[str] = set()
        seen_labels: set[str] = set()
        for entry in listed:
            seasons.append(_read_season(archive, names, entry, seen_ids, seen_labels))

    open_id = manifest.get("open_season_id")
    return Package(
        schema_version=schema,
        app_version=str(manifest.get("app_version") or ""),
        exported_at=manifest.get("exported_at"),
        open_season_id=open_id if open_id in seen_ids else None,
        includes_versions=bool(manifest.get("include_versions", False)),
        seasons=seasons,
    )


def _read_season(
    archive: zipfile.ZipFile, names: set[str], entry: Any, seen_ids: set[str], seen_labels: set[str]
) -> PackageSeason:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
        raise TransferError("V manifest.json je ročník bez identifikátoru.")
    label = normalize_label(entry.get("label"))
    if label is None:
        raise TransferError(f"Ročník má neplatné označení: {entry.get('label')!r}.")
    if entry["id"] in seen_ids or label in seen_labels:
        raise TransferError(f"Ročník {label} je v souboru uveden dvakrát.")
    seen_ids.add(entry["id"])
    seen_labels.add(label)
    folder = entry.get("dir", label)
    if not isinstance(folder, str) or not _DIR_RE.match(folder) or folder in (".", ".."):
        raise TransferError(f"Ročník {label} má neplatnou složku v archivu.")
    state_name = f"seasons/{folder}/state.json"
    if state_name not in names:
        raise TransferError(f"V archivu chybí stav ročníku {label} ({state_name}).")
    try:
        state = json.loads(archive.read(state_name))
    except ValueError as exc:
        raise _fail_json(state_name) from exc
    if not isinstance(state, dict):
        raise _fail_json(state_name)
    identity = state.get("season")
    if not isinstance(identity, dict) or identity.get("id") != entry["id"]:
        raise TransferError(f"Stav ročníku {label} nepatří k ročníku uvedenému v manifestu.")
    state["season"] = {"id": entry["id"], "label": label}

    versions: dict[str, dict[str, Any]] = {}
    prefix = f"seasons/{folder}/versions/"
    for name in sorted(n for n in names if n.startswith(prefix) and n.endswith(".json")):
        slug = name[len(prefix) : -len(".json")]
        if "/" in slug or not slug:
            continue
        try:
            version = json.loads(archive.read(name))
        except ValueError as exc:
            raise _fail_json(name) from exc
        if not isinstance(version, dict):
            raise _fail_json(name)
        versions[slug] = version
    return PackageSeason(
        id=entry["id"],
        label=label,
        state=state,
        versions=versions,
        modified_at=entry.get("modified_at"),
    )


def write_staged_season(directory: Path, state: dict[str, Any], versions: dict[str, dict[str, Any]]) -> None:
    """Write one Season (``state.json`` and ``versions/*.json``) into a fresh
    staging ``directory``, ready to be moved into place."""
    directory.mkdir(parents=True)
    (directory / "state.json").write_text(_dumps(state), encoding="utf-8")
    if versions:
        (directory / "versions").mkdir()
        for slug, version in versions.items():
            (directory / "versions" / f"{slug}.json").write_text(_dumps(version), encoding="utf-8")
