"""Season-agnostic parser for raw Google-Forms survey exports (.xlsx).

Replaces the old utils/parse_helpers.py, which hardcoded one season's exact
header text and silently dropped unresolved friend names. This version:

- matches columns via the candidate table in ``mapping.py`` instead of one
  fixed phrase per field, so it keeps working as form wording changes;
- treats the building-preference and equipment questions as the multi-select
  checkboxes they are, not single choices;
- resolves free-text friend names with normalized-then-fuzzy matching, and
  reports every name it could not confidently resolve instead of dropping it.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from rostering.domain import UNKNOWN_TSHIRT_SIZE, Helper, Role, normalize_name, parse_tshirt_size
from rostering.ingest.mapping import (
    EQUIPMENT_ALIASES,
    FIELD_HEADER_CANDIDATES,
    resolve_building_aliases,
)
from rostering.ingest.preferences import parse_preference, parse_role_token

_FUZZY_MATCH_CUTOFF = 0.75

_ROLE_PREF_FIELD_ROLES: dict[str, Role] = {
    "role_pref_Opravovatel": Role.Opravovatel,
    "role_pref_Menic": Role.Menic,
    "role_pref_Skenovac": Role.Skenovac,
    "role_pref_Kreslic": Role.Kreslic,
    "role_pref_Fotograf": Role.Fotograf,
}


@dataclass
class RawSurveyResult:
    helpers: list[Helper]
    warnings: list[str]
    # Submission timestamp of every registrant row whose timestamp could be
    # read (empty if the export has no readable timestamp column).
    submission_timestamps: list[datetime] = field(default_factory=list)


def _find_columns(headers: list[str]) -> dict[str, str]:
    normalized_headers = {h: normalize_name(h) for h in headers}
    found: dict[str, str] = {}
    for field, candidates in FIELD_HEADER_CANDIDATES.items():
        for candidate in candidates:
            norm_candidate = normalize_name(candidate)
            match = next(
                (h for h, nh in normalized_headers.items() if norm_candidate in nh),
                None,
            )
            if match is not None:
                found[field] = match
                break
    return found


def _cell_str(raw: object) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    return text or None


_ISO_DATE = re.compile(r"(\d{4})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{1,2})")
_CZECH_DATE = re.compile(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})")


def _parse_timestamp(raw: object) -> Optional[datetime]:
    """One timestamp cell -> naive datetime, or None if unreadable. Google
    Forms exports real datetimes to .xlsx, but a re-saved file can turn them
    into text like ``2026/01/12 3:45:12 PM EET`` or ``12. 1. 2026 15:45``."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or raw is pd.NaT:
        return None
    if isinstance(raw, datetime):  # includes pandas.Timestamp
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    text = str(raw).strip()
    try:
        match = _ISO_DATE.match(text)
        if match:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        match = _CZECH_DATE.match(text)
        if match:
            return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None
    return None


def _submission_timestamps(df: pd.DataFrame, columns: dict[str, str]) -> list[datetime]:
    column = columns.get("timestamp")
    if column is None and len(df.columns):
        # No recognizable header: Google Forms always puts the timestamp
        # first, so accept the first column if it is genuinely full of dates.
        first = df.iloc[:, 0].dropna()
        if len(first) and all(isinstance(v, datetime) for v in first):
            column = df.columns[0]
    if column is None:
        return []
    stamps = (_parse_timestamp(v) for v in df[column].tolist())
    return [t for t in stamps if t is not None]


def read_submission_timestamps(path: str | Path) -> list[datetime]:
    """Just the submission timestamps of an export (rows with a name only),
    for prefilling a Season label without a full parse."""
    df = pd.read_excel(path)
    columns = _find_columns(list(df.columns))
    name_col = columns.get("name")
    if name_col is not None:
        df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")]
    return _submission_timestamps(df, columns)


def _split_multiselect(raw: object) -> list[str]:
    text = _cell_str(raw)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


_FREE_TEXT_NAME_SEPARATORS = re.compile(r",|;|/|\+| a | and |&")


def _split_free_text_names(raw: object) -> list[str]:
    """Split a free-text friend-request answer into name-ish chunks. Czech
    answers often join two names with " a " ("and") rather than a comma."""
    text = _cell_str(raw)
    if not text:
        return []
    return [part.strip() for part in _FREE_TEXT_NAME_SEPARATORS.split(text) if part.strip()]


def _resolve_buildings(raw: object, warnings: list[str], row_label: str) -> frozenset[str]:
    # The place question is multi-select, but each option's own label can
    # itself contain commas (e.g. "Impakt + Troja (budova N, budova T, ...)"),
    # so splitting into comma-separated tokens first is unreliable. Instead,
    # scan the whole normalized answer for every known building alias.
    text = _cell_str(raw)
    if not text:
        return frozenset()
    resolved = resolve_building_aliases(text)
    if not resolved:
        warnings.append(f"{row_label}: unrecognized building preference {text!r}")
    return frozenset(resolved)


def _resolve_equipment(raw: object) -> tuple[bool, bool]:
    notebook = False
    camera = False
    for token in _split_multiselect(raw):
        norm_token = normalize_name(token)
        for alias, flag in EQUIPMENT_ALIASES.items():
            if alias in norm_token:
                if flag == "notebook":
                    notebook = True
                elif flag == "camera":
                    camera = True
    return notebook, camera


