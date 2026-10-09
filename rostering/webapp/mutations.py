"""State-mutation functions for the web app.

Each function takes the workspace plus whatever the UI just did, mutates the
JSON-shaped workspace state, persists it, and returns the new state dict. Kept
free of any UI import (the NiceGUI screens live in ``rostering.webapp.ui``) so
it can be unit-tested directly and reused unchanged by any caller.
"""
from __future__ import annotations

import functools
import re
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

from rostering.czech import plural
from rostering.domain import (
    TSHIRT_SIZES,
    UNKNOWN_TSHIRT_SIZE,
    Assignment,
    BrokenRule,
    Competition,
    Helper,
    ManualRoles,
    OrganizerRef,
    OverlayRole,
    Preference,
    Role,
    SolveResult,
    StructuralRole,
    group_adjacent_rooms,
    normalize_email,
    normalize_name,
    parse_tshirt_size,
)
from rostering.export.excel import write_roster
from rostering.ingest.preferences import parse_role_token
from rostering.ingest.organizer_survey import ANSWER_FIELDS as ORGANIZER_ANSWER_FIELDS
from rostering.ingest.organizer_survey import OrganizerRow, parse_organizer_survey
from rostering.ingest.raw_survey import (
    build_friend_index,
    parse_raw_survey,
    read_submission_timestamps,
    resolve_friend_names,
)
from rostering.persistence import config_store
from rostering.persistence.season_label import display_label, guess_label, label_sort_key, school_years_crossed
from rostering.persistence.serialize import (
    assignment_from_dict,
    assignment_to_dict,
    config_from_list,
    friend_ref_from_json,
    friend_ref_to_json,
    helper_from_dict,
    helper_to_dict,
    manual_roles_from_dict,
    manual_roles_to_dict,
    organizer_from_dict,
    solver_config_from_dict,
    solver_config_to_dict,
)
from rostering.persistence.workspace import SeasonError, Workspace
from rostering.persons import build_persons, link_persons, new_person_id, uncertain_candidates
from rostering.solver.checker import check_roster, newly_broken, toasts
from rostering.solver.model import NoRosterFound, solve_competition
from rostering.solver.scoring import build_friend_pairs
from rostering import forced_friends
from rostering import organizers as organizer_slots
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
    organizers = [organizer_from_dict(o) for o in state.get("organizers", [])]
    return Competition(
        buildings=buildings,
        helpers=helpers,
        tags=_tag_definitions(state),
        organizers=organizers,
        forced_groups=forced_friends.groups_from_state(state),
    )


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
            "Váš dosavadní uložený stav potřebuje označení ročníku (rok a jaro nebo podzim, např. 2026-jaro).",
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
    # A Helper may name one of the Season's Organizers as a friend, so they are
    # candidates when the free-text friend names are resolved.
    organizers = [organizer_from_dict(o) for o in workspace.load().get("organizers", [])]
    tmp_path = _write_temp(file_bytes, filename)
    try:
        result = parse_raw_survey(tmp_path, organizers=organizers)
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    creating = workspace.open_season() is None
    if creating:
        label = (label or "").strip() or guess_label(result.submission_timestamps)
        if not label:
            raise SeasonLabelRequired(
                "Data odeslání v tomto exportu se nepodařilo přečíst — zadejte označení ročníku "
                "(rok a jaro nebo podzim, např. 2026-jaro)."
            )

    state = workspace.load()
    # A Season about to be created starts blank whatever a draft held; an open
    # Season with no Helpers has nothing to refresh either, so every row is new.
    existing = [] if creating else list(state["helpers"])
    state["helpers"] = list(existing)  # the same records; new registrants are appended to this list only
    if creating:
        state.pop("next_helper_id", None)
    _merge_survey_rows(state, result.helpers, workspace.person_records(), existing)
    state["ingestion_warnings"] = result.warnings
    state["export_timestamps"] = [t.date().isoformat() for t in result.submission_timestamps]
    if not existing:
        state["assignments"] = []
        state["diagnostics"] = {
            "status": None,
            "objective_value": None,
            "unsatisfied_friend_pairs": [],
            "satisfied_friend_pairs": [],
        }
    elif state["assignments"]:
        # Nobody moved, but friend names may now resolve to other Helpers.
        _refresh_friend_pairs(state)
    if creating:
        workspace.create_season(label, state)
    else:
        workspace.save(state)
    return workspace.load()


# What a re-upload refreshes on a recognized Helper straight from the latest
# row. Everything else on the record (Tags, Can't attend, links, hand-added
# markers, ...) is hand-made state and never touched.
_SURVEY_FIELDS = (
    "name",
    "role_preferences",
    "building_preferences",
    "can_bring_notebook",
    "can_bring_camera",
    "email",
    "phone",
    "survey_responses",
)
# The answers whose change matters for a placed Helper, in the order the
# summary and the marker list them.
_MATERIAL_ANSWERS = ("Building preference", "Preferences", "Equipment")


def _material_answers(record: dict) -> dict[str, Any]:
    """The answers whose change matters for a placed Helper (Building set,
    Preferences, equipment), in a comparable form. A blank Preference counts as
    Nevadí, so an answer that only spells that out is no change."""
    preferences = record.get("role_preferences") or {}
    return {
        "Building preference": frozenset(record.get("building_preferences") or []),
        "Preferences": {role.name: preferences.get(role.name, Preference.Nevadi.name) for role in Role},
        "Equipment": (bool(record.get("can_bring_notebook")), bool(record.get("can_bring_camera"))),
    }


def _recognize_rows(rows: list[Helper], existing: list[dict], known: list) -> tuple[list[Optional[dict]], list[str]]:
    """Recognize each parsed row against the Season's loaded Helpers: the
    existing record it is the same Person as (an identical normalized e-mail, or
    a Person an earlier Season recorded under that e-mail), else ``None`` for a
    new registrant. Also returns each row's ``person_id`` (the same recognition
    routine as a first upload). A name-only match is never recognized here: the
    row stays a new registrant and the review list proposes the link."""
    by_email: dict[str, dict] = {}
    by_person: dict[str, dict] = {}
    for record in sorted(existing, key=lambda h: h["id"]):
        email = normalize_email(record.get("email"))
        if email:
            by_email.setdefault(email, record)
        if record.get("person_id"):
            by_person.setdefault(record["person_id"], record)
    person_ids = link_persons([row.email for row in rows], known)
    claimed: set[int] = set()
    matches: list[Optional[dict]] = []
    for row, person_id in zip(rows, person_ids):
        record = by_email.get(row.email) if row.email else None
        if record is None:
            record = by_person.get(person_id)
        if record is not None and record["id"] in claimed:
            record = None  # one Helper never takes two rows
        if record is not None:
            claimed.add(record["id"])
        matches.append(record)
    return matches, person_ids


def _decision_ids(raw: Any) -> list[int]:
    """The friend references of one ``friend_name_decisions`` value (a Helper id
    or ``{"organizer_id": n}``; older states stored a single int; a dismissed
    name has none)."""
    return _decision_refs(raw)


def _refresh_from_survey(record: dict, fresh: dict) -> None:
    """Replace a recognized Helper's survey-derived fields from the latest row
    (``fresh`` is that row as a record on the Helper's real ids), except any
    field typed by hand. A friend name the user resolved by hand keeps its
    resolution while the same free-text name is still in the row; a changed or
    removed name loses it. A T-shirt size set by hand survives while the
    survey answer for it is unchanged."""
    unresolved = fresh["friend_name_order"]
    typed = set(record.get("hand_typed") or [])
    for field in _SURVEY_FIELDS:
        if field in typed:
            continue
        if field in fresh:
            record[field] = fresh[field]
        else:  # an optional key the serializer leaves out when empty
            record.pop(field, None)

    if "tshirt_size" not in typed:
        baseline = record.get("survey_tshirt_size")
        hand_set = baseline is not None and record.get("tshirt_size") != baseline
        if not (hand_set and fresh["tshirt_size"] == baseline):
            record["tshirt_size"] = fresh["tshirt_size"]
    record["survey_tshirt_size"] = fresh["tshirt_size"]

    decisions = record.get("friend_name_decisions") or {}
    kept = {name: decisions[name] for name in unresolved if name in decisions}
    if "friends" not in typed:
        friends = list(fresh["friends"])
        present = {_friend_key(ref) for ref in friends}
        for raw in kept.values():
            for ref in _decision_ids(raw):
                if ref == record["id"] or _friend_key(ref) in present:
                    continue
                present.add(_friend_key(ref))
                friends.append(ref)
        record["friends"] = friends
    record["unresolved_friend_names"] = [n for n in unresolved if n not in kept]
    record["friend_name_order"] = list(unresolved)
    if kept:
        record["friend_name_decisions"] = kept
    else:
        record.pop("friend_name_decisions", None)


def _merge_survey_rows(state: dict[str, Any], rows: list[Helper], known: list, existing: list[dict]) -> None:
    """Load the parsed survey rows into ``state["helpers"]`` (which holds
    ``existing``): a recognized Helper is updated in place and keeps their id, a
    new registrant gets a fresh never-reused id (and no Assignment), and a
    Helper missing from the export is kept untouched. On a re-upload (there were
    Helpers before) the effect is recorded as the persistent upload summary, and
    a placed Helper whose Building set, Preferences or equipment changed gets an
    "answers changed since placed" marker, without moving anyone."""
    matches, person_ids = _recognize_rows(rows, existing, known)
    id_map = {row.id: (record["id"] if record else _next_helper_id(state)) for row, record in zip(rows, matches)}
    placed = {a["helper_id"] for a in state["assignments"]}

    new_entries: list[dict] = []
    changed_entries: list[dict] = []
    for row, record, person_id in zip(rows, matches, person_ids):
        helper_id = id_map[row.id]
        # An Organizer reference names the Season's own Organizer and keeps its id.
        friends = [
            f if isinstance(f, OrganizerRef) else id_map[f]
            for f in row.friends
            if isinstance(f, OrganizerRef) or (f in id_map and id_map[f] != helper_id)
        ]
        fresh = helper_to_dict(replace(row, id=helper_id, person_id=person_id, friends=friends))
        fresh["friend_name_order"] = list(row.unresolved_friend_names)
        fresh["survey_tshirt_size"] = row.tshirt_size
        if record is None:
            state["helpers"].append(fresh)
            new_entries.append({"helper_id": helper_id, "name": fresh["name"]})
            continue
        before = _material_answers(record)
        _refresh_from_survey(record, fresh)
        for assignment in state["assignments"]:
            if assignment["helper_id"] == helper_id:
                assignment["helper_name"] = record["name"]
        if helper_id not in placed:
            continue
        after = _material_answers(record)
        fields = [label for label in _MATERIAL_ANSWERS if before[label] != after[label]]
        if fields:
            already = record.get("answers_changed", [])
            record["answers_changed"] = [label for label in _MATERIAL_ANSWERS if label in fields or label in already]
            changed_entries.append({"helper_id": helper_id, "name": record["name"], "fields": fields})

    if not existing:
        return  # the first load of a Season is not a re-upload: nothing to summarize
    recognized = {record["id"] for record in matches if record is not None}
    missing = [
        {"helper_id": h["id"], "name": h["name"]}
        for h in existing
        if h["id"] not in recognized and not h.get("hand_added")
    ]
    _store_upload_summary(state, new_entries, changed_entries, missing)


