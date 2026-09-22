"""JSON (de)serialization for the domain model, used by the web app's
workspace state and API payloads. Keeps the wire format decoupled from the
dataclasses so the frontend only ever sees plain strings for enums."""
from __future__ import annotations

from typing import Any, Optional

from rostering.domain import (
    Assignment,
    Building,
    Helper,
    ManualRoles,
    OverlayAssignment,
    OverlayRole,
    Preference,
    Role,
    RoleCapacity,
    Room,
    StructuralAssignment,
    StructuralRole,
)
from rostering.ingest.preferences import parse_role_token
from rostering.solver.model import SolverConfig, SolverWeights
from rostering.solver.scoring import FriendScoringConfig, FriendScoringMode


def role_capacity_to_dict(cap: RoleCapacity) -> dict:
    return {"minimum": cap.minimum}


def role_capacity_from_dict(data: dict) -> RoleCapacity:
    return RoleCapacity(minimum=int(data.get("minimum", 0)))


def _role_caps_to_dict(caps: dict[Role, RoleCapacity]) -> dict[str, dict]:
    return {role.name: role_capacity_to_dict(cap) for role, cap in caps.items()}


def _role_caps_from_dict(data: dict) -> dict[Role, RoleCapacity]:
    result: dict[Role, RoleCapacity] = {}
    for role_name, cap_data in (data or {}).items():
        role = parse_role_token(role_name)
        if role is not None:
            result[role] = role_capacity_from_dict(cap_data)
    return result


def room_to_dict(room: Room) -> dict:
    return {"name": room.name, "capacities": _role_caps_to_dict(room.capacities)}


def room_from_dict(data: dict) -> Room:
    return Room(name=data["name"], capacities=_role_caps_from_dict(data.get("capacities", {})))


def building_to_dict(building: Building) -> dict:
    return {
        "name": building.name,
        "rooms": [room_to_dict(r) for r in building.rooms],
        "capacities": _role_caps_to_dict(building.capacities),
    }


def building_from_dict(data: dict) -> Building:
    return Building(
        name=data["name"],
        rooms=[room_from_dict(r) for r in data.get("rooms", [])],
        capacities=_role_caps_from_dict(data.get("capacities", {})),
    )


def config_to_list(buildings: dict[str, Building]) -> list[dict]:
    return [building_to_dict(b) for b in buildings.values()]


def config_from_list(data: list[dict]) -> dict[str, Building]:
    result: dict[str, Building] = {}
    for entry in data:
        b = building_from_dict(entry)
        result[b.name] = b
    return result


def helper_to_dict(h: Helper) -> dict:
    return {
        "id": h.id,
        "name": h.name,
        "role_preferences": {role.name: pref.name for role, pref in h.role_preferences.items()},
        "building_preferences": sorted(h.building_preferences),
        "friends": list(h.friends),
        "can_bring_notebook": h.can_bring_notebook,
        "can_bring_camera": h.can_bring_camera,
        "unresolved_friend_names": list(h.unresolved_friend_names),
    }


def helper_from_dict(data: dict) -> Helper:
    role_preferences = {}
    for role_name, pref_name in (data.get("role_preferences") or {}).items():
        role = parse_role_token(role_name)
        try:
            pref = Preference[pref_name]
        except KeyError:
            pref = None
        if role is not None and pref is not None:
            role_preferences[role] = pref
    return Helper(
        id=int(data["id"]),
        name=data["name"],
        role_preferences=role_preferences,
        building_preferences=frozenset(data.get("building_preferences", [])),
        friends=list(data.get("friends", [])),
        can_bring_notebook=bool(data.get("can_bring_notebook", False)),
        can_bring_camera=bool(data.get("can_bring_camera", False)),
        unresolved_friend_names=list(data.get("unresolved_friend_names", [])),
    )


def assignment_to_dict(a: Assignment) -> dict:
    return {
        "helper_id": a.helper_id,
        "helper_name": a.helper_name,
        "building": a.building,
        "room": a.room,
        "role": a.role.name,
    }


def assignment_from_dict(data: dict) -> Assignment:
    role = parse_role_token(data["role"])
    if role is None:
        raise ValueError(f"Unknown role: {data['role']!r}")
    return Assignment(
        helper_id=int(data["helper_id"]),
        helper_name=data["helper_name"],
        building=data["building"],
        room=data["room"],
        role=role,
    )


def _match_enum(enum_cls, value: str):
    for member in enum_cls:
        if member.name == value or member.value == value:
            return member
    raise ValueError(f"Unknown {enum_cls.__name__}: {value!r}")


def manual_roles_to_dict(manual: ManualRoles) -> dict:
    return {
        "structural": [
            {
                "role": s.role.name,
                "building": s.building,
                "room": s.room,
                "helper_id": s.helper_id,
                "helper_name": s.helper_name,
            }
            for s in manual.structural
        ],
        "overlay": [
            {
                "role": o.role.name,
                "helper_id": o.helper_id,
                "helper_name": o.helper_name,
                "building": o.building,
                "room": o.room,
            }
            for o in manual.overlay
        ],
    }


def manual_roles_from_dict(data: dict) -> ManualRoles:
    structural = [
        StructuralAssignment(
            role=_match_enum(StructuralRole, s["role"]),
            building=s["building"],
            room=s.get("room"),
            helper_id=s.get("helper_id"),
            helper_name=s.get("helper_name"),
        )
        for s in (data or {}).get("structural", [])
    ]
    overlay = [
        OverlayAssignment(
            role=_match_enum(OverlayRole, o["role"]),
            helper_id=o.get("helper_id"),
            helper_name=o.get("helper_name"),
            building=o.get("building"),
            room=o.get("room"),
        )
        for o in (data or {}).get("overlay", [])
    ]
    return ManualRoles(structural=structural, overlay=overlay)


def solver_config_to_dict(config: SolverConfig) -> dict:
    return {
        "weights": {
            "role_preference": config.weights.role_preference,
            "building_mismatch": config.weights.building_mismatch,
            "friend_unsatisfied": config.weights.friend_unsatisfied,
        },
        "friend_scoring": {
            "mode": config.friend_scoring.mode.value,
            "symmetric": config.friend_scoring.symmetric,
            "weight": config.friend_scoring.weight,
        },
        "time_limit_seconds": config.time_limit_seconds,
    }


def solver_config_from_dict(data: dict) -> SolverConfig:
    data = data or {}
    weights_data = data.get("weights", {})
    friend_data = data.get("friend_scoring", {})
    return SolverConfig(
        weights=SolverWeights(
            role_preference=weights_data.get("role_preference", 1),
            building_mismatch=weights_data.get("building_mismatch", 10),
            friend_unsatisfied=weights_data.get("friend_unsatisfied", 5),
        ),
        friend_scoring=FriendScoringConfig(
            mode=FriendScoringMode(friend_data.get("mode", "pairwise")),
            symmetric=friend_data.get("symmetric", True),
            weight=friend_data.get("weight", 1),
        ),
        time_limit_seconds=data.get("time_limit_seconds", 10.0),
    )
