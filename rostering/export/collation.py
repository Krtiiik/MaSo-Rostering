"""Czech collation, implemented by hand.

The OS locale is deliberately not used: Czech locale support is unreliable on
Windows (and absent from many minimal Linux images), so the order is fixed in
code and gives the same result on every machine.

Rules, as in normal Czech ordering:

- The alphabet is a b c č d e f g h **ch** i j k l m n o p q r ř s š t u v w x
  y z ž. "ch" is one letter sorting between h and i (so "Michal" comes before
  "Mika"); č, ř, š and ž are letters of their own, not accented c/r/s/z.
- Every other diacritic (á é ě í ó ú ů ý ď ť ň, ...) is only a tie-break: names
  are first compared with those accents ignored, and only when that leaves a
  tie does the unaccented spelling sort before the accented one.
- Case is ignored at first and breaks a remaining tie (lower before upper).
- Anything that is not a letter sorts before letters: whitespace and
  punctuation first, then digits. The full string is compared as entered, with
  no word-level or surname handling.
"""
from __future__ import annotations

import unicodedata

# Primary order of the Czech alphabet; "ch" is a digraph handled in the loop.
_ALPHABET = ["a", "b", "c", "č", "d", "e", "f", "g", "h", "ch", "i", "j", "k", "l", "m",
             "n", "o", "p", "q", "r", "ř", "s", "š", "t", "u", "v", "w", "x", "y", "z", "ž"]
_LETTER_RANK = {letter: rank for rank, letter in enumerate(_ALPHABET)}

# Primary-key classes, in sort order.
_SYMBOL, _DIGIT, _CZECH_LETTER, _OTHER_LETTER = range(4)

_Unit = tuple[tuple[int, int], int, int]  # (primary, accent tie-break, case tie-break)


def _unit(char: str) -> _Unit:
    """Sort key parts for one character (never the "ch" digraph)."""
    lower = char.lower()
    case = 1 if char != lower else 0
    if lower in _LETTER_RANK:  # includes č ř š ž
        return (_CZECH_LETTER, _LETTER_RANK[lower]), 0, case
    # Split off accents: "á" -> "a" + acute. The base letter is the primary
    # key, the accent only a tie-break.
    decomposed = unicodedata.normalize("NFD", lower)
    base, marks = decomposed[0], decomposed[1:]
    accent = sum(ord(m) for m in marks) if marks else 0
    if base in _LETTER_RANK:
        return (_CZECH_LETTER, _LETTER_RANK[base]), accent, case
    if base.isalpha():  # a letter outside the Czech alphabet: after all of it
        return (_OTHER_LETTER, ord(base)), accent, case
    if base.isdigit():
        return (_DIGIT, ord(base)), 0, case
    return (_SYMBOL, ord(base)), 0, case


def czech_sort_key(text: str) -> tuple:
    """A key that sorts ``text`` by Czech collation, independent of the OS."""
    text = unicodedata.normalize("NFC", text)
    units: list[_Unit] = []
    i = 0
    while i < len(text):
        if text[i] in "cC" and text[i + 1 : i + 2] in ("h", "H"):
            case = (1 if text[i] == "C" else 0) * 2 + (1 if text[i + 1] == "H" else 0)
            units.append(((_CZECH_LETTER, _LETTER_RANK["ch"]), 0, case))
            i += 2
        else:
            units.append(_unit(text[i]))
            i += 1
    return (
        [u[0] for u in units],
        [u[1] for u in units],
        [u[2] for u in units],
        text,  # total order for strings identical up to the rules above
    )