def _store_upload_summary(state: dict[str, Any], new: list[dict], changed: list[dict], missing: list[dict]) -> None:
    """Keep what a re-upload did until the user dismisses it. A summary nobody
    has dismissed yet accumulates the new registrants and changed answers of
    later uploads (so nothing unread is lost), while the Helpers missing from
    the export are always those of the latest one."""
    live = {h["id"] for h in state["helpers"]}
    old = state.get("upload_summary") or {}
    new_ids = {e["helper_id"] for e in new}
    all_new = [e for e in old.get("new", []) if e["helper_id"] in live and e["helper_id"] not in new_ids] + new
    changed_by_id = {e["helper_id"]: dict(e) for e in old.get("changed", []) if e["helper_id"] in live}
    for entry in changed:
        earlier = changed_by_id.get(entry["helper_id"], {}).get("fields", [])
        merged = [label for label in _MATERIAL_ANSWERS if label in entry["fields"] or label in earlier]
        changed_by_id[entry["helper_id"]] = {**entry, "fields": merged}
    all_changed = list(changed_by_id.values())
    if all_new or all_changed or missing:
        state["upload_summary"] = {"new": all_new, "changed": all_changed, "missing": missing}
    else:
        state.pop("upload_summary", None)


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
    ``email``, ``phone`` — the phone only a hint), most recent first, and
    ``merges_into``: the id of the Helper added by hand in this Season that
    confirming the candidate merges the entry's Helper into (None for an
    ordinary link). Empty with no Season open."""
    season = workspace.open_season()
    if season is None:
        return []
    proposals = uncertain_candidates(workspace.person_records(), season["id"])
    state = workspace.load()
    entries = []
    for helper in state["helpers"]:
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
                        "merges_into": _merge_target_id(state, helper, c.person_id),
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
            if (r.season_id, r.kind, r.helper_id) != (season["id"], "helper", helper["id"])
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
        raise RosteringError(f"Takový pomocník neexistuje: {helper_id}")
    return helper


def _known_person(workspace: Workspace, person_id: str) -> None:
    if person_id not in {r.person_id for r in workspace.person_records()}:
        raise RosteringError("Taková osoba neexistuje.")


def _hand_added_merge_target(state: dict[str, Any], helper: dict, person_id: str) -> Optional[dict]:
    """The Helper added by hand in this Season that confirming ``helper``'s link
    to ``person_id`` merges them into: a survey-derived Helper who is the same
    Person as a hand-added one. None for any other link (a hand-added Helper is
    never the one absorbed)."""
    if helper.get("hand_added"):
        return None
    return next(
        (h for h in state["helpers"] if h is not helper and h.get("hand_added") and h.get("person_id") == person_id),
        None,
    )


def _merge_target_id(state: dict[str, Any], helper: dict, person_id: str) -> Optional[int]:
    target = _hand_added_merge_target(state, helper, person_id)
    return None if target is None else target["id"]


def _merge_into_hand_added(workspace: Workspace, state: dict[str, Any], absorbed: dict, target: dict) -> None:
    """Fold a survey-derived Helper record into the hand-added Helper it turned
    out to be. ``target`` keeps their id, Assignment (and lock), Tags, Manual
    roles and flags; the survey answers fill every field they left at its
    default, while a value typed by hand wins. ``absorbed`` disappears, and
    everything that pointed at it (Friend preferences, Manual role entries)
    points at ``target``; anything the row was given meanwhile (an Assignment
    when ``target`` has none, Tags) is carried over."""
    target_id, absorbed_id = target["id"], absorbed["id"]
    absorbed_typed = [f for f in absorbed.get("hand_typed") or [] if f not in (target.get("hand_typed") or [])]

    order = absorbed.get("friend_name_order")
    if order is None:
        order = [*absorbed.get("unresolved_friend_names", []), *(absorbed.get("friend_name_decisions") or {})]
    fresh = {
        **absorbed,
        "friends": [f for f in absorbed.get("friends", []) if f != target_id],
        "friend_name_order": order,
    }
    if absorbed.get("friend_name_decisions"):
        target["friend_name_decisions"] = {**(target.get("friend_name_decisions") or {}), **absorbed["friend_name_decisions"]}
    _refresh_from_survey(target, fresh)
    target["survey_tshirt_size"] = absorbed.get("survey_tshirt_size")
    _mark_hand_typed(target, absorbed_typed)  # what the row's own hand edits set stays typed by hand

    # Who they are: the Person the survey row already belonged to (e.g. by
    # e-mail from an earlier Season) wins over a fresh hand-added one.
    season = workspace.open_season()
    settled_elsewhere = {
        r.person_id
        for r in workspace.person_records()
        if (r.season_id, r.helper_id) not in {(season["id"], absorbed_id), (season["id"], target_id)}
    }
    if target.get("person_id") not in settled_elsewhere and absorbed.get("person_id") in settled_elsewhere:
        target["person_id"] = absorbed["person_id"]
    target["link_confirmed"] = True
    rejected = [
        p for p in dict.fromkeys([*(target.get("rejected_person_ids") or []), *(absorbed.get("rejected_person_ids") or [])])
        if p != target["person_id"]
    ]
    if rejected:
        target["rejected_person_ids"] = rejected
    else:
        target.pop("rejected_person_ids", None)

    direct_tags = [*(target.get("tags") or []), *(t for t in absorbed.get("tags") or [] if t not in (target.get("tags") or []))]
    if direct_tags:
        target["tags"] = direct_tags

    placed = {a["helper_id"] for a in state["assignments"]}
    if absorbed_id in placed and target_id not in placed:
        for assignment in state["assignments"]:
            if assignment["helper_id"] == absorbed_id:
                assignment["helper_id"] = target_id
                assignment["helper_name"] = target["name"]
    else:
        state["assignments"] = [a for a in state["assignments"] if a["helper_id"] != absorbed_id]

    for group in state["manual_roles"].values():
        for entry in group:
            if entry.get("helper_id") == absorbed_id:
                entry["helper_id"] = target_id

    state["helpers"] = [h for h in state["helpers"] if h["id"] != absorbed_id]
    for other in state["helpers"]:
        other["friends"] = list(dict.fromkeys(target_id if f == absorbed_id else f for f in other.get("friends", [])))
        if other["id"] == target_id:
            other["friends"] = [f for f in other["friends"] if f != target_id]
        decisions = other.get("friend_name_decisions") or {}
        for friend_name, raw in list(decisions.items()):
            ids = _decision_ids(raw)
            if absorbed_id in ids:
                decisions[friend_name] = list(dict.fromkeys(target_id if i == absorbed_id else i for i in ids))

    summary = state.get("upload_summary")
    if summary:
        for key in ("new", "changed", "missing"):
            summary[key] = [e for e in summary.get(key, []) if e["helper_id"] != absorbed_id]
        if not any(summary.get(key) for key in ("new", "changed", "missing")):
            state.pop("upload_summary")
    if state["assignments"]:
        _refresh_friend_pairs(state)


def link_helper(workspace: Workspace, helper_id: int, person_id: str) -> dict:
    """Link a Helper of the open Season to a Person the stored Seasons know:
    confirms a proposed candidate, or links by hand to any Person (a returner
    who changed both e-mail and name form). Changes only this Helper's Person
    link — never a Helper id — and settles the Helper, so their other
    candidates are no longer proposed. Remembered on the Helper record
    independently of e-mail.

    When the Person is a Helper the organizer added by hand in this Season, the
    link is a merge instead: the survey-derived Helper is folded into the
    hand-added one, who keeps their id, Assignment, lock, Tags, Manual roles and
    flags (see :func:`_merge_into_hand_added`), so no duplicate is left."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    _known_person(workspace, person_id)
    if helper.get("person_id") == person_id:
        raise RosteringError(f"{helper['name']} je už s touto osobou propojen(a).")
    target = _hand_added_merge_target(state, helper, person_id)
    if target is not None:
        _merge_into_hand_added(workspace, state, helper, target)
        workspace.save(state)
        return state
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
        raise RosteringError(f"{helper['name']} je s touto osobou propojen(a) — místo toho zrušte propojení.")
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
        r.person_id == old_person and (r.season_id, r.kind, r.helper_id) != (season["id"], "helper", helper_id)
        for r in workspace.person_records()
    )
    if not shared and not helper.get("link_confirmed"):
        raise RosteringError(f"{helper['name']} není propojen(a) s žádným jiným záznamem.")
    helper["person_id"] = new_person_id()
    helper.pop("link_confirmed", None)
    rejected = helper.setdefault("rejected_person_ids", [])
    if old_person and old_person not in rejected:
        rejected.append(old_person)
    workspace.save(state)
    return state


