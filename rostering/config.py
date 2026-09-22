"""Season configuration: buildings, rooms, and per-role headcounts.

The YAML shape has always been tolerant of a couple of historical variants
(see the real files under data/seasons/*/config.yaml), so loading happens in
two steps: first sniff out the raw shape (dict-of-rooms vs list-of-buildings,
building-level scalar role counts vs per-room dicts), then hand the
normalized values to pydantic models for validation/coercion.

A role's capacity is a minimum headcount, written as a bare int. There is no
upper bound — with the small helper counts this project deals with, capping
a room's headcount has never been necessary. Older files may still carry a
``{min: X, max: Y}`` mapping from before the upper bound was removed; ``max``
is simply ignored when present.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict

from rostering.domain import Building, Role, RoleCapacity, Room, normalize_name

CapacityInput = Union[int, dict]


class RoleCapacityModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum: int = 0

    def to_domain(self) -> RoleCapacity:
        return RoleCapacity(minimum=self.minimum)


def _parse_capacity(value: CapacityInput, context: str) -> RoleCapacityModel:
    if isinstance(value, dict):
        minimum = value.get("min", value.get("minimum", 0))
        return RoleCapacityModel(minimum=int(minimum))
    try:
        return RoleCapacityModel(minimum=int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid capacity value for {context}: {value!r}") from exc


def _parse_role(role_name: str) -> Optional[Role]:
    lookup = normalize_name(role_name)
    for role in Role:
        if normalize_name(role.value) == lookup or normalize_name(role.name) == lookup:
            return role
    return None


def _parse_role_capacity_map(mapping: object, context: str) -> dict[Role, RoleCapacity]:
    result: dict[Role, RoleCapacity] = {}
    if not isinstance(mapping, dict):
        return result
    for role_name, raw_value in mapping.items():
        role = _parse_role(str(role_name))
        if role is None:
            continue  # not a role key (e.g. a nested room name) — ignore
        result[role] = _parse_capacity(raw_value, f"{context}.{role_name}").to_domain()
    return result


def load_buildings(config_path: str | Path) -> dict[str, Building]:
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    if isinstance(config_data, dict) and isinstance(config_data.get("buildings"), (dict, list)):
        raw_buildings = config_data["buildings"]
    elif isinstance(config_data, dict):
        raw_buildings = config_data
    else:
        raw_buildings = {}

    buildings: dict[str, Building] = {}

    if isinstance(raw_buildings, dict):
        for building_key, building_data in raw_buildings.items():
            name = str(building_key)
            rooms: list[Room] = []
            building_capacities: dict[Role, RoleCapacity] = {}

            if isinstance(building_data, dict):
                for sub_key, sub_val in building_data.items():
                    if isinstance(sub_val, dict) and _parse_role(str(sub_key)) is None:
                        # a room: its value is a {Role: count} mapping
                        room_caps = _parse_role_capacity_map(sub_val, f"{name}.{sub_key}")
                        rooms.append(Room(name=str(sub_key), capacities=room_caps))
                    else:
                        role = _parse_role(str(sub_key))
                        if role is None:
                            continue
                        building_capacities[role] = _parse_capacity(sub_val, f"{name}.{sub_key}").to_domain()

            buildings[name] = Building(name=name, rooms=rooms, capacities=building_capacities)

    elif isinstance(raw_buildings, list):
        for building_entry in raw_buildings:
            if not isinstance(building_entry, dict):
                continue
            name = building_entry.get("name")
            if not name:
                continue

            rooms = []
            raw_rooms = building_entry.get("rooms") or {}
            if isinstance(raw_rooms, dict):
                for room_name, room_map in raw_rooms.items():
                    room_caps = _parse_role_capacity_map(room_map, f"{name}.{room_name}")
                    rooms.append(Room(name=str(room_name), capacities=room_caps))

            role_reqs = building_entry.get("role_requirements") or building_entry.get("requirements") or {}
            building_capacities = _parse_role_capacity_map(role_reqs, str(name))

            buildings[str(name)] = Building(name=str(name), rooms=rooms, capacities=building_capacities)

    return buildings
