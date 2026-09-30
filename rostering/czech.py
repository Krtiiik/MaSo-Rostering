"""Czech-language helpers for user-facing text (the UI is Czech; code stays
English). See ``docs/czech-ui-glossary.md``."""
from __future__ import annotations


def plural(n: int, one: str, few: str, many: str) -> str:
    """The Czech noun form that goes with the count ``n``: 1 -> ``one``,
    2-4 -> ``few``, anything else (0, 5+) -> ``many``.

    ``plural(3, "pomocník", "pomocníci", "pomocníků")`` -> ``"pomocníci"``."""
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def count_helpers(n: int) -> str:
    return f"{n} {plural(n, 'pomocník', 'pomocníci', 'pomocníků')}"