def get_uncertain_organizer_matches(workspace: Workspace) -> list[dict]:
    """The review list of the open Season's Organizers, like
    :func:`get_uncertain_matches` for Helpers: an Organizer created by hand
    without an e-mail is only ever an uncertain name match, proposed here with the
    Persons (Helpers or Organizers of other Seasons) that share their normalized
    name and never linked until :func:`link_organizer` confirms it. An entry is
    ``organizer_id``, ``organizer_name``, ``organizer_email`` and ``candidates``
    (``person_id``, ``name``, ``season``, ``email``, ``phone``), most recent
    first. Empty with no Season open."""
    season = workspace.open_season()
    if season is None:
        return []
    proposals = uncertain_candidates(workspace.person_records(), season["id"], kind="organizer")
    entries = []
    for organizer in workspace.load()["organizers"]:
        candidates = proposals.get(organizer["id"])
        if not candidates:
            continue
        entries.append(
            {
                "organizer_id": organizer["id"],
                "organizer_name": organizer["name"],
                "organizer_email": organizer.get("email"),
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
    return sorted(entries, key=lambda e: e["organizer_id"])


def link_organizer(workspace: Workspace, organizer_id: int, person_id: str) -> dict:
    """Link an Organizer of the open Season to a Person the stored Seasons know
    (:func:`link_helper` for an Organizer): changes only their Person link,
    settles them, and is remembered independently of e-mail."""
    state = workspace.load()
    organizer = _organizer_record(state, organizer_id)
    _known_person(workspace, person_id)
    if organizer.get("person_id") == person_id:
        raise RosteringError(f"{organizer['name']} je už s touto osobou propojen(a).")
    organizer["person_id"] = person_id
    organizer["link_confirmed"] = True
    remaining = [p for p in organizer.get("rejected_person_ids", []) if p != person_id]
    if remaining:
        organizer["rejected_person_ids"] = remaining
    else:
        organizer.pop("rejected_person_ids", None)
    workspace.save(state)
    return state


def reject_organizer_match(workspace: Workspace, organizer_id: int, person_id: str) -> dict:
    """"Not the same person" for an Organizer: the pairing is never proposed
    again, from either side."""
    state = workspace.load()
    organizer = _organizer_record(state, organizer_id)
    _known_person(workspace, person_id)
    if organizer.get("person_id") == person_id:
        raise RosteringError(f"{organizer['name']} je s touto osobou propojen(a) — místo toho zrušte propojení.")
    rejected = organizer.setdefault("rejected_person_ids", [])
    if person_id not in rejected:
        rejected.append(person_id)
    workspace.save(state)
    return state


def unlink_organizer(workspace: Workspace, organizer_id: int) -> dict:
    """Undo an Organizer's Person link (:func:`unlink_helper` for an
    Organizer): they become a Person of their own again, and the Person they were
    unlinked from is remembered as rejected."""
    state = workspace.load()
    organizer = _organizer_record(state, organizer_id)
    season = workspace.open_season()
    old_person = organizer.get("person_id")
    shared = any(
        r.person_id == old_person and (r.season_id, r.kind, r.helper_id) != (season["id"], "organizer", organizer_id)
        for r in workspace.person_records()
    )
    if not shared and not organizer.get("link_confirmed"):
        raise RosteringError(f"{organizer['name']} není propojen(a) s žádným jiným záznamem.")
    organizer["person_id"] = new_person_id()
    organizer.pop("link_confirmed", None)
    rejected = organizer.setdefault("rejected_person_ids", [])
    if old_person and old_person not in rejected:
        rejected.append(old_person)
    workspace.save(state)
    return state


def _friend_key(ref: Any) -> tuple[str, int]:
    """A hashable, comparable form of a saved friend reference (a Helper's plain
    id, or ``{"organizer_id": n}``)."""
    saved = friend_ref_to_json(friend_ref_from_json(ref))
    return ("organizer", saved["organizer_id"]) if isinstance(saved, dict) else ("helper", saved)


def attending_friend_count(state: dict[str, Any], helper: dict[str, Any]) -> int:
    """How many of a Helper's matched friends are attending: a friend flagged
    Can't attend (Helper or Organizer) does not count."""
    absent = {("helper", h["id"]) for h in state["helpers"] if h.get("cant_attend")}
    absent |= {("organizer", o["id"]) for o in state.get("organizers", []) if o.get("cant_attend")}
    return sum(1 for ref in helper["friends"] if _friend_key(ref) not in absent)


def _decision_refs(raw: Any) -> list[Any]:
    """The friend references a saved ``friend_name_decisions`` value holds
    (nothing for a dismissed name). Older persisted state stored a single int
    per name instead of a list."""
    if raw is None:
        return []
    if isinstance(raw, (int, dict)):
        return [raw]
    return list(raw)


def resolve_friend(
    workspace: Workspace,
    helper_id: int,
    name: str,
    action: str,
    resolved_helper_ids: Optional[list[int]] = None,
    resolved_organizer_ids: Optional[list[int]] = None,
) -> dict:
    """Resolve (or dismiss) one unresolved friend name for a helper. ``reset``
    takes a decision back, so the name is unresolved again.

    A single free-text name can refer to more than one person (e.g. a
    group nickname), so ``resolved_helper_ids`` is a list — the name is
    matched to every helper id in it — and ``resolved_organizer_ids`` likewise
    names the Organizers it refers to.
    """
    state = workspace.load()
    helper = next((h for h in state["helpers"] if h["id"] == helper_id), None)
    if helper is None:
        raise RosteringError(f"Takový pomocník neexistuje: {helper_id}")
    decisions = helper.setdefault("friend_name_decisions", {})
    if name not in helper["unresolved_friend_names"] and name not in decisions:
        raise RosteringError(f"{name!r} není známé jméno kamaráda pomocníka {helper_id}")

    previous = {_friend_key(ref) for ref in _decision_refs(decisions.get(name))}
    helper["friends"] = [f for f in helper["friends"] if _friend_key(f) not in previous]

    if action == "resolve":
        if not resolved_helper_ids and not resolved_organizer_ids:
            raise RosteringError("resolved_helper_ids is required for action=resolve")
        known_ids = {h["id"] for h in state["helpers"]}
        unknown_ids = [hid for hid in resolved_helper_ids or [] if hid not in known_ids]
        if unknown_ids:
            raise RosteringError(f"Takoví pomocníci neexistují: {unknown_ids}")
        known_organizers = {o["id"] for o in state["organizers"]}
        unknown_organizers = [oid for oid in resolved_organizer_ids or [] if oid not in known_organizers]
        if unknown_organizers:
            raise RosteringError(f"Takoví organizátoři neexistují: {unknown_organizers}")
        new_refs: list[Any] = list(dict.fromkeys(resolved_helper_ids or []))
        new_refs += [{"organizer_id": oid} for oid in dict.fromkeys(resolved_organizer_ids or [])]
        present = {_friend_key(f) for f in helper["friends"]}
        for ref in new_refs:
            if _friend_key(ref) not in present:
                helper["friends"].append(ref)
        decisions[name] = new_refs
    elif action == "dismiss":
        decisions[name] = None
    elif action == "reset":
        decisions.pop(name, None)
        if name not in helper["unresolved_friend_names"]:
            helper["unresolved_friend_names"].append(name)
        workspace.save(state)
        return state
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


def unplaced_helpers(state: dict[str, Any]) -> list[dict]:
    """The Helper records taking part who hold no Assignment on a roster that
    exists (new registrants of a re-upload, a Helper added by hand, someone
    un-flagged from Can't attend). Empty before the first solve or placement,
    when there is no roster to be incomplete."""
    if not state["assignments"]:
        return []
    placed = {a["helper_id"] for a in state["assignments"]}
    return [h for h in state["helpers"] if not h.get("cant_attend") and h["id"] not in placed]


def unplaced_reason(state: dict[str, Any]) -> Optional[str]:
    """The line naming the registrants still unassigned (e.g. "Zatím nezařazení
    zájemci (2): Klára, Eva"), or None when everyone is placed."""
    unplaced = unplaced_helpers(state)
    if not unplaced:
        return None
    names = ", ".join(h["name"] for h in unplaced[:5]) + (f" a dalších {len(unplaced) - 5}" if len(unplaced) > 5 else "")
    return f"Zatím nezařazení zájemci ({len(unplaced)}): {names}"


def export_blockers(state: dict[str, Any]) -> list[str]:
    """Why Export is blocked right now, one line each: the stale-roster reasons,
    plus every registrant still unassigned (which lifts by itself as they are
    placed, by hand or by a Solve, unlike the stale flag that only a full Solve
    clears)."""
    unplaced = unplaced_reason(state)
    return stale_reasons(state) + ([unplaced] if unplaced else [])


def answers_changed_since_placed(state: dict[str, Any]) -> dict[int, list[str]]:
    """The placed Helpers whose re-submitted answers changed materially since
    they were placed: Helper id -> the changed fields (``Building preference``,
    ``Preferences``, ``Equipment``). The marker stays until the Helper is moved,
    locked or re-placed by a full Solve, or loses their Assignment; dismissing
    the upload summary leaves it."""
    placed = {a["helper_id"] for a in state["assignments"]}
    return {h["id"]: list(h["answers_changed"]) for h in state["helpers"] if h.get("answers_changed") and h["id"] in placed}


def upload_summary(workspace: Workspace) -> Optional[dict]:
    """What the latest re-upload(s) did to the open Season, kept until
    :func:`dismiss_upload_summary` (None when there is none): ``new`` registrants
    (unassigned), ``changed`` answers of placed Helpers (with the fields),
    Helpers ``missing`` from the export (kept), and, live, the ``uncertain``
    matches still awaiting review (:func:`get_uncertain_matches` entries)."""
    stored = workspace.load().get("upload_summary")
    if not stored:
        return None
    return {**stored, "uncertain": get_uncertain_matches(workspace)}


def _clear_answers_changed(state: dict[str, Any], helper_ids: Optional[set[int]] = None) -> None:
    """Drop the "answers changed since placed" marker of these Helpers (all of
    them when ``helper_ids`` is None): they were just moved, locked or re-placed."""
    for helper in state["helpers"]:
        if helper_ids is None or helper["id"] in helper_ids:
            helper.pop("answers_changed", None)


def dismiss_upload_summary(workspace: Workspace) -> dict:
    """Dismiss the upload summary. Only the summary goes: markers on Helpers and
    the Export gate are unaffected."""
    state = workspace.load()
    state.pop("upload_summary", None)
    workspace.save(state)
    return state


def _typed_role_entries(state: dict[str, Any]) -> list[tuple[str, dict]]:
    """The Manual role entries that name someone by hand-typed text (no Helper
    reference), as ``(group, entry)``."""
    return [
        (group, entry)
        for group in ("structural", "overlay")
        for entry in state["manual_roles"][group]
        if entry.get("helper_id") is None and (entry.get("helper_name") or "").strip()
    ]


def get_typed_role_link_offers(workspace: Workspace) -> list[dict]:
    """The typed Manual role names of the open Season that now match a Helper:
    a name someone typed for an unregistered person that a registered, attending
    Helper of the same normalized name has since matched (a newly recognized
    Helper from a re-upload, or one added by hand). One offer per typed name
    (``name`` as typed, the ``slots`` holding it as display labels) with its
    ``candidates`` (``helper_id``, ``name``, ``email``, ``phone``), the pairings
    the user declined left out. Nothing is linked until
    :func:`link_typed_role_name` confirms it."""
    if workspace.open_season() is None:
        return []
    state = workspace.load()
    declined = {(d["name"], d["helper_id"]) for d in state.get("declined_typed_role_links") or []}
    offers: dict[str, dict] = {}
    for _group, entry in _typed_role_entries(state):
        key = normalize_name(entry["helper_name"])
        offer = offers.setdefault(key, {"name": entry["helper_name"], "slots": [], "candidates": []})
        offer["slots"].append(_manual_entry_label(entry))
    for key, offer in offers.items():
        offer["candidates"] = [
            {"helper_id": h["id"], "name": h["name"], "email": h.get("email"), "phone": h.get("phone")}
            for h in state["helpers"]
            if not h.get("cant_attend") and normalize_name(h["name"]) == key and (key, h["id"]) not in declined
        ]
    return sorted((o for o in offers.values() if o["candidates"]), key=lambda o: normalize_name(o["name"]))


def link_typed_role_name(workspace: Workspace, name: str, helper_id: int) -> dict:
    """Confirm a typed Manual role name as a Helper: every entry holding that
    text (matched ignoring case, diacritics and spacing) becomes a real
    reference to the Helper, in every slot it sits in (an entry whose slot the
    Helper already holds is just dropped). Refused for a Helper the name doesn't
    match, or who can't attend."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    key = normalize_name(name)
    if helper.get("cant_attend") or normalize_name(helper["name"]) != key:
        raise RosteringError(f"{helper['name']} neodpovídá napsanému jménu {name!r}.")
    typed = [entry for _group, entry in _typed_role_entries(state) if normalize_name(entry["helper_name"]) == key]
    if not typed:
        raise RosteringError(f"Žádný záznam manuální role neuvádí {name!r} textem.")
    for group in ("structural", "overlay"):
        held = {
            (e["role"], e.get("building"), e.get("room"))
            for e in state["manual_roles"][group]
            if e.get("helper_id") == helper_id
        }
        kept = []
        for entry in state["manual_roles"][group]:
            if any(entry is t for t in typed):
                slot = (entry["role"], entry.get("building"), entry.get("room"))
                if slot in held:
                    continue  # the Helper already holds this slot
                held.add(slot)
                entry["helper_id"], entry["helper_name"] = helper_id, None
            kept.append(entry)
        state["manual_roles"][group] = kept
    workspace.save(state)
    return state


def decline_typed_role_link(workspace: Workspace, name: str, helper_id: int) -> dict:
    """"Not the same person" for a typed Manual role name: the text stays as
    typed and this name is never offered a link to this Helper again."""
    state = workspace.load()
    _helper_record(state, helper_id)
    declined = state.setdefault("declined_typed_role_links", [])
    pair = {"name": normalize_name(name), "helper_id": helper_id}
    if pair not in declined:
        declined.append(pair)
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
        lines.append(f"Přiřazení: {where}" + (" (uzamčeno)" if placed.get("locked") else ""))
    for group, label in (("structural", "Organizátorská role"), ("overlay", "Manuální role")):
        for entry in state["manual_roles"][group]:
            if entry.get("helper_id") == helper_id:
                lines.append(f"{label}: {_manual_entry_label(entry)}")
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
            f"Označením pomocníka {helper['name']} jako Nemůže se zúčastnit se vymaže: " + "; ".join(impact) + ". "
            "Pozdější zrušení příznaku to neobnoví a rozdělení pomocníků je do dalšího sestavení neaktuální.",
            impact,
        )
    helper["cant_attend"] = True
    if impact:
        state["assignments"] = [a for a in state["assignments"] if a["helper_id"] != helper_id]
        _clear_answers_changed(state, {helper_id})
        satisfied, unsatisfied = _recompute_friend_pairs(state)
        state["diagnostics"]["satisfied_friend_pairs"] = satisfied
        state["diagnostics"]["unsatisfied_friend_pairs"] = unsatisfied
        state["manual_roles"] = {
            group: [e for e in entries if e.get("helper_id") != helper_id]
            for group, entries in state["manual_roles"].items()
        }
        _add_stale_reason(state, f"{helper['name']} se nemůže zúčastnit: vymazáno přiřazení a záznamy rolí")
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
        raise RosteringError(f"Neplatná velikost trička {size!r}; povolené: {allowed}")
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
        raise RosteringError(f"Takový pomocník neexistuje: {helper_id}")
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
            lines.append(f"{other['name']} už je pomocník se stejným jménem.")
        elif email and normalize_email(other.get("email")) == email:
            lines.append(f"{other['name']} už má e-mail {email}.")
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
    friends: Optional[list[Any]] = None,
    tshirt_size: Optional[str] = None,
) -> dict[str, Any]:
    """The fields that were given (``None`` = not given), validated and in
    stored form; raises :class:`RosteringError` for any invalid one."""
    fields: dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise RosteringError("Pomocník musí mít jméno.")
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
                raise RosteringError(f"Neznámá role: {role_name!r}")
            if pref_name not in Preference.__members__:
                allowed = ", ".join(Preference.__members__)
                raise RosteringError(f"Neznámá preference {pref_name!r}; povolené: {allowed}")
            cleaned[role.name] = pref_name
        fields["role_preferences"] = cleaned
    if building_preferences is not None:
        known = [b["name"] for b in state["config"]]
        unknown = [b for b in building_preferences if b not in known]
        if unknown:
            raise RosteringError(f"Neznámé budovy: {', '.join(unknown)}")
        fields["building_preferences"] = sorted(set(building_preferences))
    if can_bring_notebook is not None:
        fields["can_bring_notebook"] = bool(can_bring_notebook)
    if can_bring_camera is not None:
        fields["can_bring_camera"] = bool(can_bring_camera)
    if friends is not None:
        # A friend is a Helper id or an Organizer reference ({"organizer_id": n}).
        refs = [friend_ref_to_json(friend_ref_from_json(f)) for f in friends]
        known_ids = {h["id"] for h in state["helpers"]}
        unknown_ids = [f for f in refs if not isinstance(f, dict) and f not in known_ids]
        if unknown_ids:
            raise RosteringError(f"Takoví pomocníci neexistují: {unknown_ids}")
        known_organizers = {o["id"] for o in state["organizers"]}
        unknown_organizers = [
            f["organizer_id"] for f in refs if isinstance(f, dict) and f["organizer_id"] not in known_organizers
        ]
        if unknown_organizers:
            raise RosteringError(f"Takoví organizátoři neexistují: {unknown_organizers}")
        if helper_id is not None and helper_id in refs:
            raise RosteringError("Pomocník nemůže být sám sobě kamarádem.")
        fields["friends"] = list({_friend_key(f): f for f in refs}.values())
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
    friends: Optional[list[Any]] = None,
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
        raise RosteringError("Pomocník musí mít jméno.")
    if not contact:
        raise RosteringError("Pomocník musí mít kontakt (e-mail nebo telefon).")
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
    friends: Optional[list[Any]] = None,
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


def _forget_as_friend(state: dict[str, Any], ref: Any) -> None:
    """Take a deleted Helper (``ref`` is their id) or Organizer (``ref`` is
    ``{"organizer_id": n}``) out of everyone's Friend preference. A friend name
    that was resolved only to them goes back to unresolved rather than being
    silently dropped."""
    gone = _friend_key(ref)
    for other in state["helpers"]:
        other["friends"] = [f for f in other.get("friends", []) if _friend_key(f) != gone]
        decisions = other.get("friend_name_decisions") or {}
        for friend_name, raw in list(decisions.items()):
            refs = _decision_refs(raw)
            if gone not in {_friend_key(r) for r in refs}:
                continue
            remaining = [r for r in refs if _friend_key(r) != gone]
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
            f"Smazáním pomocníka {helper['name']} se vymaže: " + "; ".join(impact) + ". "
            "Nelze vrátit zpět a rozdělení pomocníků je do dalšího sestavení neaktuální.",
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
        _add_stale_reason(state, f"Pomocník {helper['name']} smazán: vymazáno přiřazení a záznamy rolí")
    if state["assignments"]:
        _refresh_friend_pairs(state)
    workspace.save(state)
    return state


# -- Organizers ------------------------------------------------------------------
#
# An Organizer (see CONTEXT.md and rostering/organizers.py) is a tracked person
# of one Season, saved in ``state["organizers"]``; the four leadership slots hold
# them by id (``organizer_id`` on a ``manual_roles["structural"]`` entry) and
# an Organizer's placement is derived from the slot(s) they hold.


def _organizer_record(state: dict[str, Any], organizer_id: int) -> dict:
    record = next((o for o in state["organizers"] if o["id"] == organizer_id), None)
    if record is None:
        raise RosteringError(f"Takový organizátor neexistuje: {organizer_id}")
    return record


def _next_organizer_id(state: dict[str, Any]) -> int:
    """An Organizer id above every id in use and above every id ever handed out
    or deleted (``next_organizer_id`` is that high-water mark), so an id is
    never reused for another person."""
    new_id = max(
        int(state.get("next_organizer_id") or 1), max((o["id"] for o in state["organizers"]), default=0) + 1
    )
    state["next_organizer_id"] = new_id + 1
    return new_id


def _validated_organizer_email(email: Optional[str]) -> Optional[str]:
    normalized = normalize_email(email)
    if normalized is not None and not _looks_like_email(normalized):
        raise RosteringError(f"Toto není e-mailová adresa: {email!r}")
    return normalized


def _config_rooms(state: dict[str, Any]) -> dict[str, list[str]]:
    return {b["name"]: [r["name"] for r in b["rooms"]] for b in state["config"]}


def _slot_role(role: str) -> StructuralRole:
    try:
        return organizer_slots.parse_slot_role(role)
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc


def _checked_slot(state: dict[str, Any], role: str, building: Optional[str], room: Optional[str]):
    """The slot's role, after refusing (as a structural error) an address that
    does not fit its scope or names a Building/Room the Season lacks."""
    slot = _slot_role(role)
    try:
        organizer_slots.check_slot(slot, building, room or None, _config_rooms(state))
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc
    return slot


def _sync_placements(state: dict[str, Any]) -> None:
    """Re-derive every Organizer's placement from the slot entries: the Building
    (and Room) of the slot they hold, none while they hold no slot. The one place
    a placement is written."""
    entries = state["manual_roles"]["structural"]
    for organizer in state["organizers"]:
        organizer["building"], organizer["room"] = organizer_slots.placement_of(entries, organizer["id"])


def _same_place(entry: dict, building: Optional[str], room: Optional[str]) -> bool:
    return entry.get("building") == building and (entry.get("room") or None) == (room or None)


def _place_organizer(
    state: dict[str, Any], organizer_id: int, slot: StructuralRole, building: str, room: Optional[str]
) -> None:
    """Put an Organizer in a slot cell. They hold exactly one placement, so any
    entry of theirs elsewhere is removed (the placement moves); entries of theirs
    at this same Building/Room in other slots stay. A cell takes any number of
    Organizers; the others already in it stay. An Organizer flagged Can't attend
    holds nothing (like a Helper, they are not on the roster)."""
    record = _organizer_record(state, organizer_id)
    if record.get("cant_attend"):
        raise RosteringError(f"{record['name']} je označen(a) jako Nemůže se zúčastnit: před přidělením místa to zrušte.")
    kept = [
        entry
        for entry in state["manual_roles"]["structural"]
        if not (entry.get("organizer_id") == organizer_id and not _same_place(entry, building, room))
    ]
    if not any(e.get("organizer_id") == organizer_id and e["role"] == slot.name and _same_place(e, building, room) for e in kept):
        kept.append(
            {
                "role": slot.name,
                "building": building,
                "room": room,
                "helper_id": None,
                "helper_name": None,
                "organizer_id": organizer_id,
            }
        )
    state["manual_roles"]["structural"] = kept
    _sync_placements(state)


def _new_organizer(workspace: Workspace, state: dict[str, Any], name: str, email: Optional[str]) -> dict:
    """Append a new Organizer record to ``state`` (not saved): a fresh id, and a
    Person link that is fresh unless the e-mail was recorded in an earlier stored
    Season. Without an e-mail the only match left is the uncertain name match
    :func:`get_uncertain_organizer_matches` proposes."""
    record = {
        "id": _next_organizer_id(state),
        "person_id": _person_id_for_new_email(workspace, email),
        "name": name,
        "email": email,
        "building": None,
        "room": None,
    }
    state["organizers"].append(record)
    return record


def unresolved_friend_count(state: dict[str, Any]) -> int:
    """How many free-text friend names are still unresolved, over all Helpers."""
    return sum(len(h.get("unresolved_friend_names", [])) for h in state["helpers"])


def _retry_unresolved_friends(state: dict[str, Any]) -> int:
    """Match again every friend name still unresolved, against the Season's
    Helpers and Organizers (the survey's own rules: exact full name, unambiguous
    first name, then fuzzy), for when a new Organizer may be who a Helper meant.
    A name that now resolves is recorded as a decision (so it shows as matched in
    the person sheet, can be reset, and goes back to unresolved if that
    Organizer is deleted) and added to the Helper's Friend preference; a name
    that still doesn't, or resolves only to the Helper themself, stays as it
    was. Returns how many names were resolved. Not saved."""
    index = build_friend_index(
        [(h["id"], h["name"]) for h in state["helpers"]]
        + [({"organizer_id": o["id"]}, o["name"]) for o in state["organizers"]]
    )
    resolved_count = 0
    for helper in state["helpers"]:
        decisions = helper.setdefault("friend_name_decisions", {})
        for name in list(helper["unresolved_friend_names"]):
            refs, left = resolve_friend_names(name, *index)
            if left or not refs or any(_friend_key(ref) == _friend_key(helper["id"]) for ref in refs):
                continue
            present = {_friend_key(f) for f in helper["friends"]}
            for ref in refs:
                if _friend_key(ref) not in present:
                    present.add(_friend_key(ref))
                    helper["friends"].append(ref)
            decisions[name] = list(refs)
            helper["unresolved_friend_names"].remove(name)
            resolved_count += 1
        if not decisions:
            helper.pop("friend_name_decisions")
    if resolved_count and state["assignments"]:
        _refresh_friend_pairs(state)
    return resolved_count


def add_organizer(workspace: Workspace, name: str, email: Optional[str] = None) -> dict:
    """Create an Organizer by hand: only ``name`` is required. They get a fresh,
    never-reused Organizer id and a Person link (fresh unless the optional
    ``email`` was recorded in an earlier Season) and have no placement until
    :func:`assign_organizer` puts them in a slot. Friend names no Helper's answers
    could be matched to before are tried again, as the new Organizer may be who
    they meant. The new record is the last of ``state["organizers"]``."""
    name = (name or "").strip()
    if not name:
        raise RosteringError("Organizátor musí mít jméno.")
    email = _validated_organizer_email(email)
    state = workspace.load()
    _new_organizer(workspace, state, name, email)
    _retry_unresolved_friends(state)
    workspace.save(state)
    return state


def _repoint_friend(state: dict[str, Any], old: Any, new: Any) -> None:
    """Point everyone's Friend preference (and the friend-name decisions behind
    it) that names ``old`` at ``new`` instead; both are saved friend references."""
    old_key = _friend_key(old)

    def swapped(refs: list[Any]) -> list[Any]:
        replaced = [new if _friend_key(r) == old_key else r for r in refs]
        return list({_friend_key(r): r for r in replaced}.values())

    for other in state["helpers"]:
        other["friends"] = swapped(other.get("friends", []))
        decisions = other.get("friend_name_decisions") or {}
        for friend_name, raw in decisions.items():
            if old_key in {_friend_key(r) for r in _decision_refs(raw)}:
                decisions[friend_name] = swapped(_decision_refs(raw))


def promote_helper(workspace: Workspace, helper_id: int, confirmed: bool = False) -> dict:
    """Promote a Helper to Organizer (see CONTEXT.md "Organizer").

    The Organizer keeps the Helper's Person link (and the link decisions made
    about it), name, e-mail and direct Tags; it has no placement until
    :func:`assign_organizer` puts it in a slot. The Helper leaves the solver pool
    (their record is removed, and their id, like a deleted Helper's, is never
    handed out again) and every other Helper's Friend preference that named them
    now names the Organizer. Like Can't attend and a delete, a Helper with an
    Assignment or Manual role entries is only promoted once ``confirmed``
    (:class:`ConfirmationRequired` names what would go); confirming clears their
    Assignment and lock and every Manual role entry holding them (Additional
    roles are Helper-only, and a slot takes a tracked Organizer) and raises the
    stale-roster flag. Demotion is not supported. The new Organizer is the last
    of ``state["organizers"]``."""
    state = workspace.load()
    helper = _helper_record(state, helper_id)
    impact = cant_attend_impact(state, helper_id)
    if impact and not confirmed:
        raise ConfirmationRequired(
            f"Povýšením pomocníka {helper['name']} na organizátora se vymaže: " + "; ".join(impact) + ". "
            "Opustí množinu pomocníků, nedostanou žádnou sestavenou roli a rozdělení pomocníků je do dalšího sestavení neaktuální.",
            impact,
        )
    organizer = {
        "id": _next_organizer_id(state),
        "person_id": helper.get("person_id") or new_person_id(),
        "name": helper["name"],
        "email": helper.get("email"),
        "building": None,
        "room": None,
    }
    if helper.get("tags"):
        organizer["tags"] = list(helper["tags"])
    for key in ("link_confirmed", "rejected_person_ids"):
        if helper.get(key):
            organizer[key] = helper[key]
    state["organizers"].append(organizer)

    state["helpers"] = [h for h in state["helpers"] if h["id"] != helper_id]
    state["next_helper_id"] = max(int(state.get("next_helper_id") or 1), helper_id + 1)
    _repoint_friend(state, helper_id, {"organizer_id": organizer["id"]})
    if impact:
        state["assignments"] = [a for a in state["assignments"] if a["helper_id"] != helper_id]
        state["manual_roles"] = {
            group: [e for e in entries if e.get("helper_id") != helper_id]
            for group, entries in state["manual_roles"].items()
        }
        _add_stale_reason(state, f"{helper['name']} se stal(a) organizátorem: vymazáno přiřazení a záznamy rolí")
    if state["assignments"]:
        _refresh_friend_pairs(state)
    workspace.save(state)
    return state


def update_organizer(
    workspace: Workspace,
    organizer_id: int,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    tshirt_size: Optional[str] = None,
) -> dict:
    """Rename an Organizer and/or set or clear (blank) their e-mail or phone, and
    set their T-shirt size (one of ``TSHIRT_SIZES`` or Unknown). Fields left out
    stay as they are; the ones that changed are remembered as typed by hand, so a
    later import of the Organizers' sheet leaves them alone. Entering an e-mail an
    earlier stored Season recorded links them to that Person at once (a confident
    match) unless the user already settled their Person link or they are linked
    by e-mail already; the Organizer id never changes."""
    state = workspace.load()
    record = _organizer_record(state, organizer_id)
    changed: list[str] = []
    if name is not None:
        name = name.strip()
        if not name:
            raise RosteringError("Organizátor musí mít jméno.")
        if name != record["name"]:
            changed.append("name")
        record["name"] = name
    if phone is not None:
        new_phone = phone.strip() or None
        if new_phone != record.get("phone"):
            changed.append("phone")
            if new_phone is None:
                record.pop("phone", None)
            else:
                record["phone"] = new_phone
    if tshirt_size is not None:
        size = parse_tshirt_size(tshirt_size) or UNKNOWN_TSHIRT_SIZE
        if tshirt_size.strip() and tshirt_size != UNKNOWN_TSHIRT_SIZE and size == UNKNOWN_TSHIRT_SIZE:
            raise RosteringError(f"Neznámá velikost trička: {tshirt_size!r}")
        if size != (record.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE):
            changed.append("tshirt_size")
            if size == UNKNOWN_TSHIRT_SIZE:
                record.pop("tshirt_size", None)
            else:
                record["tshirt_size"] = size
    if email is not None:
        new_email = _validated_organizer_email(email)
        if new_email != record.get("email"):
            changed.append("email")
            record["email"] = new_email
            season = workspace.open_season()
            records = workspace.person_records()
            shared = any(
                r.person_id == record["person_id"]
                and (r.season_id, r.kind, r.helper_id) != (season["id"] if season else None, "organizer", organizer_id)
                for r in records
            )
            if new_email and not record.get("link_confirmed") and not shared:
                known = [r for r in records if season is None or r.season_id != season["id"]]
                if any(r.email == new_email for r in known):
                    record["person_id"] = link_persons([new_email], known)[0]
    _mark_hand_typed(record, changed)
    workspace.save(state)
    return state


def _organizer_impact(state: dict[str, Any], organizer_id: int) -> list[str]:
    return [
        f"Organizátorská role: {_manual_entry_label(entry)}"
        for entry in state["manual_roles"]["structural"]
        if entry.get("organizer_id") == organizer_id
    ]


def delete_organizer(workspace: Workspace, organizer_id: int, confirmed: bool = False) -> dict:
    """Delete an Organizer. One holding slots is only deleted once ``confirmed``
    (:class:`ConfirmationRequired` names the slots that would be emptied);
    their id is never handed out again."""
    state = workspace.load()
    record = _organizer_record(state, organizer_id)
    impact = _organizer_impact(state, organizer_id)
    if impact and not confirmed:
        raise ConfirmationRequired(f"Smazáním organizátora {record['name']} se vyprázdní: " + "; ".join(impact) + ".", impact)
    state["organizers"] = [o for o in state["organizers"] if o["id"] != organizer_id]
    state["next_organizer_id"] = max(int(state.get("next_organizer_id") or 1), organizer_id + 1)
    state["manual_roles"]["structural"] = [
        e for e in state["manual_roles"]["structural"] if e.get("organizer_id") != organizer_id
    ]
    _forget_as_friend(state, {"organizer_id": organizer_id})
    workspace.save(state)
    return state


def organizer_cant_attend_impact(state: dict[str, Any], organizer_id: int) -> list[str]:
    """What marking this Organizer Can't attend would clear, one line each: every
    slot entry holding them (and with the last one, their placement). Empty when
    there is nothing to clear, in which case no confirmation is needed."""
    _organizer_record(state, organizer_id)
    return _organizer_impact(state, organizer_id)


def set_organizer_cant_attend(
    workspace: Workspace, organizer_id: int, cant_attend: bool, confirmed: bool = False
) -> dict:
    """Flag an Organizer Can't attend, or clear the flag (:func:`set_cant_attend`
    for an Organizer).

    An Organizer holding a slot is only flagged once ``confirmed``; without it
    :class:`ConfirmationRequired` names the slot entries that would be cleared
    and nothing changes. Confirming removes every slot entry holding them, which
    clears their placement, and raises the stale-roster flag. One holding no slot
    is flagged at once and the roster stays as it is. Clearing the flag only
    clears the flag: it restores nothing, stales nothing and does not solve. While
    flagged an Organizer is left out of the Broken-rule check, the export and
    friend scoring (a request naming them stops counting, silently), and cannot
    be given a slot."""
    state = workspace.load()
    record = _organizer_record(state, organizer_id)
    if bool(record.get("cant_attend")) == cant_attend:
        return state
    if not cant_attend:
        record.pop("cant_attend", None)
        workspace.save(state)
        return state

    impact = _organizer_impact(state, organizer_id)
    if impact and not confirmed:
        raise ConfirmationRequired(
            f"Označením organizátora {record['name']} jako Nemůže se zúčastnit se vymaže: " + "; ".join(impact) + ". "
            "Pozdější zrušení příznaku to neobnoví a rozdělení pomocníků je do dalšího sestavení neaktuální.",
            impact,
        )
    record["cant_attend"] = True
    if impact:
        state["manual_roles"]["structural"] = [
            e for e in state["manual_roles"]["structural"] if e.get("organizer_id") != organizer_id
        ]
        _sync_placements(state)
        _add_stale_reason(state, f"{record['name']} se nemůže zúčastnit: vymazány záznamy rolí")
    workspace.save(state)
    return state


# -- Organizers' survey import -------------------------------------------------
#
# The Organizers' own form (see ``rostering.ingest.organizer_survey``) loads into
# ``state["organizers"]``. A row is the same Organizer as the record with its
# e-mail, else the one of the same normalized name (a hand-made Organizer is
# adopted this way); everything else is a new Organizer, linked to a Person by
# e-mail like a hand-made one, otherwise left to the review list's name matches.
# What the row sets on the record: ``phone``, ``tshirt_size`` (both skipped when
# typed by hand, ``hand_typed``), the e-mail when the sheet has one, and
# ``survey``, the read-only answers as the person wrote them. Nothing about
# placement, Tags, Can't attend or Person links is touched by a re-upload.

_ORGANIZER_COMPARED_FIELDS = ("phone", "tshirt_size", *ORGANIZER_ANSWER_FIELDS)


def _organizer_values(record: dict) -> dict[str, Any]:
    """The survey-derived values of an Organizer record, by field key, in the
    form the import compares them."""
    values: dict[str, Any] = {
        "phone": record.get("phone"),
        "tshirt_size": record.get("tshirt_size") or UNKNOWN_TSHIRT_SIZE,
    }
    answers = record.get("survey") or {}
    values.update({key: answers.get(key) for key in ORGANIZER_ANSWER_FIELDS})
    return values


def _recognize_organizer_rows(rows: list[OrganizerRow], existing: list[dict]) -> list[Optional[dict]]:
    """For each row the existing Organizer it is, or None for a new one. An
    identical e-mail wins; otherwise the same normalized name, unless both sides
    have an e-mail and they differ (then they are probably two people). An
    Organizer is never taken by two rows."""
    ordered = sorted(existing, key=lambda o: o["id"])
    matches: list[Optional[dict]] = [None] * len(rows)
    claimed: set[int] = set()
    for index, row in enumerate(rows):
        if row.email:
            record = next(
                (o for o in ordered if o["id"] not in claimed and normalize_email(o.get("email")) == row.email), None
            )
            if record is not None:
                matches[index] = record
                claimed.add(record["id"])
    for index, row in enumerate(rows):
        if matches[index] is not None:
            continue
        key = normalize_name(row.name)
        record = next(
            (
                o
                for o in ordered
                if o["id"] not in claimed
                and normalize_name(o["name"]) == key
                and not (row.email and normalize_email(o.get("email")) and normalize_email(o.get("email")) != row.email)
            ),
            None,
        )
        if record is not None:
            matches[index] = record
            claimed.add(record["id"])
    return matches


def _apply_organizer_row(record: dict, row: OrganizerRow) -> None:
    """Set the survey-derived fields of ``record`` from ``row``, except any typed
    by hand."""
    typed = set(record.get("hand_typed") or [])
    if "name" not in typed:
        record["name"] = row.name
    if "phone" not in typed:
        if row.phone:
            record["phone"] = row.phone
        else:
            record.pop("phone", None)
    if "tshirt_size" not in typed:
        if row.tshirt_size == UNKNOWN_TSHIRT_SIZE:
            record.pop("tshirt_size", None)
        else:
            record["tshirt_size"] = row.tshirt_size
    if "email" not in typed and row.email:
        record["email"] = row.email
    record["survey"] = dict(row.answers)


def import_organizers(workspace: Workspace, file_bytes: bytes, filename: str) -> dict:
    """Load the Organizers' survey export into the open Season (see the section
    note above); returns the new state.

    A row's Organizer is recognized by e-mail or name, so a re-upload refreshes
    them in place; a new one is created, flagged Can't attend at once when the
    sheet says they won't come on the event day (a re-upload never touches that
    flag, only reports the changed answer). What it did waits in
    ``state["organizer_upload_summary"]`` until dismissed: ``new``, ``adopted``
    (an Organizer made by hand that a row matched), ``changed`` (the field keys
    whose answer differs from before), ``missing`` (earlier sheet Organizers
    absent now, kept), ``also_helper`` (Organizer ids sharing a name with a
    Helper of the Season) and the parser's ``warnings``. Friend names still
    unresolved are matched again afterwards, as a new Organizer may be who a
    Helper meant."""
    if workspace.open_season() is None:
        raise RosteringError(
            "Organizátory lze načíst jen do otevřeného ročníku: nejdřív nahrajte odpovědi pomocníků "
            "(vytvoří ročník) nebo ročník otevřete v postranním panelu."
        )
    tmp_path = _write_temp(file_bytes, filename)
    try:
        result = parse_organizer_survey(tmp_path)
    except ValueError as exc:
        raise RosteringError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    state = workspace.load()
    existing = list(state["organizers"])
    matches = _recognize_organizer_rows(result.organizers, existing)
    new_entries: list[dict] = []
    adopted_entries: list[dict] = []
    changed_entries: list[dict] = []
    touched: list[dict] = []
    for row, record in zip(result.organizers, matches):
        if record is None:
            record = _new_organizer(workspace, state, row.name, row.email)
            _apply_organizer_row(record, row)
            if not row.attending:
                record["cant_attend"] = True
            entry = {"organizer_id": record["id"], "name": record["name"]}
            if not row.attending:
                entry["cant_attend"] = True
            new_entries.append(entry)
        else:
            had_survey = "survey" in record
            before = _organizer_values(record)
            _apply_organizer_row(record, row)
            if not had_survey:
                adopted_entries.append({"organizer_id": record["id"], "name": record["name"]})
            else:
                after = _organizer_values(record)
                fields = [key for key in _ORGANIZER_COMPARED_FIELDS if before[key] != after[key]]
                if fields:
                    changed_entries.append({"organizer_id": record["id"], "name": record["name"], "fields": fields})
        touched.append(record)

    recognized = {record["id"] for record in matches if record is not None}
    missing = [
        {"organizer_id": o["id"], "name": o["name"]}
        for o in existing
        if o["id"] not in recognized and "survey" in o
    ]
    helper_names = {normalize_name(h["name"]) for h in state["helpers"]}
    also_helper = [o["id"] for o in touched if normalize_name(o["name"]) in helper_names]
    _retry_unresolved_friends(state)
    _store_organizer_upload_summary(
        state, new_entries, adopted_entries, changed_entries, missing, also_helper, result.warnings
    )
    workspace.save(state)
    return state


def _store_organizer_upload_summary(
    state: dict[str, Any],
    new: list[dict],
    adopted: list[dict],
    changed: list[dict],
    missing: list[dict],
    also_helper: list[int],
    warnings: list[str],
) -> None:
    """Keep what an Organizers' import did until the user dismisses it. A summary
    nobody has dismissed yet accumulates the new, adopted and changed Organizers
    of later imports (so nothing unread is lost); the missing ones, the
    also-a-Helper ids and the warnings are always those of the latest."""
    live = {o["id"] for o in state["organizers"]}
    old = state.get("organizer_upload_summary") or {}

    def carried(key: str, fresh: list[dict]) -> list[dict]:
        fresh_ids = {e["organizer_id"] for e in fresh}
        return [e for e in old.get(key, []) if e["organizer_id"] in live and e["organizer_id"] not in fresh_ids] + fresh

    changed_by_id = {e["organizer_id"]: dict(e) for e in old.get("changed", []) if e["organizer_id"] in live}
    for entry in changed:
        earlier = changed_by_id.get(entry["organizer_id"], {}).get("fields", [])
        merged = [key for key in _ORGANIZER_COMPARED_FIELDS if key in entry["fields"] or key in earlier]
        changed_by_id[entry["organizer_id"]] = {**entry, "fields": merged}
    summary = {
        "new": carried("new", new),
        "adopted": carried("adopted", adopted),
        "changed": list(changed_by_id.values()),
        "missing": missing,
        "also_helper": also_helper,
        "warnings": warnings,
    }
    if any(summary.values()):
        state["organizer_upload_summary"] = summary
    else:
        state.pop("organizer_upload_summary", None)


def organizer_upload_summary(workspace: Workspace) -> Optional[dict]:
    """What the latest Organizers' import(s) did to the open Season, kept until
    :func:`dismiss_organizer_upload_summary` (None when there is none): ``new``,
    ``adopted``, ``changed`` (with field keys), ``missing``, the ``warnings`` and,
    live, the Organizers sharing a name with a Helper of the Season
    (``also_helper``: ``organizer_id``, ``name``, ``helper_name``) and the
    ``uncertain`` matches still awaiting review
    (:func:`get_uncertain_organizer_matches` entries)."""
    state = workspace.load()
    stored = state.get("organizer_upload_summary")
    if not stored:
        return None
    helpers = {normalize_name(h["name"]): h["name"] for h in state["helpers"]}
    organizers = {o["id"]: o for o in state["organizers"]}
    also_helper = [
        {"organizer_id": oid, "name": organizers[oid]["name"], "helper_name": helpers[normalize_name(organizers[oid]["name"])]}
        for oid in stored.get("also_helper", [])
        if oid in organizers and normalize_name(organizers[oid]["name"]) in helpers
    ]
    return {**stored, "also_helper": also_helper, "uncertain": get_uncertain_organizer_matches(workspace)}


def dismiss_organizer_upload_summary(workspace: Workspace) -> dict:
    """Dismiss the Organizers' import summary; only the summary goes."""
    state = workspace.load()
    state.pop("organizer_upload_summary", None)
    workspace.save(state)
    return state


