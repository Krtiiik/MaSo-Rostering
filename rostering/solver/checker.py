"""The live Broken-rule checker: a pure judgement of the roster as it
currently stands against the current rules (see CONTEXT.md "Broken rule").

Nothing is persisted or cached — the banner recomputes it on every render,
and the drop toast diffs two runs. Each registered rule family states its own
check next to its relaxation (``rostering.solver.rules``), so the checker and
the solver's bent rules describe the same violations under the same
``RuleInstance`` identities.
"""
from __future__ import annotations

from typing import Optional, Sequence

from rostering.domain import Assignment, BrokenRule, Competition
from rostering.solver.rules import CheckContext, RuleFamily, Tier, rule_families


def check_roster(
    competition: Competition,
    assignments: Sequence[Assignment],
    families: Optional[Sequence[RuleFamily]] = None,
) -> list[BrokenRule]:
    """The rule instances the current ``assignments`` break, the tier that
    bends first (minimums) at the top. ``families`` defaults to every
    registered rule family."""
    ctx = CheckContext(competition=competition, assignments=list(assignments))
    broken: list[BrokenRule] = []
    for family in sorted(families if families is not None else rule_families(), key=lambda f: f.tier):
        if family.check is None:
            raise ValueError(f"Rule family {family.name} has no live check")
        broken.extend(family.check(ctx))
    return broken


def newly_broken(before: Sequence[BrokenRule], after: Sequence[BrokenRule]) -> list[BrokenRule]:
    """The instances in ``after`` that ``before`` did not have. Compared by
    identity (rule plus entity) only: a rule that was already broken and got
    worse is not newly broken."""
    already = {b.instance for b in before}
    return [b for b in after if b.instance not in already]


def toasts(broken: BrokenRule) -> bool:
    """Whether a newly broken instance is announced after a hand move: every
    family but the minimums, which routinely dip mid-edit."""
    tiers = {family.name: family.tier for family in rule_families()}
    return tiers.get(broken.family, Tier.EQUIPMENT) != Tier.MINIMUMS
