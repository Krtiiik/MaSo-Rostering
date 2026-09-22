"""State-mutation functions for the Streamlit app.

Each function mirrors one route of the old FastAPI backend
(``rostering/webapp/api.py``, since deleted): it takes the workspace plus
whatever the UI just did, mutates the JSON-shaped workspace state, persists
it, and returns the new state dict. Kept free of any Streamlit import so it
can be unit-tested directly and reused unchanged by any future caller.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from rostering.domain import Competition, ManualRoles, SolveResult
from rostering.export.excel import write_roster
from rostering.ingest.raw_survey import parse_raw_survey
from rostering.persistence import config_store
from rostering.persistence.serialize import (
    assignment_from_dict,
    assignment_to_dict,
    config_from_list,
    helper_from_dict,
    helper_to_dict,
    manual_roles_from_dict,
    manual_roles_to_dict,
    solver_config_from_dict,
    solver_config_to_dict,
)
from rostering.persistence.workspace import Workspace
from rostering.solver.model import solve_competition
from rostering.solver.scoring import build_friend_pairs


class RosteringError(Exception):
    """Raised for any user-facing error a mutation function hits (bad input,
    unknown id, infeasible precondition, ...). Tabs catch this and show
    ``st.error(str(exc))``."""


def _prune_cell_merges(config: list[dict], cell_merges: dict) -> dict:
    """Drop merge pairs that no longer name two actually-adjacent rooms
    (e.g. after a room was renamed, reordered, or removed in the Buildings
    tab), so stale state never lingers or misapplies to the wrong rooms."""
    building_adjacent: dict[str, set[tuple[str, str]]] = {}
    for b in config:
        names = [r["name"] for r in b["rooms"]]
        building_adjacent[b["name"]] = {(names[i], names[i + 1]) for i in range(len(names) - 1)}

    pruned: dict[str, dict[str, list[list[str]]]] = {}
    for row_key, by_building in cell_merges.items():
        kept: dict[str, list[list[str]]] = {}
        for building, pairs in by_building.items():
            adjacent = building_adjacent.get(building, set())
            valid = [list(p) for p in pairs if tuple(p) in adjacent]
            if valid:
                kept[building] = valid
        if kept:
            pruned[row_key] = kept
    return pruned


def _build_competition(state: dict[str, Any]) -> Competition:
    buildings = config_from_list(state["config"])
    helpers = [helper_from_dict(h) for h in state["helpers"]]
    return Competition(buildings=buildings, helpers=helpers)


def _recompute_friend_pairs(state: dict[str, Any]) -> tuple[list[list[int]], list[list[int]]]:
    """Return (satisfied, unsatisfied) friend pairs given the current assignments."""
    helpers = [helper_from_dict(h) for h in state["helpers"]]
    friend_scoring = solver_config_from_dict(state["solver_config"]).friend_scoring
    pairs = build_friend_pairs(helpers, friend_scoring)
    room_by_helper = {a["helper_id"]: (a["building"], a["room"]) for a in state["assignments"]}
    satisfied, unsatisfied = [], []
    for a_id, b_id, _weight in pairs:
        if room_by_helper.get(a_id) is not None and room_by_helper.get(a_id) == room_by_helper.get(b_id):
            satisfied.append([a_id, b_id])
        else:
            unsatisfied.append([a_id, b_id])
    return satisfied, unsatisfied


def get_state(workspace: Workspace) -> dict:
    return workspace.load()


def reset_workspace(workspace: Workspace) -> dict:
    return workspace.reset()


def upload_responses(workspace: Workspace, file_bytes: bytes, filename: str) -> dict:
    suffix = Path(filename or "upload.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        result = parse_raw_survey(tmp_path)
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    state = workspace.load()
    state["helpers"] = [helper_to_dict(h) for h in result.helpers]
    state["ingestion_warnings"] = result.warnings
    state["assignments"] = []
    state["diagnostics"] = {
        "status": None,
        "objective_value": None,
        "unsatisfied_friend_pairs": [],
        "satisfied_friend_pairs": [],
    }
    workspace.save(state)
    return state


def resolve_friend(
    workspace: Workspace,
    helper_id: int,
    name: str,
    action: str,
    resolved_helper_id: Optional[int] = None,
) -> dict:
    state = workspace.load()
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    if helper is None:
        raise RosteringError(f"No such helper: {helper_id}")
    decisions = helper.setdefault("friend_name_decisions", {})
    if name not in helper["unresolved_friend_names"] and name not in decisions:
        raise RosteringError(f"{name!r} is not a known friend name for helper {helper_id}")

    previous_id = decisions.get(name)
    if previous_id is not None and previous_id in helper["friends"]:
        helper["friends"].remove(previous_id)

    if action == "resolve":
        if resolved_helper_id is None:
            raise RosteringError("resolved_helper_id is required for action=resolve")
        known_ids = {h["id"] for h in state["helpers"]}
        if resolved_helper_id not in known_ids:
            raise RosteringError(f"No such helper: {resolved_helper_id}")
        if resolved_helper_id not in helper["friends"]:
            helper["friends"].append(resolved_helper_id)
        decisions[name] = resolved_helper_id
    elif action == "dismiss":
        decisions[name] = None
    else:
        raise RosteringError(f"Unknown action: {action}")

    helper["unresolved_friend_names"] = [n for n in helper["unresolved_friend_names"] if n != name]
    workspace.save(state)
    return state


def put_config(workspace: Workspace, buildings: list[dict], config_path: Optional[Path] = None) -> dict:
    try:
        config_from_list(buildings)
    except (KeyError, ValueError) as exc:
        raise RosteringError(f"Invalid config: {exc}") from exc
    state = workspace.load()
    state["config"] = buildings
    state["cell_merges"] = _prune_cell_merges(buildings, state.get("cell_merges", {}))
    workspace.save(state)
    if config_path is None:
        config_store.save_default_config(buildings)
    else:
        config_store.save_default_config(buildings, path=config_path)
    return state


def put_solver_config(workspace: Workspace, solver_config: dict) -> dict:
    try:
        parsed = solver_config_from_dict(solver_config)
    except (KeyError, ValueError) as exc:
        raise RosteringError(f"Invalid solver config: {exc}") from exc
    state = workspace.load()
    state["solver_config"] = solver_config_to_dict(parsed)
    workspace.save(state)
    return state


def solve(workspace: Workspace) -> dict:
    state = workspace.load()
    if not state["helpers"]:
        raise RosteringError("Upload a responses file first.")
    if not state["config"]:
        raise RosteringError("Configure at least one building first.")

    comp = _build_competition(state)
    solver_config = solver_config_from_dict(state["solver_config"])
    result = solve_competition(comp, solver_config)

    if result is None:
        state["assignments"] = []
        state["diagnostics"] = {
            "status": "INFEASIBLE",
            "objective_value": None,
            "unsatisfied_friend_pairs": [],
            "satisfied_friend_pairs": [],
        }
    else:
        state["assignments"] = [assignment_to_dict(a) for a in result.assignments]
        state["diagnostics"] = {
            "status": result.status,
            "objective_value": result.objective_value,
            "unsatisfied_friend_pairs": [list(p) for p in result.unsatisfied_friend_pairs],
            "satisfied_friend_pairs": [list(p) for p in result.satisfied_friend_pairs],
        }
    workspace.save(state)
    return state


def move_helper(workspace: Workspace, helper_id: int, building: str, room: str, role: str) -> dict:
    state = workspace.load()
    known_ids = {h["id"] for h in state["helpers"]}
    if helper_id not in known_ids:
        raise RosteringError(f"No such helper: {helper_id}")
    helper_name = next(h["name"] for h in state["helpers"] if h["id"] == helper_id)

    assignments = [a for a in state["assignments"] if a["helper_id"] != helper_id]
    assignments.append(
        {"helper_id": helper_id, "helper_name": helper_name, "building": building, "room": room, "role": role}
    )
    state["assignments"] = assignments
    satisfied, unsatisfied = _recompute_friend_pairs(state)
    state["diagnostics"]["satisfied_friend_pairs"] = satisfied
    state["diagnostics"]["unsatisfied_friend_pairs"] = unsatisfied
    workspace.save(state)
    return state


def put_manual_roles(workspace: Workspace, manual_roles: dict) -> dict:
    try:
        manual_roles_from_dict(manual_roles)
    except (KeyError, ValueError) as exc:
        raise RosteringError(f"Invalid manual roles: {exc}") from exc
    state = workspace.load()
    state["manual_roles"] = manual_roles
    workspace.save(state)
    return state


def set_cell_merges(workspace: Workspace, row_key: str, building: str, pairs: list[list[str]], merged: bool) -> dict:
    """Merge or unmerge one or more adjacent-room-name pairs within
    ``building``, scoped to one grid row (``row_key`` — a solved role's name
    or a room-scoped manual role's name; other rows for the same rooms are
    unaffected, like merging cells within a single spreadsheet row; see
    ``rostering.domain.group_adjacent_rooms``). The grid sends a single pair
    when merging (clicking the edge between two cells) and every internal
    pair of a group when unmerging (clicking a merged cell to split it back
    into individual rooms)."""
    state = workspace.load()
    cell_merges = {k: {b: [list(p) for p in v] for b, v in bd.items()} for k, bd in state.get("cell_merges", {}).items()}
    by_building = cell_merges.setdefault(row_key, {})
    current = {tuple(p) for p in by_building.get(building, [])}
    for pair in pairs:
        key = (pair[0], pair[1])
        if merged:
            current.add(key)
        else:
            current.discard(key)
    if current:
        by_building[building] = [list(p) for p in sorted(current)]
    else:
        by_building.pop(building, None)
    if not by_building:
        cell_merges.pop(row_key, None)
    state["cell_merges"] = cell_merges
    workspace.save(state)
    return state


def list_versions(workspace: Workspace) -> list[dict]:
    return workspace.list_versions()


def save_version(workspace: Workspace, name: str) -> dict:
    return workspace.save_version(name)


def restore_version(workspace: Workspace, slug: str) -> dict:
    data = workspace.restore_version(slug)
    if data is None:
        raise RosteringError("No such version")
    return data


def delete_version(workspace: Workspace, slug: str) -> None:
    if not workspace.delete_version(slug):
        raise RosteringError("No such version")


def export_xlsx_bytes(workspace: Workspace) -> bytes:
    state = workspace.load()
    if not state["assignments"]:
        raise RosteringError("Nothing to export yet — solve first.")

    comp = _build_competition(state)
    result = SolveResult(
        assignments=[assignment_from_dict(a) for a in state["assignments"]],
        status=state["diagnostics"].get("status") or "MANUAL",
        objective_value=state["diagnostics"].get("objective_value") or 0.0,
        unsatisfied_friend_pairs=[tuple(p) for p in state["diagnostics"].get("unsatisfied_friend_pairs", [])],
        satisfied_friend_pairs=[tuple(p) for p in state["diagnostics"].get("satisfied_friend_pairs", [])],
    )
    manual: ManualRoles = manual_roles_from_dict(state["manual_roles"])

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        write_roster(comp, result, manual, tmp_path, cell_merges=state.get("cell_merges", {}))
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)