def assign_organizer(
    workspace: Workspace, organizer_id: int, role: str, building: str, room: Optional[str] = None
) -> dict:
    """Assign an Organizer to a leadership slot (``role``: ``"VedouciBudovy"``,
    ``"PravaRuka"``, ``"VedouciMistnosti"`` or ``"TechnickaPodpora"``) at
    ``building`` and, for a Room-scoped slot, ``room``. This is the only way an
    Organizer is placed: a Room-scoped slot gives Building and Room, a
    Building-scoped one the Building. Assigning them to a slot at another
    placement moves the placement and removes their previous slot entries. Any
    slot cell can hold several Organizers. An address that does not fit the slot's scope is a
    structural error, but a placement is never refused for the Broken rules it
    may cause."""
    state = workspace.load()
    _organizer_record(state, organizer_id)
    slot = _checked_slot(state, role, building, room)
    _place_organizer(state, organizer_id, slot, building, room or None)
    workspace.save(state)
    return state


def move_organizer(
    workspace: Workspace,
    organizer_id: int,
    role: str,
    building: str,
    room: Optional[str] = None,
    source: Optional[dict[str, Any]] = None,
) -> dict:
    """Drag an Organizer's chip into a slot cell: :func:`assign_organizer`, and
    when the chip came out of another slot cell (``source``: its ``role``,
    ``building`` and ``room``) that slot is given up too, so the drag moves them
    instead of adding a second slot at the same Building/Room. A chip dropped back
    on its own cell changes nothing."""
    state = workspace.load()
    _organizer_record(state, organizer_id)
    slot = _checked_slot(state, role, building, room)
    room = room or None
    if source:
        source_slot = _slot_role(source["role"])
        source_room = source.get("room") or None
        if (source_slot, source["building"], source_room) == (slot, building, room):
            return state
        state["manual_roles"]["structural"] = [
            e
            for e in state["manual_roles"]["structural"]
            if not (
                e.get("organizer_id") == organizer_id
                and e["role"] == source_slot.name
                and _same_place(e, source["building"], source_room)
            )
        ]
    _place_organizer(state, organizer_id, slot, building, room)
    workspace.save(state)
    return state


