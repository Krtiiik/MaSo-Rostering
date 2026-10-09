"""On-disk persistence for the web app's Seasons and the open Workspace.

Every Season is a stored, labelled unit: a directory ``<seasons root>/<label>/``
(``data/seasons/2026-jaro/`` by default) holding its saved state
(``state.json``) and its Versions (``versions/*.json``), next to any
hand-placed raw export and config. The Workspace is whichever Season a small
pointer file (``open-season.json`` in the seasons root) names, by Season id;
with no Season open the Workspace is a blank, unsaved draft that lives only in
memory until an upload creates a Season for it.

A Season's identity — its label and a random Season id — is stamped into its
saved state as ``state["season"]`` and owned by this class: callers never set
it, Versions never snapshot or roll it back, and a rename changes the label
(and renames the directory) but never the id, so anything that points at a
Season by id survives renames. Everything here lives under the gitignored
``data/`` directory since it contains real helpers' personal data.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from rostering import forced_friends, tags as tag_tree
from rostering.domain import ManualRoles
from rostering.persistence import config_store
from rostering.persons import PersonRecord, ensure_person_ids, records_from_state
from rostering.persistence.season_label import LABEL_FORMAT_HINT, label_sort_key, normalize_label
from rostering.persistence.serialize import manual_roles_to_dict, solver_config_to_dict
from rostering.solver.model import SolverConfig


class SeasonError(Exception):
    """A Season operation that can't be carried out (unknown id, duplicate or
    invalid label, deleting the open Season, ...). The message is meant to be
    shown to the user."""


def default_legacy_root() -> Path:
    """Where the pre-Seasons single saved state lived (``state.json`` plus a
    ``versions/`` folder). Overridable with ``ROSTERING_WORKSPACE_DIR``."""
    return Path(os.environ.get("ROSTERING_WORKSPACE_DIR", "data/workspace"))


def default_seasons_root() -> Path:
    """Directory holding one sub-directory per Season. Overridable with
    ``ROSTERING_SEASONS_DIR``; when only ``ROSTERING_WORKSPACE_DIR`` is set
    (an isolated run) the Seasons live under it too, so such a run never
    touches the real ``data/`` directory."""
    explicit = os.environ.get("ROSTERING_SEASONS_DIR")
    if explicit:
        return Path(explicit)
    isolated = os.environ.get("ROSTERING_WORKSPACE_DIR")
    if isolated:
        return Path(isolated) / "seasons"
    return Path("data/seasons")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "version"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _digests.pop(str(path), None)


class _Digest:
    """What scanning the Seasons and recognizing Persons read from one stored
    Season's ``state.json``, kept while the file is unchanged: the views redraw
    after every click and would otherwise parse every stored Season again."""

    def __init__(self) -> None:
        self.identity: Optional[dict[str, str]] = None
        self.helper_count = 0
        self.records: Optional[list[PersonRecord]] = None  # filled on first use


# state.json path -> ((mtime_ns, size) it was read at, its digest). A write
# through _write_json drops the entry; the file stamp catches any other writer.
_digests: dict[str, tuple[tuple[int, int], _Digest]] = {}


def _stamp(path: Path) -> Optional[tuple[int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _digest(state_path: Path) -> Optional[_Digest]:
    """The digest of a ``state.json`` (read now unless cached and unchanged),
    or None when it is missing or unreadable."""
    stamp = _stamp(state_path)
    if stamp is None:
        return None
    cached = _digests.get(str(state_path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        state = _read_json(state_path)
    except (OSError, ValueError):
        return None
    digest = _Digest()
    identity = state.get("season") if isinstance(state, dict) else None
    if isinstance(identity, dict) and identity.get("id") and normalize_label(identity.get("label")):
        digest.identity = {"id": identity["id"], "label": normalize_label(identity["label"])}
    digest.helper_count = len(state.get("helpers", [])) if isinstance(state, dict) else 0
    _digests[str(state_path)] = (stamp, digest)
    return digest


class Workspace:
    def __init__(self, root: Path | str | None = None, legacy_root: Path | str | None = None):
        """``root`` is the seasons directory. With no ``root`` the defaults
        (env-overridable, see above) are used, including the legacy location
        the first-launch migration reads; an explicitly given ``root`` has no
        legacy location unless ``legacy_root`` names one."""
        if root is None:
            self.root = default_seasons_root()
            self.legacy_root: Optional[Path] = Path(legacy_root) if legacy_root else default_legacy_root()
        else:
            self.root = Path(root)
            self.legacy_root = Path(legacy_root) if legacy_root else None
        self.root.mkdir(parents=True, exist_ok=True)
        self.pointer_path = self.root / "open-season.json"
        # Blank Workspace with no Season open: never persisted (see module doc).
        self._draft: Optional[dict[str, Any]] = None

    # -- the state itself -------------------------------------------------

    def empty_state(self) -> dict[str, Any]:
        return {
            "helpers": [],
            "ingestion_warnings": [],
            "config": config_store.load_default_config(),
            "solver_config": solver_config_to_dict(SolverConfig()),
            "assignments": [],
            "manual_roles": manual_roles_to_dict(ManualRoles()),
            # {row_key: {building_name: [[room_a, room_b], ...]}} — adjacent
            # room-pairs currently merged into one wider cell *for that one
            # row* (a solved role's key, or a room-scoped manual role's key)
            # in the roster grid and Excel export, like merging cells within
            # a single spreadsheet row (see
            # rostering.domain.group_adjacent_rooms). Other rows for the
            # same rooms are unaffected. Empty by default: the unmerged,
            # one-column-per-room layout for every row.
            "cell_merges": {},
            # Tall cells (see rostering.row_merges): {building, room, row} for
            # each pair of adjacent rows merged top-to-bottom over the same
            # Rooms. Presentational like cell_merges, but a merged cell holds
            # one set of people for all its roles. Part of every Version.
            "row_merges": [],
            # Why the roster is stale (see mutations.stale_reasons): set by an
            # edit that invalidates it without moving anyone, cleared by a full
            # Solve, and blocks Export while non-empty. Part of every Version.
            "stale_reasons": [],
            # The Season's Tags (see rostering.tags): dicts with id, name,
            # colour, note and parent_id. A Helper's direct Tags are the Tag
            # ids in its record's "tags"; effective Tags are computed, never
            # stored. Part of every Version and cleared by Start over.
            "tags": [],
            # Which earlier Seasons' Tags were imported into this one (see
            # mutations.import_from_season): source Season id -> {"label",
            # "deleted_tag_ids"} (the source Tags whose imported copy was
            # deliberately deleted). Part of every Version, cleared by Start over.
            "tag_imports": {},
            # The Season's Organizers (see rostering.organizers): tracked people
            # who are not Helpers, each with a single placement derived from the
            # Organizer role slot they hold. Part of every Version and cleared
            # by Start over; ids come from the high-water mark
            # "next_organizer_id" and are never reused.
            "organizers": [],
            # The Season's Forced friends groups (see rostering.forced_friends
            # and webapp.forced_groups): id, name, rules and members (each
            # a Person, by person_id). Part of every Version and cleared by
            # Start over; ids come from the high-water mark
            # "next_forced_group_id" and are never reused.
            "forced_groups": [],
            "diagnostics": {
                "status": None,
                "objective_value": None,
                "unsatisfied_friend_pairs": [],
                "satisfied_friend_pairs": [],
            },
        }

    def load(self) -> dict[str, Any]:
        open_season = self._resolve_open()
        if open_season is None:
            return copy.deepcopy(self._draft) if self._draft is not None else self.empty_state()
        return self._read_state(open_season["dir"])

    def _read_state(self, season_dir: Path) -> dict[str, Any]:
        """A stored Season's saved state. A state saved before Persons existed
        has Helper records with no ``person_id``: they get one here and it is
        written back at once, so the ids are stable from then on."""
        path = season_dir / "state.json"
        state = _read_json(path)
        # A state saved before Tags existed has none.
        state.setdefault("tags", [])
        state.setdefault("tag_imports", {})
        # ... and one saved before Organizers existed has none.
        state.setdefault("organizers", [])
        # ... and one saved before Forced friends groups existed has none.
        state.setdefault("forced_groups", [])
        # ... and a group saved before rules existed carries axes instead.
        migrated = forced_friends.migrate_state(state)
        # ... and a Tag saved before its constraints were rules carries four allow/deny lists.
        migrated = tag_tree.migrate_state(state) or migrated
        # ... and one saved before tall cells existed has none.
        state.setdefault("row_merges", [])
        if ensure_person_ids(state) or migrated:
            _write_json(path, state)
        return state

    def person_records(self) -> list[PersonRecord]:
        """The Helper records of every stored Season that has a saved state
        (the open one included; a directory without one is ignored), which is
        all a Person is made of: their e-mails and names are whatever these
        records carry, so a deleted or emptied Season no longer contributes."""
        records: list[PersonRecord] = []
        for season_dir, identity in self._scan():
            digest = _digest(season_dir / "state.json")
            if digest is None or digest.records is None:
                season_records = records_from_state(identity, self._read_state(season_dir))
                # _read_state may have written ids back: digest the file as it is now.
                digest = _digest(season_dir / "state.json")
                if digest is not None:
                    digest.records = season_records
            else:
                season_records = digest.records
            records.extend(season_records)
        return records

    def stored_state(self, season_id: str) -> Optional[dict[str, Any]]:
        """The saved state of any stored Season by id (the open one included),
        read only: nothing is opened, changed or written back. None when there
        is no such Season."""
        found = self._find_dir(season_id)
        return None if found is None else self._read_state(found[0])

    def save(self, state: dict[str, Any]) -> None:
        open_season = self._resolve_open()
        if open_season is None:
            self._draft = copy.deepcopy({k: v for k, v in state.items() if k != "season"})
            return
        state["season"] = {"id": open_season["id"], "label": open_season["label"]}
        _write_json(open_season["dir"] / "state.json", state)

    def reset(self) -> dict[str, Any]:
        """Empty the open Season's state ("Start over"): everything but its
        label, Season id and Versions. With no Season open, just blanks the
        draft."""
        state = self.empty_state()
        self.save(state)
        return self.load()

    # -- Seasons ----------------------------------------------------------

    def _read_pointer(self) -> Optional[dict[str, str]]:
        if not self.pointer_path.exists():
            return None
        try:
            data = _read_json(self.pointer_path)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("season_id"):
            return None
        return data

    def _write_pointer(self, season_id: str, label: str) -> None:
        _write_json(self.pointer_path, {"season_id": season_id, "label": label, "dir": label})

    def _identity_of(self, season_dir: Path) -> Optional[dict[str, str]]:
        """``{"id", "label"}`` of the Season stored in ``season_dir``, or None
        if it holds no saved state (or one without an identity) — such a
        directory is not a stored Season and is ignored."""
        state_path = season_dir / "state.json"
        if not season_dir.is_dir() or not state_path.is_file():
            return None
        digest = _digest(state_path)
        if digest is None or digest.identity is None:
            return None
        return dict(digest.identity)

    def _scan(self) -> Iterable[tuple[Path, dict[str, str]]]:
        for season_dir in sorted(self.root.iterdir()):
            identity = self._identity_of(season_dir)
            if identity is not None:
                yield season_dir, identity

    def _find_dir(self, season_id: str) -> Optional[tuple[Path, dict[str, str]]]:
        return next(((d, i) for d, i in self._scan() if i["id"] == season_id), None)

    def _resolve_open(self) -> Optional[dict[str, Any]]:
        """The open Season as ``{"id", "label", "dir"}``, or None when no
        Season is open (no pointer, or it names a Season that no longer
        exists)."""
        pointer = self._read_pointer()
        if pointer is None:
            return None
        hinted = self.root / pointer.get("dir", "")
        if pointer.get("dir") and (hinted / "state.json").is_file():
            # Trust the hint we maintain ourselves (a full parse of the state
            # on every load/save would be wasteful); the state's own identity
            # is verified only on the slow path below.
            return {"id": pointer["season_id"], "label": pointer.get("label", pointer["dir"]), "dir": hinted}
        found = self._find_dir(pointer["season_id"])
        if found is None:
            return None
        season_dir, identity = found
        return {"id": identity["id"], "label": identity["label"], "dir": season_dir}

    def open_season(self) -> Optional[dict[str, str]]:
        """Identity (``{"id", "label"}``) of the open Season, or None."""
        resolved = self._resolve_open()
        return None if resolved is None else {"id": resolved["id"], "label": resolved["label"]}

    def open_season_dir(self) -> Optional[Path]:
        """Directory of the open Season, or None when no Season is open."""
        resolved = self._resolve_open()
        return None if resolved is None else resolved["dir"]

    def _validated_label(self, label: Optional[str], ignore_id: Optional[str] = None) -> str:
        normalized = normalize_label(label)
        if normalized is None:
            raise SeasonError(f"Označení ročníku je {LABEL_FORMAT_HINT}.")
        for _, identity in self._scan():
            if identity["label"] == normalized and identity["id"] != ignore_id:
                raise SeasonError(f"Ročník s označením {normalized} již existuje.")
        return normalized

    def list_seasons(self) -> list[dict[str, Any]]:
        """Every stored Season, most recent first (the label orders them in
        time): ``id``, ``label``, ``helper_count`` and ``open``."""
        open_id = (self.open_season() or {}).get("id")
        seasons = []
        for season_dir, identity in self._scan():
            digest = _digest(season_dir / "state.json")
            helper_count = digest.helper_count if digest is not None else 0
            seasons.append(
                {**identity, "helper_count": helper_count, "open": identity["id"] == open_id}
            )
        return sorted(seasons, key=lambda s: label_sort_key(s["label"]), reverse=True)

    def create_season(self, label: str, state: Optional[dict[str, Any]] = None) -> dict[str, str]:
        """Store ``state`` (default: the current Workspace contents) as a new
        Season named ``label`` and open it."""
        label = self._validated_label(label)
        state = copy.deepcopy(state if state is not None else self.load())
        identity = {"id": uuid.uuid4().hex, "label": label}
        season_dir = self.root / label
        # A directory holding only hand-placed files (raw export, config) is
        # adopted as is; it just gains a saved state.
        (season_dir / "versions").mkdir(parents=True, exist_ok=True)
        state["season"] = identity
        _write_json(season_dir / "state.json", state)
        self._write_pointer(identity["id"], label)
        self._draft = None
        return identity

    def switch_to(self, season_id: str) -> dict[str, Any]:
        """Open a stored Season into the Workspace and return its state."""
        found = self._find_dir(season_id)
        if found is None:
            raise SeasonError("Takový ročník neexistuje.")
        _, identity = found
        self._write_pointer(identity["id"], identity["label"])
        self._draft = None
        return self.load()

    def close(self) -> dict[str, Any]:
        """Leave no Season open ("New Season"): the Workspace becomes a blank,
        unsaved draft; every stored Season stays stored. Returns that state."""
        self.pointer_path.unlink(missing_ok=True)
        self._draft = None
        return self.load()

    def rename_season(self, season_id: str, label: str) -> dict[str, str]:
        """Change a Season's label and rename its directory to match. The
        Season id and everything inside the directory (state, Versions,
        hand-placed files) are untouched."""
        found = self._find_dir(season_id)
        if found is None:
            raise SeasonError("Takový ročník neexistuje.")
        old_dir, identity = found
        label = self._validated_label(label, ignore_id=season_id)
        if label == identity["label"]:
            return identity
        new_dir = self.root / label
        if new_dir.exists():
            raise SeasonError(
                f"Nelze přejmenovat na {label}: složka s tímto názvem už v adresáři ročníků existuje."
            )
        old_dir.rename(new_dir)
        state = _read_json(new_dir / "state.json")
        state["season"] = {"id": season_id, "label": label}
        _write_json(new_dir / "state.json", state)
        pointer = self._read_pointer()
        if pointer is not None and pointer["season_id"] == season_id:
            self._write_pointer(season_id, label)
        return {"id": season_id, "label": label}

    def delete_season(self, season_id: str) -> None:
        """Delete a stored Season and its Versions. Refused for the open
        Season. Only what the app owns (saved state and Versions) is removed:
        hand-placed files in the directory (a raw export, a config) stay, and
        the directory itself goes only if that leaves it empty."""
        found = self._find_dir(season_id)
        if found is None:
            raise SeasonError("Takový ročník neexistuje.")
        if (self.open_season() or {}).get("id") == season_id:
            raise SeasonError("Otevřený ročník nelze smazat — nejdřív otevřete jiný ročník nebo začněte nový.")
        season_dir, _ = found
        (season_dir / "state.json").unlink()
        shutil.rmtree(season_dir / "versions", ignore_errors=True)
        try:
            season_dir.rmdir()  # only succeeds if nothing hand-placed is left
        except OSError:
            pass

    # -- first-launch migration of the pre-Seasons single saved state -----

    def legacy_state_path(self) -> Optional[Path]:
        """Path of a pre-Seasons saved state still waiting to be migrated
        into a Season, or None. A saved state with no Helpers and no Versions
        holds nothing worth keeping and is left alone."""
        if self.legacy_root is None:
            return None
        path = self.legacy_root / "state.json"
        if not path.is_file():
            return None
        try:
            has_helpers = bool(_read_json(path).get("helpers"))
        except (OSError, ValueError, AttributeError):
            return None
        versions_dir = self.legacy_root / "versions"
        has_versions = versions_dir.is_dir() and any(versions_dir.glob("*.json"))
        return path if has_helpers or has_versions else None

    def legacy_state(self) -> Optional[dict[str, Any]]:
        path = self.legacy_state_path()
        return None if path is None else _read_json(path)

    def migrate_legacy(self, label: str) -> dict[str, str]:
        """Move the pre-Seasons saved state and its Versions into a new Season
        named ``label`` and open it."""
        state_path = self.legacy_state_path()
        if state_path is None:
            raise SeasonError("Není žádný dřívější uložený stav k převedení.")
        label = self._validated_label(label)
        identity = {"id": uuid.uuid4().hex, "label": label}
        season_dir = self.root / label
        (season_dir / "versions").mkdir(parents=True, exist_ok=True)
        for version_path in (self.legacy_root / "versions").glob("*.json"):
            shutil.move(str(version_path), str(season_dir / "versions" / version_path.name))
        state = _read_json(state_path)
        state["season"] = identity
        _write_json(season_dir / "state.json", state)
        state_path.unlink()
        self._write_pointer(identity["id"], label)
        self._draft = None
        return identity

    # -- versions (each one belongs to the open Season) --------------------

    def _versions_dir(self) -> Path:
        open_season = self._resolve_open()
        if open_season is None:
            raise SeasonError("Není otevřen žádný ročník — nejdřív nahráním odpovědí nějaký vytvořte.")
        path = open_season["dir"] / "versions"
        path.mkdir(exist_ok=True)
        return path

    def _version_path(self, slug: str) -> Path:
        return self._versions_dir() / f"{slug}.json"

    def list_versions(self) -> list[dict[str, Any]]:
        if self._resolve_open() is None:
            return []
        versions = []
        for path in self._versions_dir().glob("*.json"):
            meta = _read_json(path).get("_meta", {})
            versions.append(
                {"slug": path.stem, "name": meta.get("name", path.stem), "created_at": meta.get("created_at")}
            )
        return sorted(versions, key=lambda v: v["created_at"] or "", reverse=True)

    def save_version(self, name: str) -> dict[str, Any]:
        """Snapshot the open Season's whole state, minus its identity."""
        versions_dir = self._versions_dir()
        state = {k: v for k, v in self.load().items() if k != "season"}
        created_at = datetime.now(timezone.utc).isoformat()
        state["_meta"] = {"name": name, "created_at": created_at}
        slug = f"{created_at.replace(':', '').replace('.', '')}-{_slugify(name)}"
        _write_json(versions_dir / f"{slug}.json", state)
        return {"slug": slug, "name": name, "created_at": created_at}

    def load_version(self, slug: str) -> Optional[dict[str, Any]]:
        path = self._version_path(slug)
        if not path.exists():
            return None
        state = _read_json(path)
        forced_friends.migrate_state(state)
        tag_tree.migrate_state(state)
        return state

    def restore_version(self, slug: str) -> Optional[dict[str, Any]]:
        """Roll the open Season's state back to a Version. Everything the
        Season holds is rolled back except its identity (label and Season id),
        which is always kept as it is now."""
        state = self.load_version(slug)
        if state is None:
            return None
        self.save({k: v for k, v in state.items() if k not in ("_meta", "season")})
        return self.load()

    def delete_version(self, slug: str) -> bool:
        path = self._version_path(slug)
        if not path.exists():
            return False
        path.unlink()
        return True
