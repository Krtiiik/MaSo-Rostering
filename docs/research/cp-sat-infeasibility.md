# How can CP-SAT report which hard constraints make a solve infeasible?

Research for [#12](https://github.com/Krtiiik/MaSo-Rostering/issues/12) (child of map
[#1](https://github.com/Krtiiik/MaSo-Rostering/issues/1)). Date: 2026-09-26.
OR-Tools version checked: **9.15** (installed `ortools 9.15.6755` in the project venv;
the `stable` branch on GitHub is also 9.15, and all source links below point at the `v9.15` tag).

This document covers facts and trade-offs only. The product decision belongs to the
follow-up grilling ticket ([#13](https://github.com/Krtiiik/MaSo-Rostering/issues/13)).

## TL;DR

- CP-SAT's only built-in way to explain infeasibility is **assumptions**. You put an
  enforcement literal on each constraint group (`.only_enforce_if(g)`), call
  `model.add_assumptions([...])`, and on `INFEASIBLE` read
  `solver.sufficient_assumptions_for_infeasibility()`. The result is a subset of your
  group literals that is still infeasible on its own (an unsat core).
- The core is **useful only in a restricted mode**: the model has **no objective**, it
  runs on **1 worker** (CP-SAT forces this itself), and it does not enumerate or
  interleave. Outside that mode the solver still runs, but on `INFEASIBLE` it returns
  **all** assumptions. The core is "minimized but not guaranteed minimal", and each
  solve returns **one** core.
- The cost for this project is that the forced single worker is much weaker than the
  default portfolio. On a synthetic model shaped like `rostering/solver/model.py`
  (130 helpers × 20 rooms × 6 roles, infeasible by counting), the plain hard model is
  proven infeasible in ~3–4 s. The assumption model with default parameters was still
  `UNKNOWN` after **180 s**. With `linearization_level=2` it finished in 5–14 s.
- **Group granularity decides whether the answer is readable.** With 7 family-level
  literals, the core was `{equip:Fotograf, bldgmin:Fotograf}`. With 308 per-helper and
  per-room literals, the core had 123 entries (4 building minimums + 119 per-helper
  camera rules). That core was minimal, and unreadable.
- **Soft relaxation** turns each hard group into a slack penalized by a large weight M.
  The model is then always feasible, so it keeps the normal multi-worker solve and the
  objective. It returns a full assignment plus a list of broken rules (a *minimum
  correction set*, which is not the same thing as an unsat core). The catch: *which*
  rules get broken is decided by the penalty weights, and ties are broken arbitrarily.
- There are **no other** CP-SAT infeasibility-diagnosis facilities. MathOpt's
  `ComputeInfeasibleSubsystem` is explicitly unimplemented for CP-SAT. The remaining
  tools are logging, model export, `validate()`, and solution hints.

## 1. Assumption literals + `sufficient_assumptions_for_infeasibility`

### API (Python, OR-Tools 9.15)

- `CpModel.add_assumption(lit)`, `add_assumptions(lits)`, `clear_assumptions()`. These
  append to `CpModelProto.assumptions`
  ([cp_model.py](https://github.com/google/or-tools/blob/v9.15/ortools/sat/python/cp_model.py)).
- `CpSolver.sufficient_assumptions_for_infeasibility()` returns **proto variable indices**.
  Map them back with `model.get_bool_var_from_proto_index(i)` (for example to read `.name`).
  The PascalCase `SufficientAssumptionsForInfeasibility()` is a deprecated alias
  (same file).
- Official sample: [`assumptions_sample_sat.py`](https://github.com/google/or-tools/blob/v9.15/ortools/sat/samples/assumptions_sample_sat.py)
  (three constraints `x>y`, `y>z`, `z>x`, each guarded by `a`, `b`, `c`, with all three
  assumed).

### Intended usage: one enforcement literal per constraint group

From the `assumptions` field docs in
[`cp_model.proto`](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model.proto#L682):

> "The model will be solved assuming all these literals are true. Compared to just
> fixing the domain of these literals, using this mechanism is slower but allows in case
> the model is INFEASIBLE to get a potentially small subset of them that can be used to
> explain the infeasibility. […] This is powerful as it allows to group a set of
> logically related constraint under only one enforcement literal which can potentially
> give you a good and interpretable explanation for infeasiblity."

The official [troubleshooting doc](https://github.com/google/or-tools/blob/v9.15/ortools/sat/docs/troubleshooting.md#L83)
gives the same recipe: "add enforcement literals to constraints and add these literals
to the set of assumptions".

In this project, every hard constraint in `model.py` is a linear constraint, and linear
constraints accept enforcement literals. One group literal `g` can guard many
constraints, e.g. `model.add(assign_role[h, Kreslic] == 0).only_enforce_if(g)` for every
helper without a notebook. Constraints left unguarded (such as "exactly one room / one
role per helper") act as background: they are always on and never appear in a core.

### Is the core minimal?

No, not guaranteed:

- `cp_model.proto` on `sufficient_assumptions_for_infeasibility`
  ([around L791–796](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model.proto#L796)):
  "There is also no guarantee that we return an irreducible (aka minimal subset).
  However, this is based on SAT explanation and there is a good chance it is not too
  large. If you really want a minimal subset, a possible way to get one is by changing
  your model to minimize the number of assumptions at false, but this is likely an
  harder problem to solve." It also has "TODO(user): Allows for returning multiple core
  at once", so each solve returns one core.
- Troubleshooting doc: "this set is minimized but not guaranteed to be minimal. To find a
  minimal unsatisfiable set (MUS), you must minimize the (weighted) sum of these
  assumption literals instead of using the assumptions mechanism."
- The minimization step is `MinimizeCoreWithPropagation`, called right after
  `GetLastIncompatibleDecisions()`
  ([cp_model_solver_helpers.cc L1816](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_solver_helpers.cc#L1816)).
  It "should produce a minimal core **with respect to propagation**"
  ([optimization.h L35](https://github.com/google/or-tools/blob/v9.15/ortools/sat/optimization.h#L35)).
  That means it drops literals that propagation can infer from the others. It does not
  re-solve, so the result is not a true MUS.
- Maintainer Laurent Perron in [issue #3983](https://github.com/google/or-tools/issues/3983):
  "the system returns a minimal unsatisfiable set, not a minimal correction set" and
  "(minimal is not guaranteed)". A core tells you *what conflicts*. It does not tell you
  *what is the least you must drop to become feasible*.

### Parameter / threading / presolve restrictions

Everything in this subsection comes from the 9.15 source.

- **Threads:** when the model has assumptions, CP-SAT logs "Forcing sequential search as
  assumptions are not supported in multi-thread" and sets `num_workers = 1`
  ([cp_model_solver_helpers.cc L2182](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_solver_helpers.cc#L2182)).
  Setting `num_workers = 8` is overridden by this.
  The troubleshooting doc says the same: "solving with assumptions is not compatible
  with parallelism".
- **Presolve:** the same block forces `keep_all_feasible_solutions_in_presolve = true`.
  The presolver also skips dual reductions when assumptions exist
  ([cp_model_presolve.cc L13381](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_presolve.cc#L13381)).
  Presolve therefore stays enabled but weaker. Assumption variables are registered so
  presolve does not remove them, and the core is mapped back to original indices after
  postsolve.
- **Degraded mode (all assumptions returned):** the solver logs "Warning: solving with
  assumptions was requested in a non-fully supported setting … it will include all
  assumptions" whenever any of the following is true: `num_workers > 1`, the model has
  an objective (integer or floating point), `enumerate_all_solutions`, or
  `interleave_search`
  ([cp_model_solver.cc L2718](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_solver.cc#L2718)).
  In this mode the assumptions are fixed to true, and a post-processor copies *all* of
  them into the core on `INFEASIBLE` (L2734). Perron,
  [discussion #3630](https://github.com/google/or-tools/discussions/3630): "Objective and
  assumptions are incompatible." In [#3983](https://github.com/google/or-tools/issues/3983):
  "you either have an objective, or use more than 1 worker."
- **Infeasible without any assumption:** if presolve closes the problem as `INFEASIBLE`,
  the response has no core (L2776, "Problem closed by presolve"). In the experiment, an
  infeasible *unguarded* constraint gave `INFEASIBLE` with an **empty** core. An empty
  core therefore means "infeasible even with every guarded group switched off", i.e. the
  background (unguarded) constraints or the data themselves are contradictory.

Consequence for this project: an explanation solve has to be a separate model built
**without `Minimize(...)`**. In practice that means solve normally first, and only if
the result is `INFEASIBLE`, rebuild or clone the model with group literals and no
objective, then run the diagnosis solve.

### Runtime cost: measured on a model shaped like `model.py`

Throwaway experiment, not committed. The synthetic model copies `model.py`'s structure:
`assign_room` / `assign_role` booleans, the boolean-AND `role_room_var`, exactly-one
room and role, equipment bans, per-room and per-building minimums, and the
preference/building/friend objective. Size: 130 helpers, 4 buildings × 5 rooms, 6 roles,
70 friend pairs (~20k booleans). The infeasible instance has two independent counting
conflicts. Every room needs a Kreslič (20) but only 12 helpers have a notebook. Each
building needs 3 Fotografs (12) but only 8 helpers have a camera. Machine: 6 logical
CPUs, Windows, OR-Tools 9.15.

| Run | Result | Wall time |
|---|---|---|
| Hard model, no objective, 8 workers | INFEASIBLE | 4.4 s |
| Hard model, no objective, 1 worker | INFEASIBLE | 2.8 s |
| 308 fine-grained group literals (per helper-ban, per room-min, per building-min), no objective, default params | **UNKNOWN** (no proof) | 30 s and 180 s limits both hit |
| Same, `linearization_level=2` | INFEASIBLE, core = 123 | 12.6–14.0 s |
| 7 family literals (one per rule family, e.g. "all camera bans"), default params | **UNKNOWN** | 30 s limit hit |
| Same, `linearization_level=2` | INFEASIBLE, core = `{equip:Fotograf, bldgmin:Fotograf}` | 4.8 s |
| 308 group literals **with the objective kept** | INFEASIBLE, core = **all 308** (degraded mode) | 1.9 s |

Observations. These come from one synthetic instance, not a benchmark.

- Guarding the counting constraints with enforcement literals made the default
  single-worker search fail. `linearization_level=2` fixed it. That parameter "also add[s]
  all the Boolean constraints" to the LP relaxation
  ([sat_parameters.proto L1650](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto#L1650)).
  It is not a documented requirement for assumptions. It is simply what worked here.
  Validate on real season data before relying on it.
- The 123-literal core contained 4 building-Fotograf minimums and 119 of the 122
  per-helper camera bans. That is minimal: 12 required Fotografs against 8 + 3 = 11
  eligible helpers. It is correct and still useless as a message to a user.
- Only one of the two independent conflicts was reported (the Fotograf one). Finding the
  Kreslič one requires another round: drop the reported groups, then re-solve.

### Shrinking a core: deletion loop

The standard deletion-based MUS extraction works as follows. For each literal `g` in the
current core, re-solve with the core minus `g` assumed. If the result is still
`INFEASIBLE`, drop `g` permanently. Otherwise keep it. After one pass, every remaining
literal is necessary, so the core is a true MUS relative to the guarded groups. Cost:
**one solve per core literal**, sequentially.

- Using the assumptions API for each check makes every check single-threaded.
- Alternative measured here: skip assumptions entirely, and in each check *fix* the kept
  group literals to true (`model.add(g == 1)` on a `model.clone()`). The checks then run
  as normal 8-worker feasibility solves. On the 7-family model this found the MUS
  `{equip:Fotograf, bldgmin:Fotograf}` in **7 solves / 23.6 s** (2–5 s per check).
  With the 123-literal fine-grained core, the same loop would take ~123 solves, which
  is impractical interactively.
- The docs' own suggestion for a true MUS is to minimize the (weighted) number of
  assumption literals set to false. See the soft-relaxation section: it is the same
  model shape.

## 2. Soft-relaxation alternative

Idea: remove the hard version of each group and add a slack instead. Examples:
`sum(terms) + short_g >= min` with `short_g ∈ [0, min]`, or a ban-violation boolean.
Add `M · slack` to the objective, with M much larger than any preference term. The model
is then always feasible, and the solve returns a complete assignment plus the non-zero
slacks as "rules broken".

Facts:

- It is an ordinary optimization model, so none of the assumption restrictions apply.
  It keeps the full multi-worker portfolio (the troubleshooting doc says 8 workers is
  the minimum for the parallel portfolio) and the real objective.
- The docs' "minimize the (weighted) sum of assumption literals" route to a minimal set
  is exactly this model. It returns a **minimum correction set**: the fewest or cheapest
  violations that restore feasibility. Perron contrasts this explicitly with the
  assumptions core ("minimal unsatisfiable set, not a minimal correction set",
  [#3983](https://github.com/google/or-tools/issues/3983)). Perron again, in
  [#3630](https://github.com/google/or-tools/discussions/3630): "minimizing the sum of
  Booleans, or using assumptions are doing the same thing. The minimization is exact.
  The assumptions are heuristics."
- *Which* rules get broken is a modeling choice, set by the relative penalty weights.
  With equal penalties, the experiment broke 11 equipment bans + 1 room minimum. That is
  the optimal count of 12, but it chose to hand cameras and notebooks to people who
  don't own them rather than leave rooms short. A different weighting would flip that.
- Since M dominates, the solver effectively minimizes violations first and preferences
  second. It can only prove optimality once both the violation count and the preference
  part are proven.

Measured (same synthetic model, 8 workers, 30 s limit; single runs, so the variance is
unknown):

| Run | Status | Objective (pref part) | Broken rules |
|---|---|---|---|
| Hard, feasible instance | FEASIBLE (bound 272) | 335 | – |
| Soft, same feasible instance | FEASIBLE (bound 237) | 318 | 0 |
| Soft, infeasible instance | FEASIBLE (bound 12400) | 12662 (662) | 12 = optimal count |

Solve time and quality on the feasible instance looked about the same as the hard
model: both hit the 30 s limit without proving optimality, which `model.py` already does
today at 60 s. On the infeasible instance the violation count was optimal within 30 s,
and the preference part was not proven. This is one seed on one machine, so treat it as
"no obvious penalty" rather than a benchmark. The slack variables add few variables.
The known risk, from general MIP/CP modeling rather than an OR-Tools source, is that
large M weights hurt LP-bound quality and so slow down optimality proofs.

## 3. Other OR-Tools facilities

- **MathOpt IIS:** `ComputeInfeasibleSubsystem` exists in MathOpt, but the CP-SAT backend
  returns `UnimplementedError("CPSAT does not provide a method to compute an infeasible
  subsystem")`
  ([math_opt/solvers/cp_sat_solver.cc L680](https://github.com/google/or-tools/blob/v9.15/ortools/math_opt/solvers/cp_sat_solver.cc#L680)).
  So no IIS is available for CP-SAT.
- **Troubleshooting checklist**
  ([troubleshooting.md](https://github.com/google/or-tools/blob/v9.15/ortools/sat/docs/troubleshooting.md#L68)):
  reduce the model, remove constraints while it stays infeasible, enlarge domains,
  "inject a known feasible solution and try to find where it breaks", and check the data.
  These are all manual techniques.
- **Solution hints as a checker:** with a *complete* hint (`model.add_hint`), the solver
  logs "The solution hint is complete, but it is infeasible!"
  ([cp_model_solver.cc L1012](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_solver.cc#L1012)).
  The *which constraint* detail ("Failing constraint #c") is only emitted at C++
  `VLOG(1)` ([cp_model_checker.cc L1926](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_checker.cc#L1926)),
  which Python code cannot easily read. Checking a candidate assignment (e.g. a previous
  roster or the user's manual edits) against the rules in plain Python is simple and
  independent of the solver. That is a design option, not an OR-Tools feature.
- **`log_search_progress`, `model.validate()`, `export_to_file()`:** logging shows
  "Problem closed by presolve" and presolve rule counts, and it prints the
  assumptions-mode warnings above. `validate()` only reports a malformed model
  (`MODEL_INVALID`), not infeasibility. Export is for offline debugging. None of them
  names the conflicting constraints.
- **`sat_parameters` `core_minimization_level` / `find_multiple_cores`:** these belong to
  the core-based **max-SAT optimization** search ("in the core based max-SAT
  algorithms"), not to `sufficient_assumptions_for_infeasibility`
  ([sat_parameters_pb2.pyi](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto)).
  They are not a diagnosis API.

## 4. Trade-offs for the decision (not a recommendation)

| | Assumptions core | Assumptions + deletion loop | Soft relaxation |
|---|---|---|---|
| Output | One conflicting group set (not a full roster) | One minimal conflicting set | Full roster + list of broken rules |
| Semantics | "These rules together can't hold" (unsat core) | Same, irreducible | "Break these (fewest/cheapest) to fit" (correction set) |
| Needs objective removed | Yes | Yes (or fixed-literal variant) | No |
| Threads | Forced to 1 | 1, or N with fixed-literal variant | N (normal) |
| Minimal? | No guarantee | Yes (w.r.t. groups) | Minimum *weighted* correction set, if proven optimal |
| Multiple conflicts | One per solve | One per loop | All at once (whatever it breaks) |
| Extra cost | A second solve when infeasible; can be slow single-threaded (needed `linearization_level=2` here) | +1 solve per core literal | Always-on; M weights must be designed; the choice of what to break is a policy |
| Readability depends on | Group granularity | Group granularity | Group granularity + penalty design |

Open questions for the grilling ticket:

- What granularity should rule groups have? Per rule family, per room or building, or
  per helper? Family-level cores are readable. Per-helper ones are not.
- Should the user get "why it's impossible" (core) or "the best roster if we bend these
  rules" (correction set)? The two answer different questions.
- For soft relaxation: what is the relative priority of breaking each hard-rule family
  (equipment vs. headcount vs. tag restrictions vs. forced friends vs. pre-placed
  organizers)?