def unassign_organizer(
    workspace: Workspace, organizer_id: int, role: str, building: str, room: Optional[str] = None
) -> dict:
    """Take an Organizer out of one slot. Removing them from every slot they hold
    clears their placement; they stay a tracked Organizer."""
    state = workspace.load()
    _organizer_record(state, organizer_id)
    slot = _slot_role(role)
    structural = state["manual_roles"]["structural"]
    kept = [
        e
        for e in structural
        if not (e.get("organizer_id") == organizer_id and e["role"] == slot.name and _same_place(e, building, room))
    ]
    if len(kept) == len(structural):
        raise RosteringError("Tento organizátor toto místo nedrží.")
    state["manual_roles"]["structural"] = kept
    _sync_placements(state)
    workspace.save(state)
    return state


def _slot_entry_name(state: dict[str, Any], entry: dict) -> str:
    """The display name of a slot entry: its Organizer, else (legacy) the Helper
    or the hand-typed text."""
    if entry.get("organizer_id") is not None:
        return next((o["name"] for o in state["organizers"] if o["id"] == entry["organizer_id"]), f"#{entry['organizer_id']}")
    if entry.get("helper_id") is not None:
        return next((h["name"] for h in state["helpers"] if h["id"] == entry["helper_id"]), f"#{entry['helper_id']}")
    return entry.get("helper_name") or ""


def legacy_slot_entries(state: dict[str, Any]) -> list[dict]:
    """The slot entries that are not (yet) tracked Organizers: saved before
    Organizers existed with a Helper id or hand-typed text. They still display and
    export, marked as such, until replaced. Each is ``role``, ``building``,
    ``room`` and ``name``."""
    return [
        {"role": e["role"], "building": e["building"], "room": e.get("room"), "name": _slot_entry_name(state, e)}
        for e in state["manual_roles"]["structural"]
        if e.get("organizer_id") is None
    ]


def set_slot_holders(
    workspace: Workspace, role: str, building: str, room: Optional[str], names: Sequence[str]
) -> dict:
    """Set the full list of holders of one slot cell from the names the grid
    shows in it: a name matching a tracked Organizer (ignoring case, diacritics
    and spacing) picks them, one nobody tracks creates an Organizer on the spot,
    and a name of an untracked legacy entry already in the cell keeps that entry.
    Whoever is no longer named is removed from the cell (an Organizer left with no
    slot loses their placement)."""
    state = workspace.load()
    slot = _checked_slot(state, role, building, room)
    room = room or None
    cell = [e for e in state["manual_roles"]["structural"] if e["role"] == slot.name and _same_place(e, building, room)]
    legacy_in_cell = {normalize_name(_slot_entry_name(state, e)): e for e in cell if e.get("organizer_id") is None}
    in_cell = {e["organizer_id"] for e in cell if e.get("organizer_id") is not None}

    desired: list[tuple[str, Any]] = []  # ("legacy", entry) or ("organizer", id)
    for raw in names:
        name = (raw or "").strip()
        key = normalize_name(name)
        if not key or any(_desired_key(state, d) == key for d in desired):
            continue
        if key in legacy_in_cell:
            desired.append(("legacy", legacy_in_cell[key]))
            continue
        matches = sorted(
            (o for o in state["organizers"] if normalize_name(o["name"]) == key),
            key=lambda o: (bool(o.get("cant_attend")), o["id"]),
        )
        picked = next((o for o in matches if o["id"] in in_cell), matches[0] if matches else None)
        if picked is None:
            picked = _new_organizer(workspace, state, name, None)
        desired.append(("organizer", picked["id"]))

    cell_ids = {id(e) for e in cell}
    keep_legacy = {id(entry) for kind, entry in desired if kind == "legacy"}
    keep_ids = {value for kind, value in desired if kind == "organizer"}
    state["manual_roles"]["structural"] = [
        e
        for e in state["manual_roles"]["structural"]
        if id(e) not in cell_ids
        or (e.get("organizer_id") is None and id(e) in keep_legacy)
        or (e.get("organizer_id") in keep_ids)
    ]
    for kind, value in desired:
        if kind == "organizer" and value not in in_cell:
            _place_organizer(state, value, slot, building, room)
    _sync_placements(state)
    workspace.save(state)
    return state


