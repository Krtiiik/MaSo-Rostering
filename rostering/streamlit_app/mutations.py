"""State-mutation functions for the Streamlit app.

Each function mirrors one route of the old FastAPI backend
(``rostering/webapp/api.py``, since deleted): it takes the workspace plus
whatever the UI just did, mutates the JSON-shaped workspace state, persists
it, and returns the new state dict. Kept free of any Streamlit import so it
can be unit-tested directly and reused unchanged by any future caller.
"""
from __future__ import annotations

import functools
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from rostering.domain import (
    TSHIRT_SIZES,
    UNKNOWN_TSHIRT_SIZE,
    Competition,
    ManualRoles,
    SolveResult,
    parse_tshirt_size,
)
from rostering.export.excel import write_roster
from rostering.ingest.raw_survey import parse_raw_survey, read_submission_timestamps
from rostering.persistence import config_store
from rostering.persistence.season_label import guess_label
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
from rostering.persistence.workspace import SeasonError, Workspace
from rostering.solver.model import solve_competition
from rostering.solver.scoring import build_friend_pairs


class RosteringError(Exception):
    """Raised for any user-facing error a mutation function hits (bad input,
    unknown id, infeasible precondition, ...). Tabs catch this and show
    ``st.error(str(exc))``."""


class SeasonLabelRequired(RosteringError):
    """No Season label could be settled automatically, so the user must
    supply one. ``suggested_label`` is a best-effort prefill (or None when
    there is nothing to go on)."""

    def __init__(self, message: str, suggested_label: Optional[str] = None):
        super().__init__(message)
        self.suggested_label = suggested_label


_F = TypeVar("_F", bound=Callable[..., Any])


