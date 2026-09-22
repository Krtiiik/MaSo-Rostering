"""On-disk persistence for the web app's single working session.

There's exactly one "current" workspace (no multi-season juggling in the web
UI, per design) stored as one JSON blob under ``data/workspace/state.json``.
Named versions are just timestamped copies of that blob under
``data/workspace/versions/``. Everything here lives under the gitignored
``data/`` directory since it contains real helpers' personal data.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from rostering.domain import ManualRoles
from rostering.solver.model import SolverConfig
from rostering.persistence import config_store
from rostering.persistence.serialize import manual_roles_to_dict, solver_config_to_dict

# Overridable so tests (and anyone running multiple workspaces) don't have to
# touch the real data/workspace directory.
DEFAULT_ROOT = Path(os.environ.get("ROSTERING_WORKSPACE_DIR", "data/workspace"))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "version"


class Workspace:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root)
        self.versions_dir = self.root / "versions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"

    def empty_state(self) -> dict[str, Any]:
        return {
            "helpers": [],
            "ingestion_warnings": [],
            "config": config_store.load_default_config(),
            "solver_config": solver_config_to_dict(SolverConfig()),
            "assignments": [],
            "manual_roles": manual_roles_to_dict(ManualRoles()),
            # {building_name: [[room_a, room_b], ...]} — adjacent room pairs
            # currently merged into one display column in the roster grid
            # and Excel export (see rostering.domain.group_adjacent_rooms).
            # Empty by default: the unmerged, one-column-per-room layout.
            "room_merges": {},
            "diagnostics": {
                "status": None,
                "objective_value": None,
                "unsatisfied_friend_pairs": [],
                "satisfied_friend_pairs": [],
            },
        }

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self.empty_state()
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset(self) -> dict[str, Any]:
        state = self.empty_state()
        self.save(state)
        return state

    # -- versions ---------------------------------------------------------

    def _version_path(self, slug: str) -> Path:
        return self.versions_dir / f"{slug}.json"

    def list_versions(self) -> list[dict[str, Any]]:
        versions = []
        for path in self.versions_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = data.get("_meta", {})
            versions.append(
                {"slug": path.stem, "name": meta.get("name", path.stem), "created_at": meta.get("created_at")}
            )
        return sorted(versions, key=lambda v: v["created_at"] or "", reverse=True)

    def save_version(self, name: str) -> dict[str, Any]:
        state = self.load()
        created_at = datetime.now(timezone.utc).isoformat()
        state["_meta"] = {"name": name, "created_at": created_at}
        slug = f"{created_at.replace(':', '').replace('.', '')}-{_slugify(name)}"
        self._version_path(slug).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"slug": slug, "name": name, "created_at": created_at}

    def load_version(self, slug: str) -> Optional[dict[str, Any]]:
        path = self._version_path(slug)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def restore_version(self, slug: str) -> Optional[dict[str, Any]]:
        state = self.load_version(slug)
        if state is None:
            return None
        restored = {k: v for k, v in state.items() if k != "_meta"}
        self.save(restored)
        return restored

    def delete_version(self, slug: str) -> bool:
        path = self._version_path(slug)
        if not path.exists():
            return False
        path.unlink()
        return True
