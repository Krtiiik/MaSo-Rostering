"""Persistent default buildings/rooms layout for the web app.

Kept as its own YAML file next to the workspace (``data/buildings-config.yaml``
by default) rather than only inside the gitignored, ephemeral
``data/workspace/state.json`` blob. This means a saved building/room layout
survives "start over" resets and app restarts, the same way
``data/seasons/*/config.yaml`` persists across CLI runs. The file is seeded
on first use from ``default-buildings-config.yaml`` (a copy of the most
recent season's roster, bundled with the package), and is overwritten
whenever the user saves changes on the Buildings page.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml

from rostering.config import load_buildings
from rostering.persistence.serialize import config_to_list

_BUNDLED_DEFAULT = Path(__file__).resolve().parent / "default-buildings-config.yaml"

# Overridable so tests (and anyone running multiple workspaces) don't have to
# touch the real data/buildings-config.yaml.
DEFAULT_CONFIG_PATH = Path(os.environ.get("ROSTERING_BUILDINGS_CONFIG_PATH", "data/buildings-config.yaml"))


def load_default_config(path: Path = DEFAULT_CONFIG_PATH) -> list[dict]:
    """Load the persistent buildings/rooms config, seeding it from the
    bundled default the first time it's needed."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_BUNDLED_DEFAULT, path)
    return config_to_list(load_buildings(path))


def _capacity_to_yaml(cap: dict) -> int | dict:
    minimum = cap.get("minimum", 0)
    maximum = cap.get("maximum")
    return minimum if maximum is None else {"min": minimum, "max": maximum}


def save_default_config(buildings: list[dict], path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Write the given buildings/rooms config as the new persistent default."""
    data: dict = {}
    for building in buildings:
        entry: dict = {}
        for room in building.get("rooms", []):
            entry[room["name"]] = {role: _capacity_to_yaml(cap) for role, cap in room.get("capacities", {}).items()}
        for role, cap in building.get("capacities", {}).items():
            entry[role] = _capacity_to_yaml(cap)
        data[building["name"]] = entry

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
