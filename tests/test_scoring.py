from rostering.domain import Helper
from rostering.solver.scoring import FriendScoringConfig, FriendScoringMode, build_friend_pairs


def _helper(id_, friends):
    return Helper(id=id_, name=f"h{id_}", friends=friends)


def test_pairwise_symmetric_merges_mutual_request_into_one_pair():
    # A and B both name each other -> one merged pair, not two.
    helpers = [_helper(1, [2]), _helper(2, [1])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig(mode=FriendScoringMode.PAIRWISE, symmetric=True))
    assert len(pairs) == 1
    a, b, weight = pairs[0]
    assert {a, b} == {1, 2}


def test_pairwise_nonsymmetric_scores_mutual_request_twice():
    helpers = [_helper(1, [2]), _helper(2, [1])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig(mode=FriendScoringMode.PAIRWISE, symmetric=False))
    assert len(pairs) == 2


def test_pairwise_counts_one_sided_request():
    # Only A names B; B does not name A. Pairwise still scores it.
    helpers = [_helper(1, [2]), _helper(2, [])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig(mode=FriendScoringMode.PAIRWISE, symmetric=True))
    assert len(pairs) == 1


def test_mutual_mode_drops_one_sided_request():
    helpers = [_helper(1, [2]), _helper(2, [])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig(mode=FriendScoringMode.MUTUAL, symmetric=True))
    assert pairs == []


def test_mutual_mode_keeps_reciprocated_request():
    helpers = [_helper(1, [2]), _helper(2, [1])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig(mode=FriendScoringMode.MUTUAL, symmetric=True))
    assert len(pairs) == 1


def test_unknown_friend_id_is_ignored():
    helpers = [_helper(1, [999])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig())
    assert pairs == []


def test_self_reference_is_ignored():
    helpers = [_helper(1, [1])]
    pairs = build_friend_pairs(helpers, FriendScoringConfig())
    assert pairs == []
