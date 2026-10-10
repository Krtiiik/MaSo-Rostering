"""Season labels: a year plus jaro/podzim, e.g. ``2026-jaro``.

The label is a Season's human identity: required, unique among stored
Seasons, editable, and the sort key that orders Seasons in time (jaro sorts
before podzim within a year). It doubles as the Season's directory name, so
it is validated strictly and normalized to one canonical spelling.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, Optional

HALVES = ("jaro", "podzim")  # in calendar order: spring, then autumn

_LABEL_RE = re.compile(r"^(\d{4})\s*[-_/ ]?\s*(jaro|podzim)$", re.IGNORECASE)

LABEL_FORMAT_HINT = "rok a jaro nebo podzim, např. 2026-jaro"


def normalize_label(text: Optional[str]) -> Optional[str]:
    """Canonical ``YYYY-jaro`` / ``YYYY-podzim`` spelling of ``text`` (case,
    surrounding whitespace and a space/underscore/slash separator are
    tolerated), or ``None`` if it isn't a valid label."""
    match = _LABEL_RE.match((text or "").strip())
    if match is None:
        return None
    return f"{match.group(1)}-{match.group(2).lower()}"


def display_label(label: str) -> str:
    """Readable form of a label, ``2026-jaro`` -> ``2026 Jaro``; anything that
    is not a valid label is returned unchanged."""
    normalized = normalize_label(label)
    if normalized is None:
        return label
    year, half = normalized.split("-", 1)
    return f"{year} {half.capitalize()}"


def label_sort_key(label: str) -> tuple[int, int]:
    """Time-order key: ``(year, 0 for jaro / 1 for podzim)``. ``label`` must
    be a normalized label."""
    year, half = label.split("-", 1)
    return int(year), HALVES.index(half)


def next_free_label(label: str, taken: Iterable[str]) -> Optional[str]:
    """The first label after ``label`` (a normalized one), going half-year by
    half-year, that is not in ``taken`` — the suggestion for a copy of a Season
    that cannot keep its own label. ``None`` only if forty half-years are all taken."""
    taken = set(taken)
    year, half = label_sort_key(label)
    for _ in range(40):
        half += 1
        if half == len(HALVES):
            year, half = year + 1, 0
        candidate = f"{year:04d}-{HALVES[half]}"
        if candidate not in taken:
            return candidate
    return None


def half_of(when: date | datetime) -> str:
    """January to June is jaro, July to December is podzim."""
    return "jaro" if when.month <= 6 else "podzim"


def guess_label(timestamps: Iterable[date | datetime]) -> Optional[str]:
    """Best-guess label from an export's submission timestamps: the label of
    the median submission (robust to a few stragglers submitting long after
    the rest). ``None`` when there are no timestamps. Only ever a prefill —
    the organizer confirms or edits it."""
    ordered = sorted(t.date() if isinstance(t, datetime) else t for t in timestamps)
    if not ordered:
        return None
    median = ordered[len(ordered) // 2]
    return f"{median.year:04d}-{half_of(median)}"


def school_years_crossed(source_label: str, current_label: str) -> int:
    """How many school years turned between two Seasons (normalized labels): the
    school year turns at the jaro -> podzim boundary, so 2026-jaro is still the
    school year 2025-podzim began, and 2026-jaro -> 2026-podzim crosses one.
    Never negative."""

    def school_year(label: str) -> int:
        year, half = label_sort_key(label)
        return year if half == HALVES.index("podzim") else year - 1

    return max(0, school_year(current_label) - school_year(source_label))
