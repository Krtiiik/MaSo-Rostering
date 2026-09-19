"""Loader for the simplified per-season helpers CSV.

Two shapes are accepted:

- **Canonical** (written by ``rostering.cli ingest``): columns
  ``id,name,role_preferences,building_preferences,friends,can_bring_notebook,
  can_bring_camera``, where ``building_preferences`` is a semicolon-separated
  list (the place question is multi-select, see CLAUDE.md).
- **Legacy** (hand-written or produced by the old ``utils/parse_helpers.py``):
  columns ``id,name,role_preferences,building_preference,friends`` — a single
  building and no equipment columns. Since eligibility can't be inferred from
  this shape, ``can_bring_notebook``/``can_bring_camera`` default to
  ``False`` and a warning is raised recommending re-ingestion from the raw
  survey export instead.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from rostering.domain import Helper
from rostering.ingest.preferences import parse_preference, parse_role_token


@dataclass
class LegacyCsvResult:
    helpers: list[Helper]
    warnings: list[str]


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "ano")


def load_helpers_csv(csv_path: str | Path) -> LegacyCsvResult:
    helpers: list[Helper] = []
    warnings: list[str] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        is_canonical = "building_preferences" in fieldnames
        if not is_canonical:
            warnings.append(
                f"{csv_path}: legacy single-building CSV format detected — "
                "can_bring_notebook/can_bring_camera default to False for "
                "every helper. Re-ingest from the raw survey export "
                "(rostering.ingest.raw_survey) to get accurate equipment "
                "eligibility."
            )

        for row in reader:
            raw_id = (row.get("id") or "").strip()
            try:
                helper_id = int(raw_id)
            except ValueError as exc:
                raise ValueError(f"Invalid helper id {raw_id!r} in {csv_path}") from exc

            name = (row.get("name") or "").strip()

            role_preferences = {}
            for pair in (row.get("role_preferences") or "").split(";"):
                if not pair.strip() or "=" not in pair:
                    continue
                role_name, pref_name = pair.split("=", 1)
                role = parse_role_token(role_name.strip())
                pref = parse_preference(pref_name.strip())
                if role is not None and pref is not None:
                    role_preferences[role] = pref

            if is_canonical:
                buildings_raw = (row.get("building_preferences") or "").strip()
                building_preferences = frozenset(
                    b.strip() for b in buildings_raw.split(";") if b.strip()
                )
                can_bring_notebook = _parse_bool(row.get("can_bring_notebook") or "")
                can_bring_camera = _parse_bool(row.get("can_bring_camera") or "")
            else:
                single_building = (row.get("building_preference") or "").strip()
                building_preferences = frozenset({single_building}) if single_building else frozenset()
                can_bring_notebook = False
                can_bring_camera = False

            friends_raw = (row.get("friends") or "").strip()
            friends = [int(x.strip()) for x in friends_raw.split(",") if x.strip()]

            helpers.append(
                Helper(
                    id=helper_id,
                    name=name,
                    role_preferences=role_preferences,
                    building_preferences=building_preferences,
                    friends=friends,
                    can_bring_notebook=can_bring_notebook,
                    can_bring_camera=can_bring_camera,
                )
            )

    return LegacyCsvResult(helpers=helpers, warnings=warnings)


def write_helpers_csv(helpers: list[Helper], csv_path: str | Path) -> None:
    """Write the canonical CSV shape (used by ``rostering.cli ingest``)."""
    fieldnames = [
        "id",
        "name",
        "role_preferences",
        "building_preferences",
        "friends",
        "can_bring_notebook",
        "can_bring_camera",
        "unresolved_friends",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for h in helpers:
            writer.writerow(
                {
                    "id": h.id,
                    "name": h.name,
                    "role_preferences": ";".join(
                        f"{role.name}={pref.name}" for role, pref in h.role_preferences.items()
                    ),
                    "building_preferences": ";".join(sorted(h.building_preferences)),
                    "friends": ",".join(str(fid) for fid in h.friends),
                    "can_bring_notebook": str(h.can_bring_notebook).lower(),
                    "can_bring_camera": str(h.can_bring_camera).lower(),
                    "unresolved_friends": ";".join(h.unresolved_friend_names),
                }
            )