def _resolve_tshirt_size(raw: object, warnings: list[str], row_label: str) -> str:
    text = _cell_str(raw)
    size = parse_tshirt_size(text)
    if size is None:
        warnings.append(f"{row_label}: unrecognized T-shirt size {text or ''!r}")
        return UNKNOWN_TSHIRT_SIZE
    return size


def _role_preferences_for_row(
    row: pd.Series, columns: dict[str, str]
) -> dict[Role, "Preference"]:
    from rostering.domain import Preference  # local import to avoid unused-name confusion above

    prefs: dict[Role, Preference] = {}
    likert_fields = [f for f in _ROLE_PREF_FIELD_ROLES if f in columns]
    if likert_fields:
        for field, role in _ROLE_PREF_FIELD_ROLES.items():
            col = columns.get(field)
            if col is None:
                continue
            pref = parse_preference(_cell_str(row.get(col)))
            if pref is not None:
                prefs[role] = pref
        return prefs

    # Older-season fallback: one free-text "preferred role" field (-> Ano)
    # and one free-text "role I don't want" field (-> Ne). Roles mentioned
    # in neither are left unset (neutral, no penalty either way).
    preferred_col = columns.get("preferred_role_freetext")
    if preferred_col is not None:
        for token in _split_multiselect(row.get(preferred_col)):
            role = parse_role_token(token)
            if role is not None:
                prefs[role] = Preference.Ano
    unwanted_col = columns.get("unwanted_role_freetext")
    if unwanted_col is not None:
        for token in _split_multiselect(row.get(unwanted_col)):
            role = parse_role_token(token)
            if role is not None:
                prefs[role] = Preference.Ne
    return prefs


def _resolve_friend_names(
    raw: object,
    name_to_id: dict[str, int],
    first_name_to_ids: dict[str, list[int]],
) -> tuple[list[int], list[str]]:
    resolved: list[int] = []
    unresolved: list[str] = []
    for token in _split_free_text_names(raw):
        norm_token = normalize_name(token)
        if not norm_token:
            continue

        # 1) exact full-name match
        if norm_token in name_to_id:
            resolved.append(name_to_id[norm_token])
            continue

        # 2) exact first-name match, only if unambiguous
        first_token = token.strip().split()[0] if token.strip() else token
        candidates = first_name_to_ids.get(normalize_name(first_token), [])
        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue

        # 3) fuzzy match against all known full names
        close = difflib.get_close_matches(
            norm_token, list(name_to_id.keys()), n=1, cutoff=_FUZZY_MATCH_CUTOFF
        )
        if close:
            resolved.append(name_to_id[close[0]])
            continue

        unresolved.append(token)
    return resolved, unresolved


def parse_raw_survey(path: str | Path) -> RawSurveyResult:
    df = pd.read_excel(path)
    headers = list(df.columns)
    columns = _find_columns(headers)
    warnings: list[str] = []

    name_col = columns.get("name")
    if name_col is None:
        raise ValueError(
            f"Could not find a name column in {path} — headers were: {headers}"
        )

    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")]
    df = df.reset_index(drop=True)
    submission_timestamps = _submission_timestamps(df, columns)

    # Pass 1: assign ids and build name-resolution indexes.
    names = [str(v).strip() for v in df[name_col].tolist()]
    name_to_id: dict[str, int] = {}
    first_name_to_ids: dict[str, list[int]] = {}
    for idx, name in enumerate(names, start=1):
        norm_full = normalize_name(name)
        name_to_id.setdefault(norm_full, idx)
        first = name.split(" ")[0]
        first_name_to_ids.setdefault(normalize_name(first), []).append(idx)

    helpers: list[Helper] = []
    friends_col = columns.get("friends")
    building_col = columns.get("building_preference")
    equipment_col = columns.get("equipment")
    tshirt_col = columns.get("tshirt_size")

    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        name = names[idx - 1]
        role_preferences = _role_preferences_for_row(row, columns)
        building_preferences = (
            _resolve_buildings(row.get(building_col), warnings, name) if building_col else frozenset()
        )
        can_bring_notebook, can_bring_camera = (
            _resolve_equipment(row.get(equipment_col)) if equipment_col else (False, False)
        )
        tshirt_size = (
            _resolve_tshirt_size(row.get(tshirt_col), warnings, name) if tshirt_col else UNKNOWN_TSHIRT_SIZE
        )
        friend_ids: list[int] = []
        unresolved_friends: list[str] = []
        if friends_col:
            friend_ids, unresolved_friends = _resolve_friend_names(
                row.get(friends_col), name_to_id, first_name_to_ids
            )
            friend_ids = [fid for fid in friend_ids if fid != idx]

        helpers.append(
            Helper(
                id=idx,
                name=name,
                role_preferences=role_preferences,
                building_preferences=building_preferences,
                friends=friend_ids,
                can_bring_notebook=can_bring_notebook,
                can_bring_camera=can_bring_camera,
                unresolved_friend_names=unresolved_friends,
                tshirt_size=tshirt_size,
            )
        )

    missing_important = [
        f for f in ("building_preference", "friends", "equipment", "tshirt_size") if f not in columns
    ]
    for field in missing_important:
        warnings.append(f"Column for {field!r} not found in {path} — feature left empty for all helpers")

    return RawSurveyResult(helpers=helpers, warnings=warnings, submission_timestamps=submission_timestamps)