def _desired_key(state: dict[str, Any], desired: tuple[str, Any]) -> str:
    kind, value = desired
    if kind == "legacy":
        return normalize_name(_slot_entry_name(state, value))
    return normalize_name(_organizer_record(state, value)["name"])


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
        raise RosteringError(f"Takový štítek neexistuje: {tag_id}")
    return tag


def _validated_tag_name(state: dict[str, Any], name: str, own_id: Optional[int] = None) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise RosteringError("Štítek musí mít název.")
    for other in state.get("tags") or []:
        if other["id"] != own_id and tag_tree.name_key(other["name"]) == tag_tree.name_key(cleaned):
            raise RosteringError(f"Štítek s názvem {other['name']} už existuje.")
    return cleaned


def _validated_tag_colour(colour: str) -> str:
    if not tag_tree.is_hex_colour(colour):
        raise RosteringError(f"Barva štítku je šestnáctková barva jako #3366cc, ne {colour!r}.")
    return colour.lower()


def _validated_tag_parent(state: dict[str, Any], tag_id: Optional[int], parent_id: Optional[int]) -> Optional[int]:
    if parent_id is None:
        return None
    parent = _tag_record(state, parent_id)
    if tag_id is not None and not tag_tree.can_be_parent(_tag_definitions(state), tag_id, parent_id):
        detail = "sám sebe" if parent_id == tag_id else f"{parent['name']}, který ho odvozuje"
        raise RosteringError(f"Štítek nemůže odvozovat {detail}: stal by se vlastním předkem.")
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
                raise RosteringError(f"Taková role neexistuje: {text}. Omezení štítku uvádí jednu ze šesti rolí.")
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


def _group_tag_clashes(state: dict[str, Any]) -> list[forced_friends.TagClash]:
    """The Forced friends groups whose active members' allowed sets have nothing
    in common on a Building or Role axis the group shares."""
    competition = _build_competition(state)
    return forced_friends.tag_clashes(
        competition.forced_groups, competition.helpers, competition.tags, _tag_universes(state)
    )


def _stranded(state: dict[str, Any]) -> set[tuple[str, int, str]]:
    """Every ``(kind, id, axis)`` that currently has no allowed Building or no
    allowed Role: a Helper (``kind`` ``"helper"``) on either axis, an Organizer
    (``"organizer"``) on the Building axis only, since they have no solved Role,
    and a Forced friends group (``"group"``) whose members share no allowed
    Building or Role on an axis the group shares."""
    definitions = _tag_definitions(state)
    universes = _tag_universes(state)
    direct = {h["id"]: _direct_tag_ids(h) for h in state["helpers"]}
    stranded = {("helper", hid, axis) for hid, axis in tag_tree.dead_ends(definitions, direct, universes)}
    direct_organizers = {o["id"]: _direct_tag_ids(o) for o in state["organizers"]}
    building_only = {tag_tree.BUILDING: universes[tag_tree.BUILDING]}
    stranded |= {("organizer", oid, axis) for oid, axis in tag_tree.dead_ends(definitions, direct_organizers, building_only)}
    stranded |= {("group", clash.group.id, clash.axis) for clash in _group_tag_clashes(state)}
    return stranded


def _refuse_new_dead_ends(state: dict[str, Any], before: set[tuple[str, int, str]]) -> None:
    """The one validation behind every Tag entry point (the Tags tab and the
    Helper list's inline multiselect alike): refuse an edit, already applied to
    the in-memory ``state`` but not yet saved, that leaves a Helper with no
    allowed Building or no allowed Role, an Organizer with no allowed Building,
    or a Forced friends group whose members then share no allowed Building or
    Role. Only what the edit newly strands counts, so one already stranded
    (say, by a later configuration change) never blocks an unrelated edit."""
    fresh = sorted(_stranded(state) - before)
    if not fresh:
        return
    tags = _tag_definitions(state)
    universes = _tag_universes(state)
    problems = []
    for kind, person_id, axis in (f for f in fresh if f[0] != "group"):
        record = next(p for p in state["helpers" if kind == "helper" else "organizers"] if p["id"] == person_id)
        found = tag_tree.restrictions(tags, _direct_tag_ids(record), axis, universes[axis])
        display = (lambda v: Role[v].value) if axis == tag_tree.ROLE else str
        why = "; ".join(tag_tree.describe_restriction(r, axis, display) for r in found)
        noun = "roli" if axis == tag_tree.ROLE else "budovu"
        problems.append(f"{record['name']} by neměl(a) žádnou povolenou {noun} ({why})")
    fresh_groups = {(group_id, axis) for kind, group_id, axis in fresh if kind == "group"}
    problems += [c.message() for c in _group_tag_clashes(state) if (c.group.id, c.axis) in fresh_groups]
    shown, hidden = problems[:3], len(problems) - 3
    raise RosteringError("Odmítnuto: " + "; ".join(shown) + (f"; a dalších {hidden}" if hidden > 0 else "") + ".")


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
            raise RosteringError(f"Takový štítek neexistuje: {tag_id}")
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


def add_tag_to_helpers(
    workspace: Workspace, tag_id: int, helper_ids: list[int], organizer_ids: Sequence[int] = ()
) -> dict:
    """Give one Tag directly to each of these Helpers (and Organizers, who carry
    Tags the same way), keeping whatever else they carry (the Tags tab's "Add N
    to <tag>" and the Helper list's bulk apply). All or nothing: an unknown
    Helper, Organizer or Tag, or one person the Tag would leave with no allowed
    Building (or, for a Helper, Role), changes nobody."""
    state = workspace.load()
    _tag_record(state, tag_id)
    people = [_helper_record(state, helper_id) for helper_id in helper_ids]
    people += [_organizer_record(state, organizer_id) for organizer_id in organizer_ids]
    before = _stranded(state)
    for person in people:
        _assign_tags(state, person, [*_direct_tag_ids(person), tag_id])
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


def organizer_tags(state: dict[str, Any], organizer_id: int) -> dict[str, list[int]]:
    """An Organizer's Tags as Tag ids (:func:`helper_tags` for an Organizer):
    ``direct``, ``implied`` and ``effective``, the last two computed live from
    the Tag tree."""
    tags = _tag_definitions(state)
    direct = [
        t for t in dict.fromkeys(_direct_tag_ids(_organizer_record(state, organizer_id))) if any(x.id == t for x in tags)
    ]
    implied = tag_tree.implied_tag_ids(tags, direct)
    return {"direct": direct, "implied": implied, "effective": [*direct, *implied]}


def organizer_allowed(state: dict[str, Any], organizer_id: int) -> dict[str, list[str]]:
    """An Organizer's allowed Buildings from their effective Tag constraints
    (:func:`helper_allowed`, minus the Role axis: an Organizer has no solved
    Role), in configuration order. The live checker judges their placement
    through the same rule."""
    universe = _tag_universes(state)[tag_tree.BUILDING]
    direct = _direct_tag_ids(_organizer_record(state, organizer_id))
    return {"buildings": tag_tree.allowed_values(_tag_definitions(state), direct, tag_tree.BUILDING, universe)}


def set_organizer_tags(workspace: Workspace, organizer_id: int, tag_ids: list[int]) -> dict:
    """Replace the Tags assigned directly to one Organizer (:func:`set_helper_tags`
    for an Organizer). Refused, with the reason, if it would leave them no
    allowed Building; a hand placement they already have is never touched."""
    state = workspace.load()
    before = _stranded(state)
    _assign_tags(state, _organizer_record(state, organizer_id), list(tag_ids))
    _refuse_new_dead_ends(state, before)
    workspace.save(state)
    return state


def remove_tag_from_organizer(workspace: Workspace, tag_id: int, organizer_id: int) -> dict:
    """Take a directly assigned Tag off an Organizer."""
    state = workspace.load()
    organizer = _organizer_record(state, organizer_id)
    _assign_tags(state, organizer, [t for t in _direct_tag_ids(organizer) if t != tag_id])
    workspace.save(state)
    return state


def tag_organizer_carriers(state: dict[str, Any], tag_id: int) -> list[dict]:
    """Every Organizer who carries a Tag, directly or by implication, by name:
    ``organizer_id``, ``name`` and ``via`` (:func:`tag_carriers` for Organizers)."""
    _tag_record(state, tag_id)
    tags = _tag_definitions(state)
    carriers = []
    for organizer in state["organizers"]:
        direct = organizer_tags(state, organizer["id"])["direct"]
        if tag_id in direct:
            carriers.append({"organizer_id": organizer["id"], "name": organizer["name"], "via": None})
        elif tag_id in tag_tree.effective_tag_ids(tags, direct):
            carriers.append(
                {
                    "organizer_id": organizer["id"],
                    "name": organizer["name"],
                    "via": tag_tree.via_tag_id(tags, direct, tag_id),
                }
            )
    return sorted(carriers, key=lambda c: c["name"].lower())


def tag_organizer_counts(state: dict[str, Any]) -> dict[int, int]:
    """Tag id -> how many Organizers carry it, directly or by implication."""
    counts = {t["id"]: 0 for t in state.get("tags") or []}
    for organizer in state["organizers"]:
        for tag_id in organizer_tags(state, organizer["id"])["effective"]:
            counts[tag_id] += 1
    return counts


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


def organizer_tag_pills(state: dict[str, Any]) -> dict[int, dict[str, list[dict[str, str]]]]:
    """Each Organizer's Tag pills for the roster grid, by Organizer id
    (:func:`grid_tag_pills` for Organizers, whose chips sit in their slot cells)."""
    by_id = {t["id"]: t for t in state.get("tags") or []}

    def pill(tag_id: int) -> dict[str, str]:
        return {"name": by_id[tag_id]["name"], "colour": by_id[tag_id]["colour"]}

    pills = {}
    for organizer in state["organizers"]:
        found = organizer_tags(state, organizer["id"])
        pills[organizer["id"]] = {
            "direct": [pill(t) for t in found["direct"]],
            "implied": [pill(t) for t in found["implied"]],
        }
    return pills


def dimmed_organizer_ids(state: dict[str, Any], tag_ids: list[int], mode: str) -> list[int]:
    """The Organizers the roster grid's Tag filter dims (:func:`dimmed_helper_ids`
    for Organizers): everyone who does not match ``tag_ids``."""
    tags = _tag_definitions(state)
    return [
        organizer["id"]
        for organizer in state["organizers"]
        if not tag_tree.matches_filter(tags, organizer_tags(state, organizer["id"])["direct"], tag_ids, mode)
    ]


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


