"""Coloured Tag pills as HTML (Streamlit has no native pill of an arbitrary
colour). A direct Tag is a solid pill; a Tag carried only by implication is
dashed and outlined, so the two read apart at a glance."""
from __future__ import annotations

from html import escape
from typing import Iterable

from rostering.tags import is_hex_colour

_PILL = (
    "display:inline-block;padding:1px 10px;margin:1px 4px 1px 0;border-radius:999px;"
    "font-size:0.85rem;line-height:1.5;white-space:nowrap;"
)


def _text_colour(hex_colour: str) -> str:
    """Black or white, whichever reads better on ``hex_colour``."""
    red, green, blue = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return "#000000" if (red * 299 + green * 587 + blue * 114) / 1000 > 150 else "#ffffff"


def pill_html(name: str, colour: str, implied: bool = False) -> str:
    label = escape(name)
    colour = colour if is_hex_colour(colour) else "#888888"
    if implied:
        style = f"{_PILL}border:1px dashed {colour};color:{colour};background:transparent;"
        return f'<span style="{style}" title="odvozený">{label}</span>'
    style = f"{_PILL}border:1px solid {colour};background:{colour};color:{_text_colour(colour)};"
    return f'<span style="{style}">{label}</span>'


def pills_html(direct: Iterable[dict], implied: Iterable[dict] = ()) -> str:
    """``direct`` and ``implied`` are Tag records (dicts with name and colour)."""
    return "".join(
        [*(pill_html(t["name"], t["colour"]) for t in direct), *(pill_html(t["name"], t["colour"], True) for t in implied)]
    )
