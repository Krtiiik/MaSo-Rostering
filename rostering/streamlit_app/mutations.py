"""State-mutation functions for the Streamlit app.

Each function mirrors one route of the old FastAPI backend
(``rostering/webapp/api.py``, since deleted): it takes the workspace plus
whatever the UI just did, mutates the JSON-shaped workspace state, persists
it, and returns the new state dict. Kept free of any Streamlit import so it
can be unit-tested directly and reused unchanged by any future caller.
"""
from __future__ import annotations

import functools
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

from rostering.domain import (
    TSHIRT_SIZES,
    UNKNOWN_TSHIRT_SIZE,
    Assignment,
    BrokenRule,
    Competition,
    Helper,
    ManualRoles,
    OverlayRole,
    Preference,
    Role,
    SolveResult,
    StructuralRole,
    normalize_email,
    normalize_name,
    parse_tshirt_size,
)
from rostering.export.excel import write_roster
from rostering.ingest.preferences import parse_role_token
from rostering.ingest.raw_survey import parse_raw_survey, read_submission_timestamps
from rostering.persistence import config_store
from rostering.persistence.season_label import guess_label, label_sort_key, school_years_crossed
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
from rostering.persons import build_persons, link_persons, new_person_id, uncertain_candidates
from rostering.solver.checker import check_roster, newly_broken, toasts
from rostering.solver.model import NoRosterFound, solve_competition
from rostering.solver.scoring import build_friend_pairs
from rostering import tags as tag_tree


class RosteringError(Exception):
    """Raised for any user-facing error a mutation function hits (bad input,
    unknown id, infeasible precondition, ...). Tabs catch this and show
    ``st.error(str(exc))``."""


class ConfirmationRequired(RosteringError):
    """The edit would throw away hand work, so nothing was changed: ``lines``
    name what would be cleared, and the caller asks the user and calls again
    with ``confirmed=True`` (or drops the request to cancel)."""

    def __init__(self, message: str, lines: list[str]):
        super().__init__(message)
        self.lines = lines


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
    """The Competition of the Helpers who are coming: those flagged Can't attend
    are left out, so the solver, the Broken-rule check and the export never see
    them."""
    buildings = config_from_list(state["config"])
    helpers = [helper_from_dict(h) for h in state["helpers"] if not h.get("cant_attend")]
    return Competition(buildings=buildings, helpers=helpers, tags=_tag_definitions(state))


def _recompute_friend_pairs(state: dict[str, Any]) -> tuple[list[list[int]], list[list[int]]]:
    """Return (satisfied, unsatisfied) friend pairs given the current assignments."""
    helpers = [helper_from_dict(h) for h in state["helpers"] if not h.get("cant_attend")]
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

    # Recognize Returning helpers: an identical normalized e-mail links a row
    # to the Person recorded in any stored Season (this Season's previous
    # upload included), whatever the name; anything else is a new Person.
    person_ids = link_persons([h.email for h in result.helpers], workspace.person_records())
    helper_dicts = [
        helper_to_dict(replace(h, person_id=person_id)) for h, person_id in zip(result.helpers, person_ids)
    ]
    for helper_dict in helper_dicts:
        # Fixed at upload time so the resolution UI can keep names in their
        # original order even after some of them are resolved and drop out
        # of unresolved_friend_names.
        helper_dict["friend_name_order"] = list(helper_dict["unresolved_friend_names"])

    state = workspace.load()
    _carry_over_link_decisions(state["helpers"], helper_dicts)
    _carry_over_cant_attend(state["helpers"], helper_dicts)
    _carry_over_tags(state["helpers"], helper_dicts)
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


def _carry_over_link_decisions(old_helpers: list[dict], new_helpers: list[dict]) -> None:
    """A re-upload replaces the Season's Helper records, so what the user
    decided about a Person — rejected pairings and a confirmed link — moves
    onto the new record that is the same Person (the same ``person_id``, which
    an identical e-mail keeps)."""
    rejected: dict[str, list[str]] = {}
    confirmed: set[str] = set()
    for old in old_helpers:
        person_id = old.get("person_id")
        if not person_id:
            continue
        rejected.setdefault(person_id, []).extend(old.get("rejected_person_ids") or [])
        if old.get("link_confirmed"):
            confirmed.add(person_id)
    for new in new_helpers:
        kept = list(dict.fromkeys(rejected.get(new["person_id"], [])))
        if kept:
            new["rejected_person_ids"] = kept
        if new["person_id"] in confirmed:
            new["link_confirmed"] = True


def _carry_over_cant_attend(old_helpers: list[dict], new_helpers: list[dict]) -> None:
    """Can't attend is set by hand, never by survey data, so a re-upload keeps
    it on the new record that is the same Person as a flagged one."""
    flagged = {h["person_id"] for h in old_helpers if h.get("cant_attend") and h.get("person_id")}
    for new in new_helpers:
        if new["person_id"] in flagged:
            new["cant_attend"] = True


def _carry_over_tags(old_helpers: list[dict], new_helpers: list[dict]) -> None:
    """The Season's Tags stay through a re-upload (only the Helper records are
    replaced), so the Tags a Helper was given by hand move onto the new record
    that is the same Person."""
    tags_by_person = {h["person_id"]: h["tags"] for h in old_helpers if h.get("tags") and h.get("person_id")}
    for new in new_helpers:
        if new["person_id"] in tags_by_person:
            new["tags"] = list(tags_by_person[new["person_id"]])


# -- Persons ------------------------------------------------------------------


def list_persons(workspace: Workspace) -> list[dict]:
    """Every Person the stored Seasons know, derived from their Helper records
    (there is no separate registry): ``person_id``, ``name`` (as spelled in the
    most recent appearance), ``emails`` and ``names`` (every normalized e-mail
    and name seen for them across all stored Seasons, sorted) and ``seasons``
    (labels of the Seasons that record them, most recent first)."""
    return [asdict(person) for person in build_persons(workspace.person_records())]


def get_returning_helpers(workspace: Workspace) -> dict[int, list[str]]:
    """The open Season's Returning helpers: Helper id -> labels of the earlier
    stored Seasons (most recent first) that record the same Person. A Helper
    with no earlier appearance is absent."""
    season = workspace.open_season()
    if season is None:
        return {}
    records = workspace.person_records()
    earlier_by_person: dict[str, set[str]] = {}
    for record in records:
        if label_sort_key(record.season_label) < label_sort_key(season["label"]):
            earlier_by_person.setdefault(record.person_id, set()).add(record.season_label)
    returning: dict[int, list[str]] = {}
    for helper in workspace.load()["helpers"]:
        earlier = earlier_by_person.get(helper.get("person_id") or "")
        if earlier:
            returning[helper["id"]] = sorted(earlier, key=label_sort_key, reverse=True)
    return returning


def get_uncertain_matches(workspace: Workspace) -> list[dict]:
    """The review list of the open Season: its uncertain matches, one entry
    per Helper that has any (by Helper id), each with the Persons proposed for
    them — an identical normalized name and no e-mail match, so nothing here is
    linked until :func:`link_helper` confirms it, and an unreviewed candidate
    counts as not linked.

    An entry is ``helper_id``, ``helper_name``, ``helper_email``,
    ``helper_phone`` and ``candidates``: each ``person_id`` plus the details of
    the Person's most recent same-name record (``name``, ``season`` label,
    ``email``, ``phone`` — the phone only a hint), most recent first. Empty
    with no Season open."""
    season = workspace.open_season()
    if season is None:
        return []
    proposals = uncertain_candidates(workspace.person_records(), season["id"])
    entries = []
    for helper in workspace.load()["helpers"]:
        candidates = proposals.get(helper["id"])
        if not candidates:
            continue
        entries.append(
            {
                "helper_id": helper["id"],
                "helper_name": helper["name"],
                "helper_email": helper.get("email"),
                "helper_phone": helper.get("phone"),
                "candidates": [
                    {
                        "person_id": c.person_id,
                        "name": c.record.name,
                        "season": c.record.season_label,
                        "email": c.record.email,
                        "phone": c.record.phone,
                    }
                    for c in candidates
                ],
            }
        )
    return sorted(entries, key=lambda e: e["helper_id"])


def get_person_links(workspace: Workspace) -> dict[int, dict]:
    """The open Season's linked Helpers: Helper id -> ``person_id`` and
    ``records`` (``season``, ``name``, ``email``, ``phone`` of every *other*
    record of that Person, most recent first — another Helper of this Season
    included). A Helper linked to no other record is absent."""
    season = workspace.open_season()
    if season is None:
        return {}
    by_person: dict[str, list] = {}
    for record in workspace.person_records():
        by_person.setdefault(record.person_id, []).append(record)
    links: dict[int, dict] = {}
    for helper in workspace.load()["helpers"]:
        others = [
            r
            for r in by_person.get(helper.get("person_id") or "", [])
            if (r.season_id, r.helper_id) != (season["id"], helper["id"])
        ]
        if others:
            links[helper["id"]] = {
                "person_id": helper["person_id"],
                "records": [
                    {"season": r.season_label, "name": r.name, "email": r.email, "phone": r.phone}
                    for r in sorted(others, key=lambda r: r.recency, reverse=True)
                ],
            }
    return links


def _helper_record(state: dict[str, Any], helper_id: int) -> dict:
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    if helper is None:
        raise RosteringError(f"No such helper: {helper_id}")
    return helper


def _known_person(workspace: Workspace, person_id: str) -> None:
    if person_id not in {r.person_id for r in workspace.person_records()}:
        raise RosteringError("No such Person.")