def grid_tags_present(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The Tags carried by anyone on the roster grid (attending Helpers and
    Organizers, in a cell or not), in tree order, for the Tags overlay's legend:
    ``id``, ``name``, ``colour``, ``count`` (people carrying it, directly or by
    implication) and ``direct`` (False when everyone has it only by implication,
    which draws the pill dashed). A Tag nobody on the grid carries is left out."""
    direct_counts: dict[int, int] = {}
    counts: dict[int, int] = {}
    carriers = [
        (helper_tags(state, h["id"]), h) for h in state["helpers"] if not h.get("cant_attend")
    ] + [(organizer_tags(state, o["id"]), o) for o in state["organizers"] if not o.get("cant_attend")]
    for found, _person in carriers:
        for tag_id in found["effective"]:
            counts[tag_id] = counts.get(tag_id, 0) + 1
        for tag_id in found["direct"]:
            direct_counts[tag_id] = direct_counts.get(tag_id, 0) + 1
    return [
        {"id": t.id, "name": t.name, "colour": t.colour, "count": counts[t.id], "direct": t.id in direct_counts}
        for t, _depth in tag_tree.tree_order(_tag_definitions(state))
        if t.id in counts
    ]


def tag_delete_impact(state: dict[str, Any], tag_id: int) -> dict[str, list[str]]:
    """What deleting a Tag would change, by name: ``helpers`` and ``organizers``
    it would be stripped from (those who carry it directly) and ``children`` that
    would be re-parented. All empty means the delete needs no confirmation."""
    record = _tag_record(state, tag_id)
    return {
        "helpers": sorted(
            (h["name"] for h in state["helpers"] if tag_id in _direct_tag_ids(h)), key=str.lower
        ),
        "organizers": sorted(
            (o["name"] for o in state["organizers"] if tag_id in _direct_tag_ids(o)), key=str.lower
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
    if (impact["helpers"] or impact["organizers"] or impact["children"]) and not confirmed:
        lines = []
        if impact["helpers"]:
            lines.append("Odebráno pomocníkům: " + ", ".join(impact["helpers"]))
        if impact["organizers"]:
            lines.append("Odebráno organizátorům: " + ", ".join(impact["organizers"]))
        if impact["children"]:
            parent = next((t["name"] for t in state["tags"] if t["id"] == record["parent_id"]), None)
            lines.append(
                f"Podřízené štítky {', '.join(impact['children'])} "
                + (f"se přesunou pod {parent}" if parent else "se stanou štítky nejvyšší úrovně")
            )
        raise ConfirmationRequired(f"Smazáním štítku {record['name']} se změní: " + "; ".join(lines) + ".", lines)
    for person in (*state["helpers"], *state["organizers"]):
        if tag_id in _direct_tag_ids(person):
            person["tags"] = [t for t in person["tags"] if t != tag_id]
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
    # What the user ticked, by section key (see :func:`import_from_season`); a
    # section with no entry imports everything it offers.
    selections: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportSection:
    """One importable thing: a ``key``, a ``title`` for the UI and ``run``, which
    imports it and returns its summary (a dict; ``lines`` are shown as text). A
    section the user can choose from also gives ``overview``, which lists what it
    would bring from the source (a dict, read only; see :func:`import_overview`)."""

    key: str
    title: str
    run: Callable[[ImportContext], dict[str, Any]]
    overview: Optional[Callable[[ImportContext], dict[str, Any]]] = None


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
    """Person id -> the Tags (ids of the source Season) its records there carry
    directly, in the order carried; only Tags that still exist. A Person's Helper
    and Organizer records count alike, so what a Helper carried is re-applied to
    them as an Organizer now (a promotion) and what an Organizer carried to them
    as a Helper."""
    known = {t["id"] for t in source_state.get("tags") or []}
    by_person: dict[str, list[int]] = {}
    for person in (*source_state["helpers"], *(source_state.get("organizers") or [])):
        person_id = person.get("person_id")
        if not person_id:
            continue
        carried = by_person.setdefault(person_id, [])
        carried.extend(t for t in person.get("tags") or [] if t in known and t not in carried)
    return by_person


def _add_valid_tags(
    state: dict[str, Any], helper: dict, tag_ids: Sequence[int], kind: str = "helper"
) -> tuple[list[int], list[dict]]:
    """Give a Helper (or, with ``kind="organizer"``, an Organizer) these Tags
    directly, one by one, skipping any that would leave them with no allowed
    Building or Role they did not already lack (the same test as
    :func:`_refuse_new_dead_ends`, but a skip instead of a refusal; an Organizer
    has no solved Role, so only the Building axis counts for them) and any they
    carry already. Returns ``(added Tag ids, skipped)``; a skip is ``kind``,
    ``helper_id``/``helper`` (``organizer_id``/``organizer`` for an Organizer),
    ``tag_id``, ``tag`` and ``reason``."""
    tags = _tag_definitions(state)
    names = {t.id: t.name for t in tags}
    universes = _tag_universes(state)
    if kind == "organizer":
        universes = {tag_tree.BUILDING: universes[tag_tree.BUILDING]}
    direct = _direct_tag_ids(helper)
    before = tag_tree.dead_ends(tags, {helper["id"]: direct}, universes)
    added: list[int] = []
    skipped: list[dict] = []
    for tag_id in dict.fromkeys(tag_ids):
        if tag_id in direct:
            continue
        fresh = sorted(tag_tree.dead_ends(tags, {helper["id"]: [*direct, tag_id]}, universes) - before)
        if fresh:
            nouns = " nebo ".join("roli" if axis == tag_tree.ROLE else "budovu" for _, axis in fresh)
            skipped.append(
                {
                    "kind": kind,
                    f"{kind}_id": helper["id"],
                    kind: helper["name"],
                    "tag_id": tag_id,
                    "tag": names[tag_id],
                    "reason": f"{helper['name']} by neměl(a) žádnou povolenou {nouns}",
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
    confidently linked Person, Helper or Organizer in this Season whichever they
    were in the source (an Organizer's constraint is Building-axis only, see
    :func:`_add_valid_tags`). The summary lists Helpers and Organizers tagged
    separately (``helpers_tagged``, ``organizers_tagged``), and the ones awaiting
    review likewise (``awaiting_review``, ``organizers_awaiting_review``)."""
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
    organizers_tagged: list[str] = []
    skipped: list[dict] = []
    for kind, people, names_tagged in (
        ("helper", state["helpers"], tagged),
        ("organizer", state["organizers"], organizers_tagged),
    ):
        for person in people:
            wanted = [mapping[t] for t in carried.get(person.get("person_id"), []) if t in mapping]
            if not wanted:
                continue
            added, refused = _add_valid_tags(state, person, wanted, kind)
            skipped.extend(refused)
            if added:
                names_tagged.append(person["name"])

    awaiting: list[str] = []
    organizers_awaiting: list[str] = []
    for kind, people, names_awaiting in (
        ("helper", state["helpers"], awaiting),
        ("organizer", state["organizers"], organizers_awaiting),
    ):
        proposals = uncertain_candidates(context.person_records, context.season["id"], kind=kind)
        for person in sorted(people, key=lambda p: p["id"]):
            if any(carried.get(c.person_id) for c in proposals.get(person["id"], [])):
                names_awaiting.append(person["name"])

    def names(items: Sequence[str]) -> str:
        return f" ({', '.join(items)})" if items else ""

    lines = [f"Vytvořeno štítků: {len(created)}{names(created)}"]
    if restored:
        lines.append(f"Obnoveno (dříve smazáno, znovu importováno): {len(restored)}{names(restored)}")
    if reused:
        lines.append(f"Už v tomto ročníku, znovu nekopírováno: {len(reused)}{names(reused)}")
    lines.append(f"Označeno pomocníků: {len(tagged)}{names(tagged)}")
    has_organizers = bool(state["organizers"])
    if has_organizers or organizers_tagged:
        lines.append(f"Označeno organizátorů: {len(organizers_tagged)}{names(organizers_tagged)}")
    lines.append(
        f"Vynechaná omezení (nejsou v tomto ročníku): {len(dropped)}"
        + names([f"{d['tag']}: {d['entry']}" for d in dropped])
    )
    lines.append(
        f"Přeskočená přiřazení štítků (nezbyla by povolená budova ani role): {len(skipped)}"
        + names([f"{s[s['kind']]} - {s['tag']}" for s in skipped])
    )
    lines.append(f"Pomocníci čekající na posouzení, neoznačeni: {len(awaiting)}{names(awaiting)}")
    if has_organizers or organizers_awaiting:
        lines.append(
            f"Organizátoři čekající na posouzení, neoznačeni: {len(organizers_awaiting)}{names(organizers_awaiting)}"
        )
    return {
        "tags_created": created,
        "tags_restored": restored,
        "tags_reused": reused,
        "helpers_tagged": tagged,
        "organizers_tagged": organizers_tagged,
        "dropped_constraint_entries": dropped,
        "skipped_assignments": skipped,
        "awaiting_review": awaiting,
        "organizers_awaiting_review": organizers_awaiting,
        "lines": lines,
    }


register_import_section(ImportSection("tags", "Štítky", _import_tags_section))


def _import_context(
    workspace: Workspace, source_season_id: str, selections: Optional[dict[str, Any]] = None
) -> ImportContext:
    """What the sections work on for an import from ``source_season_id`` into the
    open Season (see :class:`ImportContext`); refuses with no Season open or a
    source that is not an earlier stored Season."""
    season = workspace.open_season()
    if season is None:
        raise RosteringError("Před importem štítků otevřete ročník (nebo nahráním odpovědí nějaký vytvořte).")
    source = next((s for s in import_sources(workspace) if s["id"] == source_season_id), None)
    if source is None:
        raise RosteringError("Vyberte dřívější uložený ročník, ze kterého se má importovat.")
    identity = {"id": source["id"], "label": source["label"]}
    return ImportContext(
        workspace.load(),
        workspace.stored_state(source["id"]),
        identity,
        season,
        workspace.person_records(),
        dict(selections or {}),
    )


def import_overview(workspace: Workspace, source_season_id: str) -> dict:
    """What importing from ``source_season_id`` would offer to choose from, read
    only: ``{"source": {"id", "label"}, "sections": [...]}`` with, for each
    registered section that has something to choose (Tags has not), its ``key``,
    ``title`` and its own overview (the Forced friends section's lists each group
    of the source with its returning and missing members, see
    ``forced_groups.import_overview``). Refuses like :func:`import_from_season`."""
    context = _import_context(workspace, source_season_id)
    sections = [
        {"key": s.key, "title": s.title, **s.overview(context)} for s in _IMPORT_SECTIONS if s.overview is not None
    ]
    return {"source": context.source, "sections": sections}


def import_from_season(workspace: Workspace, source_season_id: str, selections: Optional[dict[str, Any]] = None) -> dict:
    """Import from one earlier stored Season into the open one: every registered
    section runs against the source (Tags first) and everything is saved
    together — or nothing, if any of it fails. Running it again, from this or
    another Season, is additive and never copies a Tag twice. The source Season
    is only read. ``selections`` carries what the user ticked, by section key
    (Forced friends groups: ``{"forced_groups": [source group ids]}``); a
    section with no entry imports everything it offers. Returns ``{"source":
    {"id", "label"}, "sections": [...], "promotion_prompt": bool}``, each section
    its ``key``, ``title`` and own summary (the Tags section's is described in
    :func:`_import_tags_section`); ``promotion_prompt`` says the Class promotion
    dialog should open by itself (the open Season is podzim and a school year
    turned since the source)."""
    context = _import_context(workspace, source_season_id, selections)
    season, source, state = context.season, context.source, context.state
    record = state.setdefault("tag_imports", {}).setdefault(
        source["id"], {"label": source["label"], "deleted_tag_ids": []}
    )
    record["label"] = source["label"]
    sections = [{"key": s.key, "title": s.title, **s.run(context)} for s in _IMPORT_SECTIONS]
    workspace.save(state)
    prompt = season["label"].endswith("-podzim") and school_years_crossed(source["label"], season["label"]) >= 1
    return {"source": source, "sections": sections, "promotion_prompt": prompt}


def _late_link_tags(workspace: Workspace, state: dict[str, Any], helper: dict) -> list[dict]:
    """The Tags a Helper's (or Organizer's) Person carried in an imported Season
    as a Helper or an Organizer, resolved into this Season by origin first and
    name second: ``tag_id``, ``name`` and ``source`` (that Season's label). A Tag
    that no longer resolves (deleted on purpose) is left out, and so is one the
    record already carries."""
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


def late_link_organizer_tag_offer(workspace: Workspace, organizer_id: int) -> Optional[dict]:
    """:func:`late_link_tag_offer` for an Organizer whose link to an earlier
    Person was just confirmed (:func:`link_organizer`): ``organizer_id``,
    ``organizer_name`` and ``tags``, or None when there is nothing to offer.
    Nothing is applied and no Tag is created."""
    state = workspace.load()
    organizer = _organizer_record(state, organizer_id)
    tags = _late_link_tags(workspace, state, organizer)
    if not tags:
        return None
    return {"organizer_id": organizer_id, "organizer_name": organizer["name"], "tags": tags}


def apply_late_link_organizer_tags(workspace: Workspace, organizer_id: int) -> dict:
    """Give a late-linked Organizer the Tags :func:`late_link_organizer_tag_offer`
    offers, skipping any that would leave them with no allowed Building. Returns
    ``applied`` (Tag names) and ``skipped`` (as in the import summary)."""
    state = workspace.load()
    organizer = _organizer_record(state, organizer_id)
    offered = _late_link_tags(workspace, state, organizer)
    added, skipped = _add_valid_tags(state, organizer, [t["tag_id"] for t in offered], "organizer")
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
        raise RosteringError("Před zestárnutím tříd otevřete ročník.")
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
            problems.append(f"Nový název štítku {names[tag_id]} je prázdný.")
            continue
        for other_id, other in final.items():
            if other_id == tag_id or tag_tree.name_key(other) != tag_tree.name_key(target):
                continue
            if other_id not in changes:
                problems.append(
                    f"{names[tag_id]} by se stal {target}, ale štítek {names[other_id]} není zaškrtnut "
                    "a název si ponechává. Štítky se nikdy neslučují."
                )
            elif other_id > tag_id:
                problems.append(f"{names[tag_id]} a {names[other_id]} by se oba jmenovaly {target}.")
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
        raise RosteringError("Před zestárnutím tříd otevřete ročník.")
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
        (imports.get(origin["season_id"]) or {}).get("label") or "dřívější ročník"
        for origin in _tag_record(state, tag_id).get("origins") or []
    ]


def put_config(workspace: Workspace, buildings: list[dict], config_path: Optional[Path] = None) -> dict:
    try:
        config_from_list(buildings)
    except (KeyError, ValueError) as exc:
        raise RosteringError(f"Neplatná konfigurace: {exc}") from exc
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
        raise RosteringError(f"Neplatná konfigurace řešiče: {exc}") from exc
    state = workspace.load()
    state["solver_config"] = solver_config_to_dict(parsed)
    workspace.save(state)
    return state


def _standing_assignments(state: dict[str, Any], *, only_locked: bool) -> tuple[list[Assignment], list[str]]:
    """The Assignments (only the locked ones when ``only_locked``) a Solve can
    hold fixed, and the reason for each it can't: one whose Helper, Building or
    Room no longer exists is dropped (that Helper is re-solved as unplaced)."""
    rooms = {(b["name"], r["name"]) for b in state["config"] for r in b["rooms"]}
    buildings = {b["name"] for b in state["config"]}
    helper_ids = {h["id"] for h in state["helpers"] if not h.get("cant_attend")}
    kept: list[Assignment] = []
    dropped: list[str] = []
    for data in state["assignments"]:
        if only_locked and not data.get("locked"):
            continue
        assignment = assignment_from_dict(data)
        if assignment.helper_id not in helper_ids:
            dropped.append(f"Pomocník {assignment.helper_name} už neexistuje")
        elif assignment.building not in buildings:
            dropped.append(f"Budova {assignment.building} už neexistuje")
        elif (assignment.building, assignment.room) not in rooms:
            dropped.append(f"Místnost {assignment.room} už neexistuje")
        else:
            kept.append(assignment)
    return kept, dropped


def _split_locks(state: dict[str, Any]) -> tuple[list[Assignment], list[str]]:
    """The Locked Assignments a full Solve holds fixed, and the reason for each
    lock it drops instead: a lock whose Helper, Building or Room no longer
    exists is dropped (that Helper is re-solved as unlocked)."""
    return _standing_assignments(state, only_locked=True)


def _dropped_locks_lines(reasons: list[str]) -> list[str]:
    """The Solve result's note on dropped locks, e.g. ``"1 zámek zrušen: Místnost
    R2 už neexistuje"`` (empty when none were)."""
    if not reasons:
        return []
    distinct = list(dict.fromkeys(reasons))
    noun = plural(len(reasons), "zámek zrušen", "zámky zrušeny", "zámků zrušeno")
    return [f"{len(reasons)} {noun}: {'; '.join(distinct)}"]


def locked_count(state: dict[str, Any]) -> int:
    """How many Assignments are locked (the bottom bar's live count)."""
    return sum(1 for a in state["assignments"] if a.get("locked"))


def unlocked_assignments_replaced(state: dict[str, Any]) -> int:
    """How many Assignments a full Solve would replace: everything not held by a
    Locked Assignment (a lock the Solve drops counts as replaced). Zero — so no
    confirmation is needed — when nothing is placed yet or all are locked."""
    kept, _ = _split_locks(state)
    return len(state["assignments"]) - len(kept)


def _solve_diagnostics(result: SolveResult, dropped_locks: list[str]) -> dict[str, Any]:
    """The saved-state ``diagnostics`` of a solve (a full Solve or Place new
    registrants), with ``dropped_locks`` the reasons of the locks it dropped."""
    return {
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
        "dropped_locks": _dropped_locks_lines(dropped_locks),
    }


