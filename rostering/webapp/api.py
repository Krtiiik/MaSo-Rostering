"""FastAPI backend for the interactive roster web app.

Single-workspace design (see workspace.py): upload a raw survey export,
edit the buildings/rooms config, solve, then drag helpers around the grid
and layer on manual structural/overlay roles. Named versions are snapshots
of the whole workspace state.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rostering.domain import Competition, ManualRoles
from rostering.export.excel import write_roster
from rostering.ingest.raw_survey import parse_raw_survey
from rostering.solver.model import solve_competition
from rostering.solver.scoring import build_friend_pairs
from rostering.webapp.serialize import (
    assignment_to_dict,
    config_from_list,
    helper_from_dict,
    helper_to_dict,
    manual_roles_from_dict,
    manual_roles_to_dict,
    solver_config_from_dict,
    solver_config_to_dict,
)
from rostering.webapp.workspace import Workspace

app = FastAPI(title="Rostering")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

workspace = Workspace()


class AssignmentUpdate(BaseModel):
    building: str
    room: str
    role: str


class VersionCreate(BaseModel):
    name: str


def _recompute_unsatisfied_pairs(state: dict[str, Any]) -> list[list[int]]:
    helpers = [helper_from_dict(h) for h in state["helpers"]]
    friend_scoring = solver_config_from_dict(state["solver_config"]).friend_scoring
    pairs = build_friend_pairs(helpers, friend_scoring)
    room_by_helper = {a["helper_id"]: (a["building"], a["room"]) for a in state["assignments"]}
    unsatisfied = []
    for a_id, b_id, _weight in pairs:
        if room_by_helper.get(a_id) is None or room_by_helper.get(a_id) != room_by_helper.get(b_id):
            unsatisfied.append([a_id, b_id])
    return unsatisfied


def _build_competition(state: dict[str, Any]) -> Competition:
    buildings = config_from_list(state["config"])
    helpers = [helper_from_dict(h) for h in state["helpers"]]
    return Competition(buildings=buildings, helpers=helpers)


@app.get("/api/state")
def get_state() -> dict:
    return workspace.load()


@app.post("/api/reset")
def reset_workspace() -> dict:
    return workspace.reset()


@app.post("/api/upload")
async def upload_responses(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        result = parse_raw_survey(tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    state = workspace.load()
    state["helpers"] = [helper_to_dict(h) for h in result.helpers]
    state["ingestion_warnings"] = result.warnings
    state["assignments"] = []
    state["diagnostics"] = {"status": None, "objective_value": None, "unsatisfied_friend_pairs": []}
    workspace.save(state)
    return state


@app.put("/api/config")
def put_config(buildings: list[dict]) -> dict:
    # Round-trip through the domain model to validate shape/values early.
    try:
        config_from_list(buildings)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid config: {exc}") from exc
    state = workspace.load()
    state["config"] = buildings
    workspace.save(state)
    return state


@app.put("/api/solver-config")
def put_solver_config(solver_config: dict) -> dict:
    try:
        parsed = solver_config_from_dict(solver_config)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid solver config: {exc}") from exc
    state = workspace.load()
    state["solver_config"] = solver_config_to_dict(parsed)
    workspace.save(state)
    return state


@app.post("/api/solve")
def solve() -> dict:
    state = workspace.load()
    if not state["helpers"]:
        raise HTTPException(status_code=400, detail="Upload a responses file first.")
    if not state["config"]:
        raise HTTPException(status_code=400, detail="Configure at least one building first.")

    comp = _build_competition(state)
    solver_config = solver_config_from_dict(state["solver_config"])
    result = solve_competition(comp, solver_config)

    if result is None:
        state["assignments"] = []
        state["diagnostics"] = {"status": "INFEASIBLE", "objective_value": None, "unsatisfied_friend_pairs": []}
    else:
        state["assignments"] = [assignment_to_dict(a) for a in result.assignments]
        state["diagnostics"] = {
            "status": result.status,
            "objective_value": result.objective_value,
            "unsatisfied_friend_pairs": [list(p) for p in result.unsatisfied_friend_pairs],
        }
    workspace.save(state)
    return state


@app.put("/api/assignments/{helper_id}")
def move_helper(helper_id: int, body: AssignmentUpdate) -> dict:
    state = workspace.load()
    known_ids = {h["id"] for h in state["helpers"]}
    if helper_id not in known_ids:
        raise HTTPException(status_code=404, detail=f"No such helper: {helper_id}")
    helper_name = next(h["name"] for h in state["helpers"] if h["id"] == helper_id)

    assignments = [a for a in state["assignments"] if a["helper_id"] != helper_id]
    assignments.append(
        {"helper_id": helper_id, "helper_name": helper_name, "building": body.building, "room": body.room, "role": body.role}
    )
    state["assignments"] = assignments
    state["diagnostics"]["unsatisfied_friend_pairs"] = _recompute_unsatisfied_pairs(state)
    workspace.save(state)
    return state


@app.put("/api/manual-roles")
def put_manual_roles(manual_roles: dict) -> dict:
    try:
        manual_roles_from_dict(manual_roles)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid manual roles: {exc}") from exc
    state = workspace.load()
    state["manual_roles"] = manual_roles
    workspace.save(state)
    return state


@app.get("/api/versions")
def list_versions() -> list[dict]:
    return workspace.list_versions()


@app.post("/api/versions")
def create_version(body: VersionCreate) -> dict:
    return workspace.save_version(body.name)


@app.get("/api/versions/{slug}")
def get_version(slug: str) -> dict:
    data = workspace.load_version(slug)
    if data is None:
        raise HTTPException(status_code=404, detail="No such version")
    return data


@app.post("/api/versions/{slug}/restore")
def restore_version(slug: str) -> dict:
    data = workspace.restore_version(slug)
    if data is None:
        raise HTTPException(status_code=404, detail="No such version")
    return data


@app.delete("/api/versions/{slug}")
def delete_version(slug: str) -> dict:
    if not workspace.delete_version(slug):
        raise HTTPException(status_code=404, detail="No such version")
    return {"deleted": slug}


@app.get("/api/export.xlsx")
def export_xlsx() -> FileResponse:
    state = workspace.load()
    if not state["assignments"]:
        raise HTTPException(status_code=400, detail="Nothing to export yet — solve first.")

    comp = _build_competition(state)
    from rostering.webapp.serialize import assignment_from_dict
    from rostering.domain import SolveResult

    result = SolveResult(
        assignments=[assignment_from_dict(a) for a in state["assignments"]],
        status=state["diagnostics"].get("status") or "MANUAL",
        objective_value=state["diagnostics"].get("objective_value") or 0.0,
        unsatisfied_friend_pairs=[tuple(p) for p in state["diagnostics"].get("unsatisfied_friend_pairs", [])],
    )
    manual = manual_roles_from_dict(state["manual_roles"])

    tmp_path = Path(tempfile.gettempdir()) / "rostering-export.xlsx"
    write_roster(comp, result, manual, tmp_path)
    return FileResponse(
        tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="roster.xlsx",
    )


_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