def link_helper(workspace: Workspace, helper_id: int, person_id: str) -> dict:
    """Link a Helper of the open Season to a Person the stored Seasons know:
    confirms a proposed candidate, or links by hand to any Person (a returner
    who changed both e-mail and name form). Changes only this Helper's Person
    link — never a Helper id — and settles the Helper, so their other
    candidates are no longer proposed. Remembered on the Helper record
    independently of e-mail."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    _known_person(workspace, person_id)
    if helper.get("person_id") == person_id:
        raise RosteringError(f"{helper['name']} is already linked to that Person.")
    helper["person_id"] = person_id
    helper["link_confirmed"] = True
    remaining = [p for p in helper.get("rejected_person_ids", []) if p != person_id]
    if remaining:
        helper["rejected_person_ids"] = remaining
    else:
        helper.pop("rejected_person_ids", None)
    workspace.save(state)
    return state


def reject_person_match(workspace: Workspace, helper_id: int, person_id: str) -> dict:
    """"Not the same person": remember that this Helper is not that Person, so
    the pairing is never proposed again (from either Season's side). Leaves the
    Helper's other candidates, and their Person link, untouched."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    _known_person(workspace, person_id)
    if helper.get("person_id") == person_id:
        raise RosteringError(f"{helper['name']} is linked to that Person — unlink them instead.")
    rejected = helper.setdefault("rejected_person_ids", [])
    if person_id not in rejected:
        rejected.append(person_id)
    workspace.save(state)
    return state


def unlink_helper(workspace: Workspace, helper_id: int) -> dict:
    """Undo a Helper's Person link, automatic or confirmed: they become a Person
    of their own again (a fresh id; the Helper id and every other record are
    untouched). The Person they were unlinked from is remembered as rejected,
    so they are not proposed straight back to it."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    season = workspace.open_season()
    old_person = helper.get("person_id")
    shared = any(
        r.person_id == old_person and (r.season_id, r.helper_id) != (season["id"], helper_id)
        for r in workspace.person_records()
    )
    if not shared and not helper.get("link_confirmed"):
        raise RosteringError(f"{helper['name']} is not linked to any other record.")
    helper["person_id"] = new_person_id()
    helper.pop("link_confirmed", None)
    rejected = helper.setdefault("rejected_person_ids", [])
    if old_person and old_person not in rejected:
        rejected.append(old_person)
    workspace.save(state)
    return state


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


# -- Can't attend and the stale roster ------------------------------------------


def stale_reasons(state: dict[str, Any]) -> list[str]:
    """Why the roster is stale, one line per edit that raised it (empty when it
    isn't). A stale roster no longer matches the Helpers and rules it was
    solved for without anyone having been moved; Export is refused until the
    next full Solve."""
    return list(state.get("stale_reasons") or [])


def _add_stale_reason(state: dict[str, Any], reason: str) -> None:
    reasons = stale_reasons(state)
    if reason not in reasons:
        reasons.append(reason)
    state["stale_reasons"] = reasons


def mark_stale(workspace: Workspace, reason: str) -> dict:
    """Raise the stale-roster flag with ``reason`` (shown as the banner near the
    Solve button). The reusable mechanism for any edit that changes the roster's
    validity without moving anyone; only a full Solve clears it."""
    state = workspace.load()
    _add_stale_reason(state, reason)
    workspace.save(state)
    return state


def _manual_entry_label(entry: dict) -> str:
    role = next((r.value for r in (*StructuralRole, *OverlayRole) if r.name == entry["role"]), entry["role"])
    where = " · ".join(filter(None, [entry.get("building"), entry.get("room")]))
    return f"{role} ({where})" if where else role


def cant_attend_impact(state: dict[str, Any], helper_id: int) -> list[str]:
    """What marking this Helper Can't attend would clear, one line each: their
    Assignment (and its lock) and every Manual role entry holding them. Empty
    when there is nothing to clear, in which case no confirmation is needed."""
    lines = []
    placed = next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)
    if placed is not None:
        where = f"{placed['building']} · {placed['room']} · {Role[placed['role']].value}"
        lines.append(f"Assignment: {where}" + (" (locked)" if placed.get("locked") else ""))
    for group in ("structural", "overlay"):
        for entry in state["manual_roles"][group]:
            if entry.get("helper_id") == helper_id:
                lines.append(f"Manual role: {_manual_entry_label(entry)}")
    return lines


def set_cant_attend(workspace: Workspace, helper_id: int, cant_attend: bool, confirmed: bool = False) -> dict:
    """Flag a Helper Can't attend, or clear the flag.

    A Helper with an Assignment or Manual role entries is only flagged once
    ``confirmed``; without it :class:`ConfirmationRequired` names what would be
    cleared and nothing changes. Confirming removes their Assignment (and its
    lock) and every Manual role entry holding them, and raises the stale-roster
    flag. A Helper with nothing to clear is flagged at once and the roster
    stays as it is. Clearing the flag only clears the flag: it restores nothing,
    stales nothing and does not solve."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    if bool(helper.get("cant_attend")) == cant_attend:
        return state
    if not cant_attend:
        helper.pop("cant_attend", None)
        workspace.save(state)
        return state

    impact = cant_attend_impact(state, helper_id)
    if impact and not confirmed:
        raise ConfirmationRequired(
            f"Marking {helper['name']} as Can't attend clears " + "; ".join(impact) + ". "
            "Un-flagging them later does not restore these, and the roster is out of date until the next Solve.",
            impact,
        )
    helper["cant_attend"] = True
    if impact:
        state["assignments"] = [a for a in state["assignments"] if a["helper_id"] != helper_id]
        satisfied, unsatisfied = _recompute_friend_pairs(state)
        state["diagnostics"]["satisfied_friend_pairs"] = satisfied
        state["diagnostics"]["unsatisfied_friend_pairs"] = unsatisfied
        state["manual_roles"] = {
            group: [e for e in entries if e.get("helper_id") != helper_id]
            for group, entries in state["manual_roles"].items()
        }
        _add_stale_reason(state, f"{helper['name']} can't attend: their Assignment and role entries were cleared")
    workspace.save(state)
    return state


def _parse_tshirt_size(size: str) -> str:
    """The canonical size ``size`` names (one of ``TSHIRT_SIZES`` or
    ``UNKNOWN_TSHIRT_SIZE``, ignoring case and surrounding whitespace like the
    survey answer); anything else raises :class:`RosteringError`."""
    if (size or "").strip().lower() == UNKNOWN_TSHIRT_SIZE.lower():
        return UNKNOWN_TSHIRT_SIZE
    parsed = parse_tshirt_size(size)
    if parsed is None:
        allowed = ", ".join([*TSHIRT_SIZES, UNKNOWN_TSHIRT_SIZE])
        raise RosteringError(f"Invalid T-shirt size {size!r}; expected one of: {allowed}")
    return parsed


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
    parsed = _parse_tshirt_size(size)
    if helper.get("tshirt_size") != parsed and helper.get("hand_added"):
        _mark_hand_typed(helper, ["tshirt_size"])
    helper["tshirt_size"] = parsed
    workspace.save(state)
    return state


# -- Adding, editing and deleting a Helper by hand ----------------------------------

# What a hand-added Helper starts with for every optional field: exactly a blank
# survey row (no Preferences, so each Role reads as Nevadí; no Building
# preference; no equipment; no friends; T-shirt size Unknown).
_BLANK_ANSWERS: dict[str, Any] = {
    "role_preferences": {},
    "building_preferences": [],
    "can_bring_notebook": False,
    "can_bring_camera": False,
    "friends": [],
    "tshirt_size": UNKNOWN_TSHIRT_SIZE,
}
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_like_email(contact: str) -> bool:
    return _EMAIL_SHAPE.match(contact.strip()) is not None


def _mark_hand_typed(helper: dict, fields: list[str]) -> None:
    """Remember on the record that these fields were typed by hand, so a later
    survey row fills only what was left at its default (see CONTEXT.md
    "Hand-added Helper")."""
    typed = list(helper.get("hand_typed") or [])
    typed.extend(f for f in fields if f not in typed)
    if typed:
        helper["hand_typed"] = typed


def helper_collisions(
    state: dict[str, Any], name: str, contact: Optional[str] = None, exclude_helper_id: Optional[int] = None
) -> list[str]:
    """Warning lines for a name or e-mail that another Helper of the Season
    already has (names compared ignoring case, diacritics and spacing; an
    e-mail only when ``contact`` is e-mail-shaped). Only a warning: the caller
    may go ahead. ``exclude_helper_id`` skips the Helper being edited."""
    name_key = normalize_name(name)
    email = normalize_email(contact) if contact and _looks_like_email(contact) else None
    lines = []
    for other in state["helpers"]:
        if other["id"] == exclude_helper_id:
            continue
        if name_key and normalize_name(other["name"]) == name_key:
            lines.append(f"{other['name']} is already a Helper with this name.")
        elif email and normalize_email(other.get("email")) == email:
            lines.append(f"{other['name']} already has the e-mail {email}.")
    return lines


def _validated_helper_fields(
    state: dict[str, Any],
    helper_id: Optional[int],
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    role_preferences: Optional[dict[str, str]] = None,
    building_preferences: Optional[list[str]] = None,
    can_bring_notebook: Optional[bool] = None,
    can_bring_camera: Optional[bool] = None,
    friends: Optional[list[int]] = None,
    tshirt_size: Optional[str] = None,
) -> dict[str, Any]:
    """The fields that were given (``None`` = not given), validated and in
    stored form; raises :class:`RosteringError` for any invalid one."""
    fields: dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise RosteringError("A Helper needs a name.")
        fields["name"] = name.strip()
    if email is not None:
        fields["email"] = normalize_email(email)
    if phone is not None:
        fields["phone"] = phone.strip() or None
    if role_preferences is not None:
        cleaned = {}
        for role_name, pref_name in role_preferences.items():
            role = parse_role_token(role_name)
            if role is None:
                raise RosteringError(f"Unknown role: {role_name!r}")
            if pref_name not in Preference.__members__:
                allowed = ", ".join(Preference.__members__)
                raise RosteringError(f"Unknown preference {pref_name!r}; expected one of: {allowed}")
            cleaned[role.name] = pref_name
        fields["role_preferences"] = cleaned
    if building_preferences is not None:
        known = [b["name"] for b in state["config"]]
        unknown = [b for b in building_preferences if b not in known]
        if unknown:
            raise RosteringError(f"Unknown building(s): {', '.join(unknown)}")
        fields["building_preferences"] = sorted(set(building_preferences))
    if can_bring_notebook is not None:
        fields["can_bring_notebook"] = bool(can_bring_notebook)
    if can_bring_camera is not None:
        fields["can_bring_camera"] = bool(can_bring_camera)
    if friends is not None:
        known_ids = {h["id"] for h in state["helpers"]}
        unknown_ids = [f for f in friends if f not in known_ids]
        if unknown_ids:
            raise RosteringError(f"No such helper(s): {unknown_ids}")
        if helper_id is not None and helper_id in friends:
            raise RosteringError("A Helper can't be their own friend.")
        fields["friends"] = list(dict.fromkeys(friends))
    if tshirt_size is not None:
        fields["tshirt_size"] = _parse_tshirt_size(tshirt_size)
    return fields


def _next_helper_id(state: dict[str, Any]) -> int:
    """A Helper id above every id in use and above every id ever handed out or
    deleted (``next_helper_id`` is that high-water mark), so an id is never
    reused for another person."""
    new_id = max(int(state.get("next_helper_id") or 1), max((h["id"] for h in state["helpers"]), default=0) + 1)
    state["next_helper_id"] = new_id + 1
    return new_id


def _person_id_for_new_email(workspace: Workspace, email: Optional[str]) -> str:
    """The Person link for a Helper added by hand: a confident match by e-mail
    to a Person an earlier stored Season recorded, otherwise a fresh Person. The
    open Season's own records never match, so a duplicate e-mail typed here
    doesn't fuse two Helpers of one Season into one Person."""
    open_season = workspace.open_season()
    known = [r for r in workspace.person_records() if open_season is None or r.season_id != open_season["id"]]
    return link_persons([email], known)[0]


def add_helper(
    workspace: Workspace,
    name: str,
    contact: str,
    *,
    role_preferences: Optional[dict[str, str]] = None,
    building_preferences: Optional[list[str]] = None,
    can_bring_notebook: Optional[bool] = None,
    can_bring_camera: Optional[bool] = None,
    friends: Optional[list[int]] = None,
    tshirt_size: Optional[str] = None,
) -> dict:
    """Add a Helper by hand (see CONTEXT.md "Hand-added Helper"): only ``name``
    and ``contact`` are required, and every optional field left out takes the
    blank-survey default. An e-mail-shaped ``contact`` is stored as the Helper's
    e-mail (so it takes part in Person matching); any other contact is kept as
    the display contact (``phone``) and matching falls back to the name. The
    record gets a fresh, never-reused Helper id, a Person link (fresh unless the
    e-mail was recorded in an earlier Season) and remembers which fields were
    typed by hand; it is appended to ``state["helpers"]``, which is how the
    caller finds it. A name or e-mail another Helper already has is not
    refused here: :func:`helper_collisions` is the warning."""
    name = (name or "").strip()
    contact = (contact or "").strip()
    if not name:
        raise RosteringError("A Helper needs a name.")
    if not contact:
        raise RosteringError("A Helper needs a contact (an e-mail or a phone number).")
    state = workspace.load()
    is_email = _looks_like_email(contact)
    fields = _validated_helper_fields(
        state,
        None,
        name=name,
        email=contact if is_email else None,
        phone=None if is_email else contact,
        role_preferences=role_preferences,
        building_preferences=building_preferences,
        can_bring_notebook=can_bring_notebook,
        can_bring_camera=can_bring_camera,
        friends=friends,
        tshirt_size=tshirt_size,
    )
    person_id = _person_id_for_new_email(workspace, fields.get("email"))
    record = helper_to_dict(Helper(id=_next_helper_id(state), name=name, person_id=person_id))
    record.update(fields)
    record["hand_added"] = True
    _mark_hand_typed(
        record, [f for f, value in fields.items() if f in ("name", "email", "phone") or value != _BLANK_ANSWERS[f]]
    )
    state["helpers"].append(record)
    workspace.save(state)
    return state


def update_helper(
    workspace: Workspace,
    helper_id: int,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    role_preferences: Optional[dict[str, str]] = None,
    building_preferences: Optional[list[str]] = None,
    can_bring_notebook: Optional[bool] = None,
    can_bring_camera: Optional[bool] = None,
    friends: Optional[list[int]] = None,
    tshirt_size: Optional[str] = None,
) -> dict:
    """Edit any field of a Helper by hand, at any time (before or after a solve;
    an edit never moves anyone). Fields left out stay as they are; a blank
    ``email`` or ``phone`` clears it. The Helper id and Person link are
    untouched, and the fields that changed are remembered as typed by hand."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    fields = _validated_helper_fields(
        state,
        helper_id,
        name=name,
        email=email,
        phone=phone,
        role_preferences=role_preferences,
        building_preferences=building_preferences,
        can_bring_notebook=can_bring_notebook,
        can_bring_camera=can_bring_camera,
        friends=friends,
        tshirt_size=tshirt_size,
    )
    changed = [f for f, value in fields.items() if helper.get(f) != value]
    helper.update({f: fields[f] for f in changed})
    _mark_hand_typed(helper, changed)
    if "name" in changed:
        for assignment in state["assignments"]:
            if assignment["helper_id"] == helper_id:
                assignment["helper_name"] = helper["name"]
    if "friends" in changed and state["assignments"]:
        _refresh_friend_pairs(state)
    workspace.save(state)
    return state


def _refresh_friend_pairs(state: dict[str, Any]) -> None:
    satisfied, unsatisfied = _recompute_friend_pairs(state)
    state["diagnostics"]["satisfied_friend_pairs"] = satisfied
    state["diagnostics"]["unsatisfied_friend_pairs"] = unsatisfied


def _forget_as_friend(state: dict[str, Any], helper_id: int) -> None:
    """Take a deleted Helper out of everyone's Friend preference. A friend name
    that was resolved only to them goes back to unresolved rather than being
    silently dropped."""
    for other in state["helpers"]:
        other["friends"] = [f for f in other.get("friends", []) if f != helper_id]
        decisions = other.get("friend_name_decisions") or {}
        for friend_name, raw in list(decisions.items()):
            ids = [raw] if isinstance(raw, int) else list(raw or [])
            if helper_id not in ids:
                continue
            remaining = [i for i in ids if i != helper_id]
            if remaining:
                decisions[friend_name] = remaining
                continue
            del decisions[friend_name]
            if friend_name not in other["unresolved_friend_names"]:
                other["unresolved_friend_names"].append(friend_name)


def delete_helper(workspace: Workspace, helper_id: int, confirmed: bool = False) -> dict:
    """Delete a Helper, at any time.

    Like flagging Can't attend, a Helper with an Assignment or Manual role
    entries is only deleted once ``confirmed``; without it
    :class:`ConfirmationRequired` names what would be cleared and nothing
    changes. Confirming removes their Assignment (and its lock) and every Manual
    role entry holding them and raises the stale-roster flag; a Helper with
    nothing to clear is simply removed. Either way they are dropped from other
    Helpers' Friend preferences, and their id is never handed out again."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    impact = cant_attend_impact(state, helper_id)
    if impact and not confirmed:
        raise ConfirmationRequired(
            f"Deleting {helper['name']} clears " + "; ".join(impact) + ". "
            "This can't be undone, and the roster is out of date until the next Solve.",
            impact,
        )
    state["helpers"] = [h for h in state["helpers"] if h["id"] != helper_id]
    state["next_helper_id"] = max(int(state.get("next_helper_id") or 1), helper_id + 1)
    _forget_as_friend(state, helper_id)
    if impact:
        state["assignments"] = [a for a in state["assignments"] if a["helper_id"] != helper_id]
        state["manual_roles"] = {
            group: [e for e in entries if e.get("helper_id") != helper_id]
            for group, entries in state["manual_roles"].items()
        }
        _add_stale_reason(state, f"{helper['name']} was deleted: their Assignment and role entries were cleared")
    if state["assignments"]:
        _refresh_friend_pairs(state)
    workspace.save(state)
    return state


# -- Tags ------------------------------------------------------------------------


class _Unchanged:
    """Marks an :func:`update_tag` argument that was not given (``None`` is a
    real value for a parent: no parent)."""


_UNCHANGED = _Unchanged()


def _tag_definitions(state: dict[str, Any]) -> list[tag_tree.Tag]:
    return [tag_tree.tag_from_dict(t) for t in state.get("tags") or []]


def _tag_record(state: dict[str, Any], tag_id: int) -> dict:
    tag = next((t for t in state.get("tags") or [] if t["id"] == tag_id), None)
    if tag is None:
        raise RosteringError(f"No such tag: {tag_id}")
    return tag


def _validated_tag_name(state: dict[str, Any], name: str, own_id: Optional[int] = None) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise RosteringError("A tag needs a name.")
    for other in state.get("tags") or []:
        if other["id"] != own_id and tag_tree.name_key(other["name"]) == tag_tree.name_key(cleaned):
            raise RosteringError(f"A tag named {other['name']} already exists.")
    return cleaned


def _validated_tag_colour(colour: str) -> str:
    if not tag_tree.is_hex_colour(colour):
        raise RosteringError(f"A tag colour is a hex colour like #3366cc, not {colour!r}.")
    return colour.lower()


def _validated_tag_parent(state: dict[str, Any], tag_id: Optional[int], parent_id: Optional[int]) -> Optional[int]:
    if parent_id is None:
        return None
    parent = _tag_record(state, parent_id)
    if tag_id is not None and not tag_tree.can_be_parent(_tag_definitions(state), tag_id, parent_id):
        detail = "itself" if parent_id == tag_id else f"{parent['name']}, which implies it"
        raise RosteringError(f"A tag can't imply {detail}: it would become its own ancestor.")
    return parent_id


_CONSTRAINT_FIELDS = ("building_allow", "building_deny", "role_allow", "role_deny")


def _validated_constraint(field: str, entries: Sequence[str]) -> list[str]:
    """One constraint list as stored: blanks and repeats dropped, a Role
    entry (its name or its display name) stored as ``Role.name``. A Building
    entry is kept as given -- it may name a Building the Season no longer has,
    which is inert, not wrong."""
    names: list[str] = []
    for entry in entries or []:
        text = (entry or "").strip()
        if not text:
            continue
        if field.startswith("role"):
            role = parse_role_token(text)
            if role is None:
                raise RosteringError(f"No such role: {text}. A tag constraint names one of the six roles.")
            text = role.name
        names.append(text)
    return list(dict.fromkeys(names))


def _tag_universes(state: dict[str, Any]) -> dict[str, list[str]]:
    """What a Tag constraint can name this Season: its configured Buildings and
    the fixed Roles (by ``Role.name``)."""
    return {
        tag_tree.BUILDING: [b["name"] for b in state.get("config") or []],
        tag_tree.ROLE: [role.name for role in Role],
    }


def _stranded(state: dict[str, Any]) -> set[tuple[int, str]]:
    """Every ``(helper id, axis)`` that currently has no allowed Building or no
    allowed Role."""
    direct = {h["id"]: _direct_tag_ids(h) for h in state["helpers"]}
    return tag_tree.dead_ends(_tag_definitions(state), direct, _tag_universes(state))


def _refuse_new_dead_ends(state: dict[str, Any], before: set[tuple[int, str]]) -> None:
    """The one validation behind every Tag entry point (the Tags tab and the
    Helper list's inline multiselect alike): refuse an edit, already applied to
    the in-memory ``state`` but not yet saved, that leaves a Helper with no
    allowed Building or no allowed Role. Only Helpers the edit newly strands
    count, so one already stranded (say, by a later configuration change) never
    blocks an unrelated edit."""
    fresh = sorted(_stranded(state) - before)
    if not fresh:
        return
    tags = _tag_definitions(state)
    universes = _tag_universes(state)
    names = {h["id"]: h["name"] for h in state["helpers"]}
    problems = []
    for helper_id, axis in fresh:
        record = next(h for h in state["helpers"] if h["id"] == helper_id)
        found = tag_tree.restrictions(tags, _direct_tag_ids(record), axis, universes[axis])
        display = (lambda v: Role[v].value) if axis == tag_tree.ROLE else str
        why = "; ".join(tag_tree.describe_restriction(r, axis, display) for r in found)
        noun = "Role" if axis == tag_tree.ROLE else "Building"
        problems.append(f"{names[helper_id]} would be left with no allowed {noun} ({why})")
    shown, hidden = problems[:3], len(problems) - 3
    raise RosteringError("Refused: " + "; ".join(shown) + (f"; and {hidden} more" if hidden > 0 else "") + ".")


def tag_constraint_entries(state: dict[str, Any], tag_id: int) -> dict[str, list[dict]]:
    """A Tag's four constraint lists as ``{"name", "in_season"}`` entries. An
    entry naming a Building the Season's configuration no longer has is
    ``in_season: False``: inert, ignored by the solver and the checker, and
    shown as "not in this Season"."""
    record = _tag_record(state, tag_id)
    universes = _tag_universes(state)
    entries: dict[str, list[dict]] = {}
    for field in _CONSTRAINT_FIELDS:
        axis = field.split("_")[0]
        entries[field] = [
            {"name": entry, "in_season": tag_tree.entry_in_universe(axis, entry, universes[axis])}
            for entry in record.get(field) or []
        ]
    return entries


def helper_allowed(state: dict[str, Any], helper_id: int) -> dict[str, list[str]]:
    """A Helper's allowed sets from their effective Tag constraints (see
    CONTEXT.md "Tag constraint"), computed live: ``buildings`` (the Season's
    configured Building names) and ``roles`` (``Role.name``), each in
    configuration order. The solver and the live checker judge through the same
    function."""
    direct = _direct_tag_ids(_helper_record(state, helper_id))
    tags = _tag_definitions(state)
    universes = _tag_universes(state)
    return {
        "buildings": tag_tree.allowed_values(tags, direct, tag_tree.BUILDING, universes[tag_tree.BUILDING]),
        "roles": tag_tree.allowed_values(tags, direct, tag_tree.ROLE, universes[tag_tree.ROLE]),
    }


def add_tag(
    workspace: Workspace,
    name: str,
    *,
    colour: Optional[str] = None,
    note: str = "",
    parent_id: Optional[int] = None,
    building_allow: Sequence[str] = (),
    building_deny: Sequence[str] = (),
    role_allow: Sequence[str] = (),
    role_deny: Sequence[str] = (),
) -> dict:
    """Create a Tag in the open Season (see CONTEXT.md "Tag"): a required name,
    unique among the Season's Tags ignoring case, a hex colour (each new Tag
    otherwise gets the next colour of a fixed palette), a free note, an
    optional single parent Tag it implies and its Tag constraints -- allow- and
    deny-lists of Building and Role names. The new Tag is the last of
    ``state["tags"]``. Nobody carries a new Tag, so no constraint can strand
    anyone yet."""
    state = workspace.load()
    tags = state.setdefault("tags", [])
    given = dict(zip(_CONSTRAINT_FIELDS, (building_allow, building_deny, role_allow, role_deny)))
    record = {
        "id": _next_tag_id(state),
        "name": _validated_tag_name(state, name),
        "colour": _validated_tag_colour(colour or tag_tree.PALETTE[len(tags) % len(tag_tree.PALETTE)]),
        "note": (note or "").strip(),
        "parent_id": _validated_tag_parent(state, None, parent_id),
        **{field: _validated_constraint(field, entries) for field, entries in given.items()},
    }
    tags.append(record)
    workspace.save(state)
    return state


def update_tag(
    workspace: Workspace,
    tag_id: int,
    *,
    name: Optional[str] = None,
    colour: Optional[str] = None,
    note: Optional[str] = None,
    parent_id: Optional[int] | _Unchanged = _UNCHANGED,
    building_allow: Optional[Sequence[str]] = None,
    building_deny: Optional[Sequence[str]] = None,
    role_allow: Optional[Sequence[str]] = None,
    role_deny: Optional[Sequence[str]] = None,
) -> dict:
    """Edit a Tag; fields left out stay as they are, and ``parent_id=None``
    makes it a root. The same rules as :func:`add_tag` apply, and a Tag can
    never be given itself or one of its own descendants as parent, which would
    make it its own ancestor. An edit of its constraints or parent that would
    leave any Helper with no allowed Building or no allowed Role is refused
    with the reason. Nothing changes if any field is refused."""
    state = workspace.load()
    record = _tag_record(state, tag_id)
    before = _stranded(state)
    changes: dict[str, Any] = {}
    if name is not None:
        changes["name"] = _validated_tag_name(state, name, own_id=tag_id)
    if colour is not None:
        changes["colour"] = _validated_tag_colour(colour)
    if note is not None:
        changes["note"] = note.strip()
    if not isinstance(parent_id, _Unchanged):
        changes["parent_id"] = _validated_tag_parent(state, tag_id, parent_id)
    given = dict(zip(_CONSTRAINT_FIELDS, (building_allow, building_deny, role_allow, role_deny)))
    for field, entries in given.items():
        if entries is not None:
            changes[field] = _validated_constraint(field, entries)
    record.update(changes)
    _refuse_new_dead_ends(state, before)
    workspace.save(state)
    return state


def _direct_tag_ids(helper: dict) -> list[int]:
    return list(helper.get("tags") or [])


def helper_tags(state: dict[str, Any], helper_id: int) -> dict[str, list[int]]:
    """A Helper's Tags as Tag ids, computed live from the Tag tree: ``direct``
    (assigned to them, in the order assigned), ``implied`` (every ancestor of a
    direct Tag that is not itself direct, nearest first) and ``effective``
    (both). Nothing here is stored on the Helper but the direct ones."""
    tags = _tag_definitions(state)
    direct = [t for t in dict.fromkeys(_direct_tag_ids(_helper_record(state, helper_id))) if any(x.id == t for x in tags)]
    implied = tag_tree.implied_tag_ids(tags, direct)
    return {"direct": direct, "implied": implied, "effective": [*direct, *implied]}


def _assign_tags(state: dict[str, Any], helper: dict, tag_ids: list[int]) -> None:
    """The single place a Helper's direct Tags are written."""
    known = {t["id"] for t in state.get("tags") or []}
    for tag_id in tag_ids:
        if tag_id not in known:
            raise RosteringError(f"No such tag: {tag_id}")
    helper["tags"] = list(dict.fromkeys(tag_ids))


def set_helper_tags(workspace: Workspace, helper_id: int, tag_ids: list[int]) -> dict:
    """Replace the Tags assigned directly to one Helper (the Helper list's
    inline multiselect). Implied Tags follow by themselves. Refused, with the
    reason, if it would leave them no allowed Building or no allowed Role."""
    state = workspace.load()
    before = _stranded(state)
    _assign_tags(state, _helper_record(state, helper_id), list(tag_ids))
    _refuse_new_dead_ends(state, before)
    workspace.save(state)
    return state


def add_tag_to_helpers(workspace: Workspace, tag_id: int, helper_ids: list[int]) -> dict:
    """Give one Tag directly to each of these Helpers, keeping whatever else
    they carry (the Tags tab's "Add N to <tag>" and the Helper list's bulk
    apply). All or nothing: an unknown Helper or Tag, or one Helper the Tag
    would leave with no allowed Building or Role, changes nobody."""
    state = workspace.load()
    _tag_record(state, tag_id)
    helpers = [_helper_record(state, helper_id) for helper_id in helper_ids]
    before = _stranded(state)
    for helper in helpers:
        _assign_tags(state, helper, [*_direct_tag_ids(helper), tag_id])
    _refuse_new_dead_ends(state, before)
    workspace.save(state)
    return state


def remove_tag_from_helper(workspace: Workspace, tag_id: int, helper_id: int) -> dict:
    """Take a directly assigned Tag off a Helper. A Tag they carry only by
    implication is removed by removing the Tag that implies it."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    _assign_tags(state, helper, [t for t in _direct_tag_ids(helper) if t != tag_id])
    workspace.save(state)
    return state


def tag_carriers(state: dict[str, Any], tag_id: int) -> list[dict]:
    """Every Helper who carries a Tag, directly or by implication, by name:
    ``helper_id``, ``name`` and ``via`` — None for a direct carrier, else the id
    of the direct Tag that implies it for them."""
    _tag_record(state, tag_id)
    tags = _tag_definitions(state)
    carriers = []
    for helper in state["helpers"]:
        direct = helper_tags(state, helper["id"])["direct"]
        if tag_id in direct:
            carriers.append({"helper_id": helper["id"], "name": helper["name"], "via": None})
        elif tag_id in tag_tree.effective_tag_ids(tags, direct):
            carriers.append(
                {"helper_id": helper["id"], "name": helper["name"], "via": tag_tree.via_tag_id(tags, direct, tag_id)}
            )
    return sorted(carriers, key=lambda c: c["name"].lower())


def tag_helper_counts(state: dict[str, Any]) -> dict[int, int]:
    """Tag id -> how many Helpers carry it, directly or by implication."""
    counts = {t["id"]: 0 for t in state.get("tags") or []}
    for helper in state["helpers"]:
        for tag_id in helper_tags(state, helper["id"])["effective"]:
            counts[tag_id] += 1
    return counts


def grid_tag_pills(state: dict[str, Any]) -> dict[int, dict[str, list[dict[str, str]]]]:
    """Each Helper's Tag pills for the roster grid, by Helper id: ``direct``
    (solid pills) and ``implied`` (dashed pills), each a ``{name, colour}``,
    computed live from the Tag tree like every effective Tag."""
    by_id = {t["id"]: t for t in state.get("tags") or []}

    def pill(tag_id: int) -> dict[str, str]:
        return {"name": by_id[tag_id]["name"], "colour": by_id[tag_id]["colour"]}

    pills = {}
    for helper in state["helpers"]:
        found = helper_tags(state, helper["id"])
        pills[helper["id"]] = {
            "direct": [pill(t) for t in found["direct"]],
            "implied": [pill(t) for t in found["implied"]],
        }
    return pills


def dimmed_helper_ids(state: dict[str, Any], tag_ids: list[int], mode: str) -> list[int]:
    """The Helpers the roster grid's Tag filter dims: everyone who does not match
    ``tag_ids`` (all-of or any-of, ``mode`` ``"all"``/``"any"``; inherited Tags
    count). Nobody is dimmed by an empty filter. Dimming never hides anyone."""
    tags = _tag_definitions(state)
    return [
        helper["id"]
        for helper in state["helpers"]
        if not tag_tree.matches_filter(tags, helper_tags(state, helper["id"])["direct"], tag_ids, mode)
    ]


def tag_delete_impact(state: dict[str, Any], tag_id: int) -> dict[str, list[str]]:
    """What deleting a Tag would change, by name: ``helpers`` it would be
    stripped from (those who carry it directly) and ``children`` that would be
    re-parented. Both empty means the delete needs no confirmation."""
    record = _tag_record(state, tag_id)
    return {
        "helpers": sorted(
            (h["name"] for h in state["helpers"] if tag_id in _direct_tag_ids(h)), key=str.lower
        ),
        "children": sorted(
            (t["name"] for t in state["tags"] if t["parent_id"] == record["id"]), key=str.lower
        ),
    }


def delete_tag(workspace: Workspace, tag_id: int, confirmed: bool = False) -> dict:
    """Delete a Tag. One that is carried directly by a Helper or has child Tags
    is only deleted once ``confirmed``; without it :class:`ConfirmationRequired`
    lists the affected Helpers and child Tags and nothing changes. Confirming
    strips the Tag from those Helpers and re-parents its children to its own
    parent (they become roots if it had none)."""
    state = workspace.load()
    record = _tag_record(state, tag_id)
    impact = tag_delete_impact(state, tag_id)
    if (impact["helpers"] or impact["children"]) and not confirmed:
        lines = []
        if impact["helpers"]:
            lines.append("Removed from: " + ", ".join(impact["helpers"]))
        if impact["children"]:
            parent = next((t["name"] for t in state["tags"] if t["id"] == record["parent_id"]), None)
            lines.append(
                f"Child tags {', '.join(impact['children'])} "
                + (f"move up to {parent}" if parent else "become top-level tags")
            )
        raise ConfirmationRequired(f"Deleting the tag {record['name']} changes: " + "; ".join(lines) + ".", lines)
    for helper in state["helpers"]:
        if tag_id in _direct_tag_ids(helper):
            helper["tags"] = [t for t in helper["tags"] if t != tag_id]
    for child in state["tags"]:
        if child["parent_id"] == tag_id:
            child["parent_id"] = record["parent_id"]
    state["tags"] = [t for t in state["tags"] if t["id"] != tag_id]
    state["next_tag_id"] = max(int(state.get("next_tag_id") or 1), tag_id + 1)
    # An imported Tag deleted on purpose is remembered per source Season, so an
    # explicit re-import brings it back and says so (see import_from_season).
    for origin in record.get("origins") or []:
        deleted = state.setdefault("tag_imports", {}).setdefault(
            origin["season_id"], {"label": "", "deleted_tag_ids": []}
        )["deleted_tag_ids"]
        if origin["tag_id"] not in deleted:
            deleted.append(origin["tag_id"])
    workspace.save(state)
    return state


def _next_tag_id(state: dict[str, Any]) -> int:
    """A Tag id above every id in use and above every id ever handed out
    (``next_tag_id`` is that high-water mark, so a deleted Tag's id is not
    reused)."""
    new_id = max(int(state.get("next_tag_id") or 1), max((t["id"] for t in state.get("tags") or []), default=0) + 1)
    state["next_tag_id"] = new_id + 1
    return new_id


# -- Tag import ------------------------------------------------------------------
#
# Bringing an earlier Season's Tags into the open Season (see CONTEXT.md "Tag
# import"). The offer is section-based: every importable thing is an
# ``ImportSection`` in ``_IMPORT_SECTIONS`` (Tags first; Forced-friends groups
# register a second one), each run over the same source Season and saved
# together. State kept in the open Season: a Tag copy's ``origins`` (source
# Season id + source Tag id, surviving renames) and ``state["tag_imports"]``
# (per source Season: its label, the source Tags whose imported copy was
# deliberately deleted, and Class promotion's records: ``promoted_years`` and
# ``unpromoted_tag_ids``, see "Class promotion" below).


@dataclass
class ImportContext:
    """What an import section works on: the open Season's ``state`` (changed in
    place, saved once after every section ran), the earlier Season's
    ``source_state`` (read only), the ``source`` and ``season`` identities
    (``{"id", "label"}``) and the ``person_records`` of every stored Season."""

    state: dict[str, Any]
    source_state: dict[str, Any]
    source: dict[str, str]
    season: dict[str, str]
    person_records: list


@dataclass(frozen=True)
class ImportSection:
    """One importable thing: a ``key``, a ``title`` for the UI and ``run``, which
    imports it and returns its summary (a dict; ``lines`` are shown as text)."""

    key: str
    title: str
    run: Callable[[ImportContext], dict[str, Any]]


_IMPORT_SECTIONS: list[ImportSection] = []


def register_import_section(section: ImportSection) -> None:
    """Add a section to the import offer, after the ones already there."""
    if any(existing.key == section.key for existing in _IMPORT_SECTIONS):
        raise ValueError(f"An import section {section.key!r} is already registered.")
    _IMPORT_SECTIONS.append(section)


def import_sources(workspace: Workspace) -> list[dict]:
    """The Seasons the open Season can import from: every earlier stored Season
    (it has a saved state by being stored), most recent first, as ``id``,
    ``label``, ``helper_count`` and ``tag_count``. Empty with no Season open."""
    season = workspace.open_season()
    if season is None:
        return []
    now = label_sort_key(season["label"])
    sources = []
    for stored in workspace.list_seasons():
        if label_sort_key(stored["label"]) >= now:
            continue
        saved = workspace.stored_state(stored["id"]) or {}
        sources.append(
            {
                "id": stored["id"],
                "label": stored["label"],
                "helper_count": stored["helper_count"],
                "tag_count": len(saved.get("tags") or []),
            }
        )
    return sources


def default_import_source(workspace: Workspace) -> Optional[dict]:
    """The most recent earlier stored Season, or None if there is none."""
    sources = import_sources(workspace)
    return sources[0] if sources else None


def tag_import_offer(workspace: Workspace) -> dict:
    """What the import offer shows: ``sources`` (see :func:`import_sources`),
    ``default_source_id``, the ``sections`` it will import (``key``, ``title``)
    and ``banner`` — whether to nudge the user after the first upload: the
    Season has Helpers but no Tags yet and some earlier Season has Tags to bring.
    Nothing here waits for the uncertain-match review."""
    sources = import_sources(workspace)
    state = workspace.load() if workspace.open_season() is not None else None
    banner = bool(
        state is not None and state["helpers"] and not state["tags"] and any(s["tag_count"] for s in sources)
    )
    return {
        "sources": sources,
        "default_source_id": sources[0]["id"] if sources else None,
        "sections": [{"key": s.key, "title": s.title} for s in _IMPORT_SECTIONS],
        "banner": banner,
    }


def _origin(source_id: str, source_tag_id: int) -> dict[str, Any]:
    return {"season_id": source_id, "tag_id": source_tag_id}


def _imported_name(source_tag: dict, record: Optional[dict]) -> str:
    """The name a source Season's Tag has in this Season: as it was there, moved
    up by the Class promotion steps already applied for that source, unless the
    Tag was deliberately left unpromoted (``record`` is the source's entry of
    ``state["tag_imports"]``)."""
    years = int((record or {}).get("promoted_years") or 0)
    if years and source_tag["id"] not in (record.get("unpromoted_tag_ids") or []):
        return tag_tree.promoted_class_name(source_tag["name"], years) or source_tag["name"]
    return source_tag["name"]


def _resolve_import_tag(
    tags: list[dict], source_id: str, source_tag: dict, record: Optional[dict] = None
) -> Optional[dict]:
    """The Tag of this Season that stands for a source Season's Tag: the one
    that remembers it as an origin (whatever it is called now), else the one
    named as the source Tag is called here (:func:`_imported_name`, so a
    promoted class is found as "9.M" and no stray "8.M" is made)."""
    origin = _origin(source_id, source_tag["id"])
    by_origin = next((t for t in tags if origin in (t.get("origins") or [])), None)
    if by_origin is not None:
        return by_origin
    key = tag_tree.name_key(_imported_name(source_tag, record))
    return next((t for t in tags if tag_tree.name_key(t["name"]) == key), None)


def _source_direct_tags_by_person(source_state: dict[str, Any]) -> dict[str, list[int]]:
    """Person id -> the Tags (ids of the source Season) its Helper records there
    carry directly, in the order carried; only Tags that still exist."""
    known = {t["id"] for t in source_state.get("tags") or []}
    by_person: dict[str, list[int]] = {}
    for helper in source_state["helpers"]:
        person_id = helper.get("person_id")
        if not person_id:
            continue
        carried = by_person.setdefault(person_id, [])
        carried.extend(t for t in helper.get("tags") or [] if t in known and t not in carried)
    return by_person


def _add_valid_tags(state: dict[str, Any], helper: dict, tag_ids: Sequence[int]) -> tuple[list[int], list[dict]]:
    """Give a Helper these Tags directly, one by one, skipping any that would
    leave them with no allowed Building or Role they did not already lack (the
    same test as :func:`_refuse_new_dead_ends`, but a skip instead of a refusal)
    and any they carry already. Returns ``(added Tag ids, skipped)``; a skip is
    ``helper_id``, ``helper``, ``tag_id``, ``tag`` and ``reason``."""
    tags = _tag_definitions(state)
    names = {t.id: t.name for t in tags}
    universes = _tag_universes(state)
    direct = _direct_tag_ids(helper)
    before = tag_tree.dead_ends(tags, {helper["id"]: direct}, universes)
    added: list[int] = []
    skipped: list[dict] = []
    for tag_id in dict.fromkeys(tag_ids):
        if tag_id in direct:
            continue
        fresh = sorted(tag_tree.dead_ends(tags, {helper["id"]: [*direct, tag_id]}, universes) - before)
        if fresh:
            nouns = " or ".join("Role" if axis == tag_tree.ROLE else "Building" for _, axis in fresh)
            skipped.append(
                {
                    "helper_id": helper["id"],
                    "helper": helper["name"],
                    "tag_id": tag_id,
                    "tag": names[tag_id],
                    "reason": f"would leave {helper['name']} with no allowed {nouns}",
                }
            )
            continue
        direct = [*direct, tag_id]
        added.append(tag_id)
    if added:
        helper["tags"] = direct
    return added, skipped


def _import_tags_section(context: ImportContext) -> dict[str, Any]:
    """The Tags section: copy the source's Tag tree (each Tag it lacks, matched
    by origin then name), then re-apply the directly carried Tags to every
    confidently linked Person."""
    state, source_state, source = context.state, context.source_state, context.source
    source_tags = source_state.get("tags") or []
    tags = state.setdefault("tags", [])
    universes = _tag_universes(state)
    record = state["tag_imports"][source["id"]]
    deleted = set(record["deleted_tag_ids"])

    created: list[str] = []
    restored: list[str] = []
    reused: list[str] = []
    dropped: list[dict] = []
    mapping: dict[int, int] = {}  # source Tag id -> this Season's Tag id
    for source_def, _ in tag_tree.tree_order([tag_tree.tag_from_dict(t) for t in source_tags]):
        source_tag = next(t for t in source_tags if t["id"] == source_def.id)
        target = _resolve_import_tag(tags, source["id"], source_tag, record)
        origin = _origin(source["id"], source_tag["id"])
        if target is None:
            constraints = {}
            for field in _CONSTRAINT_FIELDS:
                axis = field.split("_")[0]
                kept = []
                for entry in source_tag.get(field) or []:
                    if tag_tree.entry_in_universe(axis, entry, universes[axis]):
                        kept.append(entry)
                    else:
                        dropped.append({"tag": source_tag["name"], "field": field, "entry": entry})
                constraints[field] = kept
            target = {
                "id": _next_tag_id(state),
                "name": _imported_name(source_tag, record),
                "colour": source_tag.get("colour") or tag_tree.PALETTE[0],
                "note": source_tag.get("note") or "",
                "parent_id": mapping.get(source_tag.get("parent_id")),
                **constraints,
                "origins": [origin],
            }
            tags.append(target)
            (restored if source_tag["id"] in deleted else created).append(target["name"])
        else:
            reused.append(target["name"])
            if origin not in (target.get("origins") or []):
                target.setdefault("origins", []).append(origin)
        mapping[source_tag["id"]] = target["id"]
        deleted.discard(source_tag["id"])
    record["deleted_tag_ids"] = sorted(d for d in deleted if any(t["id"] == d for t in source_tags))

    carried = _source_direct_tags_by_person(source_state)
    tagged: list[str] = []
    skipped: list[dict] = []
    for helper in state["helpers"]:
        wanted = [mapping[t] for t in carried.get(helper.get("person_id"), []) if t in mapping]
        if not wanted:
            continue
        added, refused = _add_valid_tags(state, helper, wanted)
        skipped.extend(refused)
        if added:
            tagged.append(helper["name"])

    awaiting: list[str] = []
    proposals = uncertain_candidates(context.person_records, context.season["id"])
    for helper in sorted(state["helpers"], key=lambda h: h["id"]):
        if any(carried.get(c.person_id) for c in proposals.get(helper["id"], [])):
            awaiting.append(helper["name"])

    def names(items: Sequence[str]) -> str:
        return f" ({', '.join(items)})" if items else ""

    lines = [f"Tags created: {len(created)}{names(created)}"]
    if restored:
        lines.append(f"Restored (deleted earlier, imported again): {len(restored)}{names(restored)}")
    if reused:
        lines.append(f"Already in this Season, not copied again: {len(reused)}{names(reused)}")
    lines.append(f"Helpers tagged: {len(tagged)}{names(tagged)}")
    lines.append(
        f"Constraint entries dropped (not in this Season): {len(dropped)}"
        + names([f"{d['tag']}: {d['entry']}" for d in dropped])
    )
    lines.append(
        f"Assignments skipped (would leave no allowed Building or Role): {len(skipped)}"
        + names([f"{s['helper']} - {s['tag']}" for s in skipped])
    )
    lines.append(f"Helpers awaiting review, not tagged: {len(awaiting)}{names(awaiting)}")
    return {
        "tags_created": created,
        "tags_restored": restored,
        "tags_reused": reused,
        "helpers_tagged": tagged,
        "dropped_constraint_entries": dropped,
        "skipped_assignments": skipped,
        "awaiting_review": awaiting,
        "lines": lines,
    }


register_import_section(ImportSection("tags", "Tags", _import_tags_section))


def import_from_season(workspace: Workspace, source_season_id: str) -> dict:
    """Import from one earlier stored Season into the open one: every registered
    section runs against the source (Tags first) and everything is saved
    together — or nothing, if any of it fails. Running it again, from this or
    another Season, is additive and never copies a Tag twice. The source Season
    is only read. Returns ``{"source": {"id", "label"}, "sections": [...],
    "promotion_prompt": bool}``, each section its ``key``, ``title`` and own
    summary (the Tags section's is described in :func:`_import_tags_section`);
    ``promotion_prompt`` says the Class promotion dialog should open by itself
    (the open Season is podzim and a school year turned since the source)."""
    season = workspace.open_season()
    if season is None:
        raise RosteringError("Open a Season (or upload responses to create one) before importing Tags.")
    source = next((s for s in import_sources(workspace) if s["id"] == source_season_id), None)
    if source is None:
        raise RosteringError("Pick an earlier stored Season to import from.")
    state = workspace.load()
    source_state = workspace.stored_state(source["id"])
    identity = {"id": source["id"], "label": source["label"]}
    record = state.setdefault("tag_imports", {}).setdefault(
        source["id"], {"label": source["label"], "deleted_tag_ids": []}
    )
    record["label"] = source["label"]
    context = ImportContext(state, source_state, identity, season, workspace.person_records())
    sections = [{"key": s.key, "title": s.title, **s.run(context)} for s in _IMPORT_SECTIONS]
    workspace.save(state)
    prompt = season["label"].endswith("-podzim") and school_years_crossed(source["label"], season["label"]) >= 1
    return {"source": identity, "sections": sections, "promotion_prompt": prompt}


def _late_link_tags(workspace: Workspace, state: dict[str, Any], helper: dict) -> list[dict]:
    """The Tags a Helper's Person carried in an imported Season, resolved into
    this Season by origin first and name second: ``tag_id``, ``name`` and
    ``source`` (that Season's label). A Tag that no longer resolves (deleted on
    purpose) is left out, and so is one the Helper already carries."""
    person_id = helper.get("person_id")
    direct = _direct_tag_ids(helper)
    found: dict[int, dict] = {}
    for source_id in state.get("tag_imports") or {}:
        source_state = workspace.stored_state(source_id)
        if source_state is None:
            continue
        by_id = {t["id"]: t for t in source_state["tags"]}
        record = state["tag_imports"][source_id]
        for source_tag_id in _source_direct_tags_by_person(source_state).get(person_id, []):
            target = _resolve_import_tag(state["tags"], source_id, by_id[source_tag_id], record)
            if target is not None and target["id"] not in direct:
                found.setdefault(
                    target["id"],
                    {"tag_id": target["id"], "name": target["name"], "source": source_state["season"]["label"]},
                )
    return list(found.values())


def late_link_tag_offer(workspace: Workspace, helper_id: int) -> Optional[dict]:
    """After a Helper's link to an earlier Person is confirmed: the Tags that
    Person carried in a Season already imported from, if any could be applied
    ("apply their Tags?") — ``helper_id``, ``helper_name`` and ``tags`` (see
    :func:`_late_link_tags`), or None when there is nothing to offer. Nothing is
    applied and no Tag is created; a deliberately deleted Tag stays deleted."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    tags = _late_link_tags(workspace, state, helper)
    if not tags:
        return None
    return {"helper_id": helper_id, "helper_name": helper["name"], "tags": tags}


def apply_late_link_tags(workspace: Workspace, helper_id: int) -> dict:
    """Give a late-linked Helper the Tags offered by :func:`late_link_tag_offer`,
    skipping any that would leave them with no allowed Building or Role. Returns
    ``applied`` (Tag names) and ``skipped`` (as in the import summary)."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    offered = _late_link_tags(workspace, state, helper)
    added, skipped = _add_valid_tags(state, helper, [t["tag_id"] for t in offered])
    workspace.save(state)
    return {"applied": [t["name"] for t in offered if t["tag_id"] in added], "skipped": skipped}


# -- Class promotion -------------------------------------------------------------
#
# Renaming school-class Tags one school year up per school year crossed since the
# Season they were imported from (see CONTEXT.md "Class promotion"). The years
# are counted from a Tag's newest origin. What the Season remembers, per source,
# in ``state["tag_imports"][source id]``: ``promoted_years`` (the years applied to
# that source's Tags) and ``unpromoted_tag_ids`` (source Tags the user left
# unticked), which decide the name a Tag gets when a later import or a
# late-confirmed link resolves it (:func:`_imported_name`).


def _class_promotions(state: dict[str, Any], labels: dict[str, str], season_label: str) -> list[dict]:
    """Every class Tag with an origin, with the years it still can move: ``tag``,
    ``source_id``, ``source_tag_id``, ``crossed`` (school years since the source
    Season) and ``remaining`` (what is left to apply, at least 0)."""
    found = []
    for tag in state.get("tags") or []:
        if not tag_tree.is_class_name(tag["name"]):
            continue
        sources = []
        for origin in tag.get("origins") or []:
            record = (state.get("tag_imports") or {}).get(origin["season_id"])
            label = labels.get(origin["season_id"]) or (record or {}).get("label")
            if label:
                sources.append((label_sort_key(label), origin, label, record or {}))
        if not sources:
            continue
        _, origin, label, record = max(sources, key=lambda source: source[0])
        crossed = school_years_crossed(label, season_label)
        left_alone = origin["tag_id"] in (record.get("unpromoted_tag_ids") or [])
        applied = 0 if left_alone else int(record.get("promoted_years") or 0)
        found.append(
            {
                "tag": tag,
                "source_id": origin["season_id"],
                "source_tag_id": origin["tag_id"],
                "crossed": crossed,
                "remaining": max(0, crossed - applied),
            }
        )
    return found


def class_promotion_offer(workspace: Workspace) -> dict:
    """What the Class promotion dialog shows: ``suggestions`` (each ``tag_id``,
    ``name`` and ``target``: the class Tags imported from an earlier Season that a
    school year has since passed), ``other_tags`` (every other Tag, which can be
    added by hand: ``target`` is its exact current name, to be edited) and
    ``nothing_to_promote`` (no suggestion). How many school years were crossed is
    deliberately not part of it. Nothing is changed."""
    season = workspace.open_season()
    if season is None:
        raise RosteringError("Open a Season before promoting classes.")
    state = workspace.load()
    labels = {s["id"]: s["label"] for s in workspace.list_seasons()}
    suggestions = []
    for item in _class_promotions(state, labels, season["label"]):
        if item["remaining"]:
            tag = item["tag"]
            target = tag_tree.promoted_class_name(tag["name"], item["remaining"])
            suggestions.append({"tag_id": tag["id"], "name": tag["name"], "target": target})
    suggestions.sort(key=lambda s: (int(s["name"].split(".")[0]), tag_tree.name_key(s["name"])))
    suggested = {s["tag_id"] for s in suggestions}
    return {
        "suggestions": suggestions,
        "other_tags": [
            {"tag_id": t["id"], "name": t["name"], "target": t["name"]}
            for t in state.get("tags") or []
            if t["id"] not in suggested
        ],
        "nothing_to_promote": not suggestions,
    }


def _class_promotion_changes(state: dict[str, Any], renames: dict[int, str]) -> dict[int, str]:
    """The ticked renames that actually change a name (a typed target equal to
    the current name is no rename), targets trimmed."""
    changes = {}
    for tag_id, target in renames.items():
        record = _tag_record(state, tag_id)
        target = (target or "").strip()
        if target != record["name"]:
            changes[tag_id] = target
    return changes


def _class_promotion_conflicts(state: dict[str, Any], changes: dict[int, str]) -> list[str]:
    names = {t["id"]: t["name"] for t in state.get("tags") or []}
    final = {tag_id: changes.get(tag_id, name) for tag_id, name in names.items()}
    problems = []
    for tag_id, target in changes.items():
        if not target:
            problems.append(f"The new name of {names[tag_id]} is empty.")
            continue
        for other_id, other in final.items():
            if other_id == tag_id or tag_tree.name_key(other) != tag_tree.name_key(target):
                continue
            if other_id not in changes:
                problems.append(
                    f"{names[tag_id]} would become {target}, but a Tag named {names[other_id]} is not ticked "
                    "and keeps its name. Tags are never merged."
                )
            elif other_id > tag_id:
                problems.append(f"{names[tag_id]} and {names[other_id]} would both be named {target}.")
    return problems


def class_promotion_conflicts(workspace: Workspace, renames: dict[int, str]) -> list[str]:
    """Why these ticked renames (Tag id -> target name) cannot be applied, one
    line each: an empty target, or a target another Tag keeps or is renamed to
    (names compare ignoring case). Empty means Apply is allowed."""
    state = workspace.load()
    return _class_promotion_conflicts(state, _class_promotion_changes(state, renames))


def apply_class_promotion(workspace: Workspace, renames: dict[int, str]) -> dict:
    """Apply the ticked renames (Tag id -> target name) in place, all at once so
    a chain of classes shifts without trampling: only the name changes (parent,
    children, constraints, colour, note, carriers stay). Refused, changing
    nothing, if :func:`class_promotion_conflicts` finds any. Tags are never
    merged and only the open Season is edited. Each suggestion left out of
    ``renames`` is remembered as deliberately left unpromoted, and the source
    Seasons of the ticked ones as promoted, so later imports and late-confirmed
    links resolve the promoted name. Returns the new state."""
    season = workspace.open_season()
    if season is None:
        raise RosteringError("Open a Season before promoting classes.")
    state = workspace.load()
    changes = _class_promotion_changes(state, renames)
    problems = _class_promotion_conflicts(state, changes)
    if problems:
        raise RosteringError(" ".join(problems))
    labels = {s["id"]: s["label"] for s in workspace.list_seasons()}
    for item in _class_promotions(state, labels, season["label"]):
        if not item["remaining"]:
            continue
        record = state["tag_imports"][item["source_id"]]
        unpromoted = record.setdefault("unpromoted_tag_ids", [])
        if item["tag"]["id"] in renames:
            record["promoted_years"] = max(int(record.get("promoted_years") or 0), item["crossed"])
            if item["source_tag_id"] in unpromoted:
                unpromoted.remove(item["source_tag_id"])
        elif item["source_tag_id"] not in unpromoted:
            unpromoted.append(item["source_tag_id"])
    for tag_id, target in changes.items():
        _tag_record(state, tag_id)["name"] = target
    workspace.save(state)
    return state


def tag_origin_labels(state: dict[str, Any], tag_id: int) -> list[str]:
    """The Seasons (by label) an imported Tag was copied from, or matched to."""
    imports = state.get("tag_imports") or {}
    return [
        (imports.get(origin["season_id"]) or {}).get("label") or "an earlier Season"
        for origin in _tag_record(state, tag_id).get("origins") or []
    ]


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


def _split_locks(state: dict[str, Any]) -> tuple[list[Assignment], list[str]]:
    """The Locked Assignments a full Solve holds fixed, and the reason for each
    lock it drops instead: a lock whose Helper, Building or Room no longer
    exists is dropped (that Helper is re-solved as unlocked)."""
    rooms = {(b["name"], r["name"]) for b in state["config"] for r in b["rooms"]}
    buildings = {b["name"] for b in state["config"]}
    helper_ids = {h["id"] for h in state["helpers"] if not h.get("cant_attend")}
    kept: list[Assignment] = []
    dropped: list[str] = []
    for data in state["assignments"]:
        if not data.get("locked"):
            continue
        assignment = assignment_from_dict(data)
        if assignment.helper_id not in helper_ids:
            dropped.append(f"Helper {assignment.helper_name} no longer exists")
        elif assignment.building not in buildings:
            dropped.append(f"Building {assignment.building} no longer exists")
        elif (assignment.building, assignment.room) not in rooms:
            dropped.append(f"Room {assignment.room} no longer exists")
        else:
            kept.append(assignment)
    return kept, dropped


def _dropped_locks_lines(reasons: list[str]) -> list[str]:
    """The Solve result's note on dropped locks, e.g. ``"2 locks dropped: Room
    R2 no longer exists"`` (empty when none were)."""
    if not reasons:
        return []
    distinct = list(dict.fromkeys(reasons))
    noun = "lock" if len(reasons) == 1 else "locks"
    return [f"{len(reasons)} {noun} dropped: {'; '.join(distinct)}"]


def locked_count(state: dict[str, Any]) -> int:
    """How many Assignments are locked (the bottom bar's live count)."""
    return sum(1 for a in state["assignments"] if a.get("locked"))


def unlocked_assignments_replaced(state: dict[str, Any]) -> int:
    """How many Assignments a full Solve would replace: everything not held by a
    Locked Assignment (a lock the Solve drops counts as replaced). Zero — so no
    confirmation is needed — when nothing is placed yet or all are locked."""
    kept, _ = _split_locks(state)
    return len(state["assignments"]) - len(kept)


def solve(workspace: Workspace) -> dict:
    state = workspace.load()
    if not state["helpers"]:
        raise RosteringError("Upload a responses file first.")
    if all(h.get("cant_attend") for h in state["helpers"]):
        raise RosteringError("Every helper is marked Can't attend, so there is nobody to solve for.")
    if not state["config"]:
        raise RosteringError("Configure at least one building first.")

    comp = _build_competition(state)
    solver_config = solver_config_from_dict(state["solver_config"])
    fixed, dropped = _split_locks(state)
    try:
        result = solve_competition(comp, solver_config, fixed_assignments=fixed)
    except NoRosterFound as exc:
        # Nothing to store: the previous roster (if any) is left untouched.
        raise RosteringError(str(exc)) from exc

    # A full Solve keeps the locked Assignments and replaces every other one.
    locked_ids = {a.helper_id for a in fixed}
    state["assignments"] = [
        assignment_to_dict(replace(a, locked=a.helper_id in locked_ids)) for a in result.assignments
    ]
    state["diagnostics"] = {
        "status": result.status,
        "objective_value": result.objective_value,
        "unsatisfied_friend_pairs": [list(p) for p in result.unsatisfied_friend_pairs],
        "satisfied_friend_pairs": [list(p) for p in result.satisfied_friend_pairs],
        # What the solver had to bend, as of this solve — later hand edits do
        # not update it. Not shown: the banner judges the roster live
        # (``broken_rules``).
        "broken_rules": [
            {"family": b.family, "amount": b.amount, "line": b.line} for b in result.broken_rules
        ],
        # The locks this solve dropped because their Helper/Room/Building is
        # gone (each Helper was re-solved unlocked); shown once after a solve.
        "dropped_locks": _dropped_locks_lines(dropped),
    }
    # The roster is fresh again: whatever made it stale has been solved for.
    state["stale_reasons"] = []
    workspace.save(state)
    return state


def broken_rules(state: dict[str, Any]) -> list[BrokenRule]:
    """The Broken rules of the roster in ``state`` as it stands right now
    (see CONTEXT.md "Broken rule"): judged live on every call from the current
    Assignments and configuration, never stored. Nothing is judged before the
    first solve — an empty roster is not a roster that breaks its minimums."""
    if not state["assignments"]:
        return []
    assignments = [assignment_from_dict(a) for a in state["assignments"]]
    return check_roster(_build_competition(state), assignments)


def newly_broken_rules(before: dict[str, Any], after: dict[str, Any]) -> list[BrokenRule]:
    """The rule instances broken in state ``after`` that were not in ``before``."""
    return newly_broken(broken_rules(before), broken_rules(after))


def move_toast_lines(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """What the transient toast after a hand move says: the banner's own line
    for each rule instance the move newly broke, except minimums, which dip
    routinely mid-edit and show only in the banner and the grid marks."""
    return [b.line for b in newly_broken_rules(before, after) if toasts(b)]


def broken_rule_marks(broken: list[BrokenRule]) -> dict[str, list[dict]]:
    """What the grid marks for these Broken rules: ``cells`` are ``{building,
    room, role, line}`` (a ``None`` role marks the whole Room), ``helpers`` are
    ``{helper_id, line}`` chips."""
    return {
        "cells": [
            {"building": b, "room": r, "role": role, "line": rule.line}
            for rule in broken
            for b, r, role in rule.cells
        ],
        "helpers": [{"helper_id": hid, "line": rule.line} for rule in broken for hid in rule.helper_ids],
    }


def set_lock(workspace: Workspace, helper_id: int, locked: bool) -> dict:
    """Lock or unlock a placed Helper's whole Assignment. Only placed Helpers
    are lockable; a lock never blocks anything and does not affect the
    Broken-rule check."""
    state = workspace.load()
    for assignment in state["assignments"]:
        if assignment["helper_id"] == helper_id:
            if locked:
                assignment["locked"] = True
            else:
                assignment.pop("locked", None)
            workspace.save(state)
            return state
    raise RosteringError(f"Helper {helper_id} is not placed, so there is nothing to lock.")


def lock_all_placed(workspace: Workspace) -> dict:
    """Lock every placed Helper's Assignment (a no-op with nothing placed)."""
    state = workspace.load()
    for assignment in state["assignments"]:
        assignment["locked"] = True
    workspace.save(state)
    return state


def clear_all_locks(workspace: Workspace) -> dict:
    """Unlock every Assignment; the Assignments themselves stay."""
    state = workspace.load()
    for assignment in state["assignments"]:
        assignment.pop("locked", None)
    workspace.save(state)
    return state


def move_helper(workspace: Workspace, helper_id: int, building: str, room: str, role: str) -> dict:
    state = workspace.load()
    known_ids = {h["id"] for h in state["helpers"]}
    if helper_id not in known_ids:
        raise RosteringError(f"No such helper: {helper_id}")
    if any(h["id"] == helper_id and h.get("cant_attend") for h in state["helpers"]):
        raise RosteringError(f"Helper {helper_id} is marked Can't attend, so they can't be placed.")
    helper_name = next(h["name"] for h in state["helpers"] if h["id"] == helper_id)

    previous = next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)
    assignments = [a for a in state["assignments"] if a["helper_id"] != helper_id]
    moved = {"helper_id": helper_id, "helper_name": helper_name, "building": building, "room": room, "role": role}
    if previous is not None and previous.get("locked"):
        moved["locked"] = True  # a lock moves with its Helper
    assignments.append(moved)
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
    reasons = stale_reasons(state)
    if reasons:
        raise RosteringError("The roster is out of date: " + "; ".join(reasons) + ". Solve again before exporting.")

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