def solve(workspace: Workspace) -> dict:
    state = workspace.load()
    if not state["helpers"]:
        raise RosteringError("Nejdřív nahrajte soubor s odpověďmi.")
    if all(h.get("cant_attend") for h in state["helpers"]):
        raise RosteringError("Všichni pomocníci jsou označeni jako Nemůže se zúčastnit, není tedy koho zařazovat.")
    if not state["config"]:
        raise RosteringError("Nejdřív nastavte alespoň jednu budovu.")

    comp = _build_competition(state)
    solver_config = solver_config_from_dict(state["solver_config"])
    fixed, dropped = _split_locks(state)
    try:
        result = solve_competition(comp, solver_config, fixed_assignments=fixed)
    except NoRosterFound as exc:
        # Nothing to store: the previous roster (if any) is left untouched.
        raise RosteringError(str(exc)) from exc

    # A full Solve keeps the locked Assignments and replaces every other one,
    # which re-places those Helpers: their answers no longer changed "since placed".
    locked_ids = {a.helper_id for a in fixed}
    _clear_answers_changed(state, {h["id"] for h in state["helpers"]} - locked_ids)
    state["assignments"] = [
        assignment_to_dict(replace(a, locked=a.helper_id in locked_ids)) for a in result.assignments
    ]
    state["diagnostics"] = _solve_diagnostics(result, dropped)
    # The roster is fresh again: whatever made it stale has been solved for.
    state["stale_reasons"] = []
    workspace.save(state)
    return state


def place_new_registrants(workspace: Workspace) -> dict:
    """Place only the unassigned Helpers, holding every existing Assignment
    fixed (locked or not): the fixed Helpers still count toward Room/Building
    minimums, Friend preferences and Forced-friend groups, but nobody placed is
    moved, repaired or re-solved, even when a hand move breaks a rule. Locks are
    neither created nor cleared, and the stale flag is left as it is (only a
    full Solve clears it). If not every rule can hold the roster still comes
    back with the Broken rules reported, like any solve. An Assignment whose Room
    or Building no longer exists cannot be held, so that Helper is placed afresh
    with the newcomers (its lock, if any, is dropped and reported as in a full
    Solve). Raises when there is no roster yet or nobody is unassigned."""
    state = workspace.load()
    if not state["config"]:
        raise RosteringError("Nejdřív nastavte alespoň jednu budovu.")
    if not state["assignments"]:
        raise RosteringError("Rozdělení pomocníků zatím neexistuje: nejdřív sestavte celé rozdělení.")
    fixed, _ = _standing_assignments(state, only_locked=False)
    _, dropped_locks = _split_locks(state)
    held = {a.helper_id for a in fixed}
    newcomers = {h["id"] for h in state["helpers"] if not h.get("cant_attend") and h["id"] not in held}
    if not newcomers:
        raise RosteringError("Všichni jsou už zařazeni, není koho zařazovat.")

    comp = _build_competition(state)
    solver_config = solver_config_from_dict(state["solver_config"])
    try:
        result = solve_competition(comp, solver_config, fixed_assignments=fixed)
    except NoRosterFound as exc:
        # Nothing to store: the roster as it was is left untouched.
        raise RosteringError(str(exc)) from exc

    # Every held Assignment stays the record it was (lock and all); only the
    # newcomers' Assignments come from the solve.
    state["assignments"] = [a for a in state["assignments"] if a["helper_id"] in held] + [
        assignment_to_dict(a) for a in result.assignments if a.helper_id in newcomers
    ]
    _clear_answers_changed(state, newcomers)  # placed anew
    state["diagnostics"] = _solve_diagnostics(result, dropped_locks)
    workspace.save(state)
    return state


def broken_rules(state: dict[str, Any]) -> list[BrokenRule]:
    """The Broken rules of the roster in ``state`` as it stands right now
    (see CONTEXT.md "Broken rule"): judged live on every call from the current
    Assignments and configuration, never stored. Nothing about the Helpers is
    judged before the first solve — an empty roster is not a roster that breaks
    its minimums — but an Organizer's placement is, since they are placed by
    hand whether or not anything has been solved."""
    assignments = [assignment_from_dict(a) for a in state["assignments"]]
    broken = check_roster(_build_competition(state), assignments)
    return broken if assignments else [b for b in broken if b.organizer_ids]


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
    ``{helper_id, line}`` chips and ``organizers`` the ``{organizer_id, line}``
    chips of Organizers in their slot cells."""
    return {
        "cells": [
            {"building": b, "room": r, "role": role, "line": rule.line}
            for rule in broken
            for b, r, role in rule.cells
        ],
        "helpers": [{"helper_id": hid, "line": rule.line} for rule in broken for hid in rule.helper_ids],
        "organizers": [{"organizer_id": oid, "line": rule.line} for rule in broken for oid in rule.organizer_ids],
    }


def grid_forced_groups(state: dict[str, Any]) -> dict[int, list[str]]:
    """What the grid marks on a chip: for each Helper who is an active member of a
    Forced friends group in force (some rule binds its attending members), the
    groups that bind them, worded ``Rodina (musí sdílet místnost; ...)`` for the
    chip's tooltip. A dormant group binds no one, so marks no one."""
    competition = _build_competition(state).attending()
    marks: dict[int, list[str]] = {}
    for group in competition.forced_groups:
        # A placed Organizer counts towards a group being in force; only the
        # Helper members carry a chip mark.
        if not forced_friends.in_force(
            group, forced_friends.active_member_count(group, competition.helpers, competition.organizers)
        ):
            continue
        active = forced_friends.active_helper_ids(group, competition.helpers)
        line = f"{group.name} ({'; '.join(rule.text() for rule in group.rules)})"
        for helper_id in active:
            marks.setdefault(helper_id, []).append(line)
    return marks


def set_lock(workspace: Workspace, helper_id: int, locked: bool) -> dict:
    """Lock or unlock a placed Helper's whole Assignment. Only placed Helpers
    are lockable; a lock never blocks anything and does not affect the
    Broken-rule check."""
    state = workspace.load()
    for assignment in state["assignments"]:
        if assignment["helper_id"] == helper_id:
            if locked:
                assignment["locked"] = True
                _clear_answers_changed(state, {helper_id})  # pinning it is accepting the placement
            else:
                assignment.pop("locked", None)
            workspace.save(state)
            return state
    raise RosteringError(f"Pomocník {helper_id} není zařazen, takže není co zamykat.")


def lock_all_placed(workspace: Workspace) -> dict:
    """Lock every placed Helper's Assignment (a no-op with nothing placed)."""
    state = workspace.load()
    for assignment in state["assignments"]:
        assignment["locked"] = True
    _clear_answers_changed(state)
    workspace.save(state)
    return state


def clear_all_locks(workspace: Workspace) -> dict:
    """Unlock every Assignment; the Assignments themselves stay."""
    state = workspace.load()
    for assignment in state["assignments"]:
        assignment.pop("locked", None)
    workspace.save(state)
    return state


def clear_roster(workspace: Workspace) -> dict:
    """Throw the whole roster away and go back to the state before the first
    Solve: every Assignment (locked ones included), the solver's diagnostics
    (status, objective, friend pairs, dropped locks) and the stale flag, which has
    nothing left to be stale about. Helpers, Organizers, Tags, Forced friends
    groups, the layout and the hand-entered Manual roles are untouched. A no-op
    with nothing placed."""
    state = workspace.load()
    state["assignments"] = []
    state["diagnostics"] = {
        "status": None,
        "objective_value": None,
        "unsatisfied_friend_pairs": [],
        "satisfied_friend_pairs": [],
    }
    state["stale_reasons"] = []
    _clear_answers_changed(state)
    workspace.save(state)
    return state


def _entry_covers(state: dict[str, Any], entry: dict, building: str, room: str) -> bool:
    """Whether a Manual role entry's cell holds the place ``building``/``room``:
    a building-scoped entry (no room) holds its whole Building, a room-scoped one
    the cell group its room sits in for its own row, so two rooms the row has
    merged count as one place."""
    if entry.get("building") != building:
        return False
    if entry.get("room") is None:
        return True
    names = next(([r["name"] for r in b["rooms"]] for b in state["config"] if b["name"] == building), [])
    merges = state.get("cell_merges", {}).get(entry["role"], {}).get(building, [])
    group = next((g for g in group_adjacent_rooms(names, merges) if entry["room"] in g), [entry["room"]])
    return room in group


def _entries_left_behind(state: dict[str, Any], helper_id: int, building: str, room: str) -> list[dict]:
    """The Additional role entries that hold this Helper where they stand now
    and no longer fit ``building``/``room``. Empty for an unplaced Helper."""
    previous = next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)
    if previous is None:
        return []
    return [
        entry
        for entry in state["manual_roles"]["overlay"]
        if entry.get("helper_id") == helper_id
        and _entry_covers(state, entry, previous["building"], previous["room"])
        and not _entry_covers(state, entry, building, room)
    ]


def move_manual_role_impact(state: dict[str, Any], helper_id: int, building: str, room: str) -> list[str]:
    """What moving this Helper to ``building``/``room`` would take them out of,
    one line each: the Additional role entries (Manuální role) that hold them
    where they stand now and no longer fit where they would stand. Empty when
    they are unplaced, stay within every such cell, or hold none, in which case
    no confirmation is needed."""
    return [f"Manuální role: {_manual_entry_label(e)}" for e in _entries_left_behind(state, helper_id, building, room)]


def move_helper(
    workspace: Workspace, helper_id: int, building: str, room: str, role: str, confirmed: bool = False
) -> dict:
    """Place a Helper by hand. A move out of a Room whose Additional role cell
    holds them also takes them out of that role (the entry is scoped to the place
    they left), so it is only done once ``confirmed``; without it
    :class:`ConfirmationRequired` names the entries that would go and nothing
    changes. Nothing else is ever refused."""
    state = workspace.load()
    known_ids = {h["id"] for h in state["helpers"]}
    if helper_id not in known_ids:
        raise RosteringError(f"Takový pomocník neexistuje: {helper_id}")
    if any(h["id"] == helper_id and h.get("cant_attend") for h in state["helpers"]):
        raise RosteringError(f"Pomocník {helper_id} je označen jako Nemůže se zúčastnit, takže ho nelze zařadit.")
    helper_name = next(h["name"] for h in state["helpers"] if h["id"] == helper_id)

    impact = move_manual_role_impact(state, helper_id, building, room)
    if impact and not confirmed:
        raise ConfirmationRequired(
            f"Přesunutím pomocníka {helper_name} se odebere z: " + "; ".join(impact) + ".", impact
        )
    if impact:
        leaving = _entries_left_behind(state, helper_id, building, room)
        state["manual_roles"]["overlay"] = [e for e in state["manual_roles"]["overlay"] if not any(e is x for x in leaving)]

    previous = next((a for a in state["assignments"] if a["helper_id"] == helper_id), None)
    assignments = [a for a in state["assignments"] if a["helper_id"] != helper_id]
    moved = {"helper_id": helper_id, "helper_name": helper_name, "building": building, "room": room, "role": role}
    if previous is not None and previous.get("locked"):
        moved["locked"] = True  # a lock moves with its Helper
    assignments.append(moved)
    state["assignments"] = assignments
    _clear_answers_changed(state, {helper_id})  # placed anew by hand
    satisfied, unsatisfied = _recompute_friend_pairs(state)
    state["diagnostics"]["satisfied_friend_pairs"] = satisfied
    state["diagnostics"]["unsatisfied_friend_pairs"] = unsatisfied
    workspace.save(state)
    return state


def put_manual_roles(workspace: Workspace, manual_roles: dict) -> dict:
    try:
        manual_roles_from_dict(manual_roles)
    except (KeyError, ValueError) as exc:
        raise RosteringError(f"Neplatné manuální role: {exc}") from exc
    state = workspace.load()
    # A slot entry that names an Organizer must name a tracked one, at an address
    # its slot's scope allows. Bare Helper/typed entries are the legacy form: a
    # saved one is kept (and still exported) until replaced.
    for entry in manual_roles.get("structural", []):
        if entry.get("organizer_id") is not None:
            _organizer_record(state, entry["organizer_id"])
            _checked_slot(state, entry["role"], entry.get("building"), entry.get("room"))
    state["manual_roles"] = manual_roles
    _sync_placements(state)
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
        raise RosteringError("Taková verze neexistuje")
    return data


@_season_errors
def delete_version(workspace: Workspace, slug: str) -> None:
    if not workspace.delete_version(slug):
        raise RosteringError("Taková verze neexistuje")


def export_xlsx_bytes(workspace: Workspace) -> bytes:
    state = workspace.load()
    if not state["assignments"]:
        raise RosteringError("Zatím není co exportovat — nejdřív sestavte rozdělení.")
    reasons = stale_reasons(state)
    if reasons:
        raise RosteringError("Rozdělení pomocníků je neaktuální: " + "; ".join(reasons) + ". Před exportem sestavte rozdělení znovu.")
    unplaced = unplaced_reason(state)
    if unplaced:
        raise RosteringError(unplaced + ". Před exportem je zařaďte (přetáhněte je do mřížky, nebo sestavte rozdělení).")

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


def export_file_name(label: str) -> str:
    """File name of a Season's exported roster, e.g. ``Rozdělení pomocníků
    Praha - 2026 Jaro.xlsx`` for ``2026-jaro``."""
    return f"Rozdělení pomocníků Praha - {display_label(label)}.xlsx"


def save_export_to_season(workspace: Workspace, data: bytes | None = None) -> Path:
    """Write the exported roster (``data``, else a fresh export) into the open
    Season's directory, replacing an earlier export, and return its path."""
    season = workspace.open_season()
    season_dir = workspace.open_season_dir()
    if season is None or season_dir is None:
        raise RosteringError("Není otevřená žádná sezóna, do jejíž složky by se dalo exportovat.")
    if data is None:
        data = export_xlsx_bytes(workspace)
    path = season_dir / export_file_name(season["label"])
    try:
        path.write_bytes(data)
    except PermissionError as exc:
        raise RosteringError(f"Soubor {path.name} nejde přepsat — není otevřený v Excelu?") from exc
    return path


# The Forced friends import section registers itself when its module loads; it
# builds on this module, so it can only be imported once everything above exists.
from rostering.webapp import forced_groups as _forced_groups  # noqa: E402,F401
