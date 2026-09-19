"""Friend-preference scoring configuration (see CLAUDE.md "Friend preference").

A helper may name others they want to share a room with. This is always a
*soft* preference — the solver never forces it — scored along two
independent, configurable axes:

- ``mode``:
  - ``PAIRWISE``: every named request scores independently. A lists B is one
    scored unit, satisfied if A and B end up in the same room, regardless of
    whether B reciprocated.
  - ``MUTUAL``: only requests where both helpers named each other count.
- ``symmetric``: when both A→B and B→A were requested, ``True`` merges them
  into a single scored pair (satisfying it once is "fully satisfied");
  ``False`` scores the two directions independently, so a mutual request
  counts for double the weight of a one-sided one.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from rostering.domain import Helper


class FriendScoringMode(Enum):
    PAIRWISE = "pairwise"
    MUTUAL = "mutual"


@dataclass(frozen=True)
class FriendScoringConfig:
    mode: FriendScoringMode = FriendScoringMode.PAIRWISE
    symmetric: bool = True
    weight: int = 1


def build_friend_pairs(
    helpers: list[Helper], config: FriendScoringConfig
) -> list[tuple[int, int, int]]:
    """Return (helper_a_id, helper_b_id, weight) triples to reward when the
    two helpers end up in the same room, per the configured mode/symmetry."""
    helper_ids = {h.id for h in helpers}
    directed: set[tuple[int, int]] = set()
    for h in helpers:
        for friend_id in h.friends:
            if friend_id in helper_ids and friend_id != h.id:
                directed.add((h.id, friend_id))

    if config.mode is FriendScoringMode.MUTUAL:
        directed = {(a, b) for (a, b) in directed if (b, a) in directed}

    if not config.symmetric:
        return [(a, b, config.weight) for a, b in directed]

    seen: set[frozenset[int]] = set()
    pairs: list[tuple[int, int, int]] = []
    for a, b in directed:
        key = frozenset((a, b))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((a, b, config.weight))
    return pairs
