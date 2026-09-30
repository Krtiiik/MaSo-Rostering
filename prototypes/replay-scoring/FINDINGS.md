# Replay: today's vs candidate role scoring (issue #16) — PROTOTYPE findings

Throwaway. Script: `replay_scoring_PROTOTYPE.py`. Results: `out/results.html` (baseline)
and `out/stress.html` (stress), raw numbers in the matching `.json`. Aggregates only, no names.

**Question:** does the candidate scoring from #15 produce better rosters than today's?

## Setup

6 Seasons (2023-podzim … 2026-jaro, 94–114 Helpers) re-solved on identical inputs under
8 scoring variants, 60 s per solve, using the production CP-SAT model forked so the role cost
is pluggable (fidelity check: fork = production = 114 on 2026-jaro). 45 of 48 baseline solves
are proven optimal (worst gap 6 %). Two regimes:

- **Baseline**: minimums as configured (2026-jaro) or read from the Season's hand-built roster
  (other five; exact for 2026-jaro). Σ minimums is 75–96 % of the Helpers, so Záloha has slack.
- **Stress**: minimums scaled to 100 % of the Helpers: no slack, Roles compete. 2026-jaro's
  stress solves are unconverged (gaps 13–27 %), so treat that Season's stress numbers as soft.

**Two data layouts, and they must be read separately.** The survey changed format:

- **2023-podzim … 2025-jaro: free text** ("preferred role" → Ano, "unwanted role" → Ne,
  every other Role blank). Blanks are the norm here (4 of 5 Roles per Helper).
- **2025-podzim, 2026-jaro: per-Role Likert.** Few blanks (a Helper skips all five or none).
  This is the form going forward, so it is what the decision should rest on.

## Results

### Likert Seasons (2025-podzim + 2026-jaro, 222 Helpers): decision-relevant

| | today | candidate u=4 |
|---|---|---|
| single-"Ano" got their Role, baseline | 115/125 (92 %) | 123/125 (98 %) |
| multi-"Ano" got one of theirs, baseline | 52/54 | 54/54 |
| Helpers parked in Záloha, baseline | 20 (7 had an "Ano") | 0 |
| single-"Ano" got their Role, **stress** | 117/125 | 118/125 |
| Building satisfaction, baseline / stress | 189/199 / 186/199 | 190/199 / 183/199 |
| friend pairs satisfied, baseline / stress | 158/167 / 152/167 | 159/167 / 147/167 |

### Free-text Seasons (2023 … 2025-jaro, 407 Helpers): largely a data-format effect

Single-"Ano" 67/167 (40 %) → 167/167; Záloha 39 (33 with an "Ano") → 0. Today's formula scores an
unmentioned Role 0, the same as the one Role the Helper asked for, so the solver is indifferent
between them. That is exactly the bug the candidate's "blank = Nevadí" removes, and it is why
the pooled numbers look dramatic. It does not predict the gain for future Likert Seasons.

## What each rule buys (ablations at u=4)

- **Záloha costs 4**: the clearest win on Likert data. Free Záloha parks 18 Helpers (6 with an
  "Ano") instead of 20/7 today, and loses 6 single-"Ano" placements vs the full candidate.
- **Blank = Nevadí**: decisive on free-text data (single-Ano 40 % → 100 %), nearly irrelevant
  on Likert data (122 vs 123 of 125), where blanks are rare.
- **Concentration (1 + 1/k)**: weak but consistent evidence in the Likert stress regime
  (removing it loses 4 of 125 single-"Ano" Helpers: 114 vs 118; +1 in the converged
  2025-podzim, +3 in the unconverged 2026-jaro). No effect anywhere else. Roles only have
  minimums, so k=1 and k=3 Helpers rarely compete for the same slot.
- **Unit `u`** (role cost vs Building 3 / friend 5): irrelevant in baseline (u=1…8 identical).
  In stress on Likert data it is a real trade: friend pairs 158 (u=1) → 152 (u=2) → 147 (u=4)
  → 144 (u=8) of 167, and Building 179 → 184, while single-"Ano" moves only 117 → 119. Today's
  weights give 152 friend pairs and 186 Building. So at u=4 the candidate gives up ~5 friend
  pairs and ~3 Building placements under maximum pressure for ~1 more "Ano" placement.

## Caveats

- Only 2026-jaro used its real config. The other five use minimums read from the hand-built
  roster, i.e. what the organizers actually staffed.
- The solver has no per-Role maximums, so scarcity is artificial; "stress" is a proxy.
- CP-SAT breaks ties arbitrarily: differences of 1–2 Helpers between variants are noise.
- Likert evidence is two Seasons and 125 single-"Ano" Helpers: small numbers.

## Decision

**u = 1**, chosen by the user to protect friend requests. On the Likert Seasons under stress it
satisfies 158 of 167 friend pairs (today 152, u=2 152, u=4 147) at the cost of about 7 Building
placements versus today (179 vs 186 of 199). Single-"Ano" placements are unchanged (117 of 125).
Baseline results are identical for u=1 to u=8, so this only matters when Roles compete.

With u=1, an Ano to Klidně step costs 1 against a Building mismatch of 3 and an unsatisfied
friend of 5, so role preferences mostly break ties between placements that are otherwise equal
for Building and friends. `u` stays configurable next to the other solver weights (per #15).
The evidence is two Seasons and the 2026-jaro stress solves were unconverged, so re-check on
the next Season's data.