def _season_errors(func: _F) -> _F:
    """Surface the workspace's Season errors as :class:`RosteringError` so
    tabs only ever have to catch one exception type."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SeasonError as exc:
            raise RosteringError(str(exc)) from exc

    return wrapper  # type: ignore[return-value]


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
    """"Start over": empty the open Season's state, keeping its label, Season
    id and Versions."""
    return workspace.reset()


# -- Seasons -----------------------------------------------------------------


def list_seasons(workspace: Workspace) -> list[dict]:
    """Every stored Season, most recent first: ``id``, ``label``,
    ``helper_count`` and ``open``."""
    return workspace.list_seasons()


def get_open_season(workspace: Workspace) -> Optional[dict]:
    """``{"id", "label"}`` of the open Season, or None if none is open."""
    return workspace.open_season()


@_season_errors
def open_season(workspace: Workspace, season_id: str) -> dict:
    """Open a stored Season into the Workspace (replacing its contents; there
    is no read-only mode) and return its state."""
    return workspace.switch_to(season_id)


def new_season(workspace: Workspace) -> dict:
    """"New Season": leave no Season open, so the Workspace is blank and the
    next upload creates a Season. Nothing needs archiving first — every stored
    Season stays stored. Returns the blank state."""
    return workspace.close()


@_season_errors
def rename_season(workspace: Workspace, season_id: str, label: str) -> dict:
    """Relabel a Season (open or stored) and rename its directory; the Season
    id never changes. Returns its ``{"id", "label"}``."""
    return workspace.rename_season(season_id, label)


@_season_errors
def delete_season(workspace: Workspace, season_id: str) -> None:
    """Delete a stored Season together with its Versions. Refused for the open
    Season."""
    workspace.delete_season(season_id)


def migrate_legacy_workspace(workspace: Workspace, label: Optional[str] = None) -> Optional[dict]:
    """First-launch migration of the pre-Seasons single saved state (and its
    Versions) into a labelled Season, which is then opened.

    Returns the new Season's ``{"id", "label"}``, or None when there is nothing
    to migrate. The label comes from ``label`` if given, else from the
    submission timestamps stored with the old state; when neither yields a
    usable label :class:`SeasonLabelRequired` is raised (nothing is moved) with
    the old state file's last-modified date as the suggestion, and the caller
    asks once and calls again with the answer."""
    legacy = workspace.legacy_state()
    if legacy is None:
        return None
    derived = guess_label([datetime.fromisoformat(t) for t in legacy.get("export_timestamps", [])])
    candidate = (label or "").strip() or derived
    if not candidate:
        modified = datetime.fromtimestamp(workspace.legacy_state_path().stat().st_mtime)
        raise SeasonLabelRequired(
            "Your existing saved state needs a Season label (a year plus jaro or podzim, e.g. 2026-jaro).",
            suggested_label=guess_label([modified]),
        )
    try:
        return workspace.migrate_legacy(candidate)
    except SeasonError as exc:
        # The derived or typed label is unusable (duplicate, malformed): ask.
        raise SeasonLabelRequired(str(exc), suggested_label=candidate) from exc


def _write_temp(file_bytes: bytes, filename: str) -> Path:
    suffix = Path(filename or "upload.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
    return Path(tmp.name)


def suggest_season_label(file_bytes: bytes, filename: str) -> Optional[str]:
    """Best-guess Season label (e.g. ``2026-jaro``) for a survey export, from
    the median of its submission timestamps — January to June is jaro, July to
    December is podzim. ``None`` when the timestamps can't be read; the
    caller must then ask for the label. Only ever a prefill."""
    tmp_path = _write_temp(file_bytes, filename)
    try:
        return guess_label(read_submission_timestamps(tmp_path))
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@_season_errors
def upload_responses(workspace: Workspace, file_bytes: bytes, filename: str, label: Optional[str] = None) -> dict:
    """Load a raw survey export into the Workspace.

    With a Season open this is always a re-upload into that Season (``label``
    is ignored). With none open it creates a Season: ``label`` (required,
    unique among stored Seasons) names it, defaulting to the guess from the
    export's submission timestamps; if neither is available,
    :class:`SeasonLabelRequired` is raised and nothing is changed."""
    tmp_path = _write_temp(file_bytes, filename)
    try:
        result = parse_raw_survey(tmp_path)
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    creating = workspace.open_season() is None
    if creating:
        label = (label or "").strip() or guess_label(result.submission_timestamps)
        if not label:
            raise SeasonLabelRequired(
                "The submission dates in this export couldn't be read — enter the Season label "
                "(a year plus jaro or podzim, e.g. 2026-jaro)."
            )

    helper_dicts = [helper_to_dict(h) for h in result.helpers]
    for helper_dict in helper_dicts:
        # Fixed at upload time so the resolution UI can keep names in their
        # original order even after some of them are resolved and drop out
        # of unresolved_friend_names.
        helper_dict["friend_name_order"] = list(helper_dict["unresolved_friend_names"])

    state = workspace.load()
    state["helpers"] = helper_dicts
    state["ingestion_warnings"] = result.warnings
    state["export_timestamps"] = [t.date().isoformat() for t in result.submission_timestamps]
    state["assignments"] = []
    state["diagnostics"] = {
        "status": None,
        "objective_value": None,
        "unsatisfied_friend_pairs": [],
        "satisfied_friend_pairs": [],
    }
    if creating:
        workspace.create_season(label, state)
    else:
        workspace.save(state)
    return workspace.load()


def resolve_friend(
    workspace: Workspace,
    helper_id: int,
    name: str,
    action: str,
    resolved_helper_ids: Optional[list[int]] = None,
) -> dict:
    """Resolve (or dismiss) one unresolved friend name for a helper.

    A single free-text name can refer to more than one person (e.g. a
    group nickname), so ``resolved_helper_ids`` is a list — the name is
    matched to every helper id in it.
    """
    state = workspace.load()
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    if helper is None:
        raise RosteringError(f"No such helper: {helper_id}")
    decisions = helper.setdefault("friend_name_decisions", {})
    if name not in helper["unresolved_friend_names"] and name not in decisions:
        raise RosteringError(f"{name!r} is not a known friend name for helper {helper_id}")

    previous_raw = decisions.get(name)
    # Older persisted state stored a single int per name instead of a list.
    previous_ids = [previous_raw] if isinstance(previous_raw, int) else list(previous_raw or [])
    for previous_id in previous_ids:
        if previous_id in helper["friends"]:
            helper["friends"].remove(previous_id)

    if action == "resolve":
        if not resolved_helper_ids:
            raise RosteringError("resolved_helper_ids is required for action=resolve")
        known_ids = {h["id"] for h in state["helpers"]}
        unknown_ids = [hid for hid in resolved_helper_ids if hid not in known_ids]
        if unknown_ids:
            raise RosteringError(f"No such helper(s): {unknown_ids}")
        new_ids = list(dict.fromkeys(resolved_helper_ids))
        for hid in new_ids:
            if hid not in helper["friends"]:
                helper["friends"].append(hid)
        decisions[name] = new_ids
    elif action == "dismiss":
        decisions[name] = None
    else:
        raise RosteringError(f"Unknown action: {action}")

    helper["unresolved_friend_names"] = [n for n in helper["unresolved_friend_names"] if n != name]
    workspace.save(state)
    return state


def set_tshirt_size(workspace: Workspace, helper_id: int, size: str) -> dict:
    """Set one helper's T-shirt size by hand (chiefly to resolve an Unknown
    flagged by the upload warnings). ``size`` must be one of
    ``TSHIRT_SIZES`` or ``UNKNOWN_TSHIRT_SIZE``, matched ignoring case and
    surrounding whitespace like the survey answer; anything else is rejected
    and nothing is changed."""
    state = workspace.load()
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    if helper is None:
        raise RosteringError(f"No such helper: {helper_id}")
    if (size or "").strip().lower() == UNKNOWN_TSHIRT_SIZE.lower():
        parsed: Optional[str] = UNKNOWN_TSHIRT_SIZE
    else:
        parsed = parse_tshirt_size(size)
    if parsed is None:
        allowed = ", ".join([*TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE])
        raise RosteringError(f"Invalid T-shirt size {size!r}; expected one of: {allowed}")
    helper["tshirt_size"] = parsed
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
    """The open Season's Versions, newest first (none with no Season open)."""
    return workspace.list_versions()


@_season_errors
def save_version(workspace: Workspace, name: str) -> dict:
    """Snapshot the open Season's whole state, minus its identity."""
    return workspace.save_version(name)


@_season_errors
def restore_version(workspace: Workspace, slug: str) -> dict:
    """Roll the open Season back to a Version. Rolls back everything the
    Season holds (helpers, Person links and rejections, Tags, Forced-friend
    groups, Assignments, ...) except its label and Season id."""
    data = workspace.restore_version(slug)
    if data is None:
        raise RosteringError("No such version")
    return data


@_season_errors
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
