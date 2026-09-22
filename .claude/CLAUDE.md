# Rostering — project context

This project assigns registered helpers ("pomocníci") to buildings, rooms, and
roles for a Czech math competition ("MaSo"/"MaSe"), based on their preferences,
using an OR-Tools CP-SAT solver. This file is the shared glossary and domain
context — read it before making changes so terminology stays consistent.

## Vocabulary

- **Season** — one instance of the competition, e.g. `2026-jaro` (spring 2026)
  or `2025-podzim` (autumn 2025). `jaro` = spring, `podzim` = autumn.
- **Helper / pomocník** — a volunteer who registered to help, the entity being
  scheduled.
- **Building** — a venue (e.g. Malá Strana, Karlov, Impakt/Troja, Karlín). The
  set of buildings is **not stable across seasons** — always config-driven.
- **Room** — a room within a building (e.g. S3, S4 in Malá Strana). Room
  groupings also change season to season (rooms get merged/split).
- **Role** — the single functional job a helper is assigned to during the
  event. The solver's role set is fixed to 6 roles (see below); other
  functions used in the real event are assigned manually (see "Out-of-solver
  roles").
- **Simulace** — a rehearsal held before the competition day.

## Roles modeled by the solver (a helper gets exactly one)

| Role (Czech) | Code identifier | Meaning |
|---|---|---|
| Opravovatel | `Opravovatel` | Corrector/grader |
| Měnič | `Menic` | "Changer" — swaps/exchanges papers or materials between rounds |
| Skenovač | `Skenovac` | Scans solutions |
| Kreslič | `Kreslic` | Draws problems/diagrams — **requires the helper can bring a notebook (laptop)** |
| Fotograf | `Fotograf` | Photographer — **requires the helper can bring a camera** |
| Záloha | `Zaloha` | Reserve/overflow — not a preference option on the form; absorbs excess helpers, unbounded capacity |

## Out-of-solver roles (manual, post-solve only)

Real events also need these functions, which the solver never assigns —
they're layered on by hand after the solver runs:

- **Structural roles** (assigned to any helper, independent of their solved
  role): **Vedoucí budovy** (building lead), **Pravá ruka** (deputy),
  **Vedoucí místností** (room lead(s)), **Technická podpora** (tech support).
- **Overlay roles** (a helper keeps their solved main role *and* can
  additionally be tagged with one of these, since the duties happen
  before/after the event and don't conflict in time): **Registrace**
  (registration desk, building/global-scoped), **Uvaděči účastníků**
  (participant ushering) and **Focení předávání cen** (photographing the
  award ceremony) — these last two are **room-scoped**: a helper can only
  be tagged into the overlay slot for the room they're already solved
  into, not a different room. In the roster grid these two can be filled
  either by drag-and-dropping a helper's existing chip onto the overlay
  cell for their own room (which duplicates them into that slot without
  moving their solved assignment — shown with a dotted border to mark it
  as a duplicate) or by typing/picking a name as with any other manual
  role.

## Preference scale

Helpers rate each of the 6 roles on a 5-point ordinal scale (free Czech text,
normalized on ingestion): **Ano / Ano, prosím** (yes) → **Klidně** (sure,
no problem) → **Nevadí (mi)** (don't mind) → **Spíš ne** (rather not) →
**Ne / Nechci** (no). Higher = more willing.

## Building preference is a SET, not a single choice

The registration form's place question is a **multi-select checkbox** — a
helper can mark several buildings as acceptable (e.g. "Malá Strana, Karlov").
Model this as an **acceptable-building set**: satisfied if the assigned
building is in the set (or the set is empty, meaning no preference); do not
treat it as a single ranked preference.

## Equipment eligibility (hard constraint)

The form's "what can you bring" question is also multi-select
(`"Notebook, Fotoaparát"` etc.). It gates two roles:

- No notebook checked → the helper **cannot** be assigned Kreslič.
- No camera ("fotoaparát") checked → the helper **cannot** be assigned
  Fotograf.

This is a hard constraint, not a soft preference.

## Friend preference (soft constraint, configurable scoring)

A helper may name others (free text, often nicknames/diminutives — "Terka"
for "Tereza", "Verča" for "Veronika" — and occasionally jokes/non-names) they
want to share a **room** (not just building) with. This must be:

- **Soft**, i.e. minimized-if-unsatisfied, never a hard "must be in the same
  room" constraint.
- **Configurable** along two independent axes:
  - `mode`: `pairwise` (every named request scores independently — partial
    credit per satisfied request) vs `mutual` (only requests where both
    helpers named each other count).
  - `symmetric`: whether a request from A naming B and a request from B
    naming A are merged into one undirected pair, vs scored as two
    independent directed units.
  - Default: `pairwise` + `symmetric`.
- Free-text friend names must be resolved to helper IDs during ingestion via
  normalized/fuzzy matching; **names that can't be confidently resolved must
  be surfaced as a warning**, not silently dropped (the old
  `utils/parse_helpers.py` silently dropped unmatched names).

## Data pipeline stages

1. **Raw survey export** (`data/seasons/<season>/raw-response.xlsx`) — the
   untouched Google Forms export. Column wording changes almost every season
   (see season-by-season header differences below) — ingestion must be
   column-mapping-driven, never hardcoded to one season's exact header text.
2. **Canonical helpers** — parsed into the domain model (`rostering.domain`)
   via `rostering.ingest`.
3. **Season config** (`data/seasons/<season>/config.yaml`) — buildings, rooms,
   and per-role min/max headcounts for that season.
4. **Solve** (`rostering.solver`) — CP-SAT model producing a room+role
   assignment per helper.
5. **Manual overlay** (`data/seasons/<season>/manual-roles.yaml`, optional) —
   hand-entered structural/overlay role assignments, merged in at export time.
6. **Export** (`rostering.export.excel`) — the final formatted roster
   spreadsheet.

## Known historical data quirks (why ingestion must stay flexible)

- Building names vary: `Karlín` one season, `Křižíkova` another, sometimes
  merged as `Impakt + Troja`.
- Room groupings vary: e.g. `N4`, `N6` some seasons; `"N4 + N5"`,
  `"N6 + N7 + N9"` in others.
- Survey question wording and structure changed materially between seasons —
  e.g. 2023-podzim asked one free-text "preferred role" + one free-text
  "role you don't want" field, while 2025/2026 ask five separate per-role
  Likert-style "Výběr role [X]" columns.
- Historical hand-built final rosters (`data/rosters/*.xlsx`) additionally
  track informal per-helper annotations like `(n)`/`(f)` next to names —
  these mark whether the helper can bring a notebook / camera respectively,
  not "new helper" as might be assumed at a glance.

## Versioning

Follows [Semantic Versioning](https://semver.org) with a `CHANGELOG.md` in
[Keep a Changelog](https://keepachangelog.com) format. Log user-facing
changes under `## [Unreleased]` as they land; when that's accumulated
enough to be worth shipping, move it under a new
`## [X.Y.Z] - YYYY-MM-DD` heading, bump `version` in `pyproject.toml` to
match, and tag the commit (`git tag -a vX.Y.Z -m "vX.Y.Z"`). Started at
`0.1.0` (2026-09-20), whose entry is the standalone-executable GitHub
Action. Pushing a `v*.*.*` tag triggers
`.github/workflows/build-executables.yml`, which builds and attaches that
release's Windows/Linux/macOS executables — so cutting a release means
pushing the tag, not just creating it locally.

## Status / decisions log

- Tech stack: a single-process [Streamlit](https://streamlit.io) app
  (`rostering/streamlit_app/`) calling the domain/solver/ingest/export
  modules directly, in-process — no HTTP API layer (the project previously
  shipped a FastAPI backend + separate React/Vite/dnd-kit frontend; both
  were removed in favor of Streamlit to cut the toolchain down to one
  language). `app.py` is the entry point; `mutations.py` holds
  Streamlit-free state-mutation functions (upload, solve, move a helper,
  friend resolution, ...) that the three tabs (`tabs/upload_tab.py`,
  `tabs/config_tab.py`, `tabs/grid_tab.py`) call into and that tests exercise
  directly. Single-workspace design: no season picker in the UI — upload a
  raw survey export, configure buildings/rooms directly in the browser,
  solve, drag helpers between cells, save/restore named versions, export to
  Excel. State persists as JSON under `data/workspace/` (gitignored). Run via
  `rostering serve` (see README.md).
- The one piece of UI Streamlit can't do natively — drag-and-drop — is a
  custom Streamlit component (CCv2) at `components/rostering-assignment-grid/`
  (React + dnd-kit, generated from Streamlit's official CCv2
  `component-template` and then customized). It's packaged as its own
  installable distribution, separate from the `rostering` package, because
  Streamlit's CCv2 manifest scanner discovers packaged components by
  scanning *installed distributions* for their own `pyproject.toml`, not by
  finding arbitrary subpackages nested inside a different, larger
  distribution — see README.md "Setup" for the two-package editable-install
  this requires. Its built JS/CSS bundle is checked into git so a normal
  `pip install -e` alone is enough to run the app.
- Equipment eligibility is a **hard** constraint (see above).
- The solver's role scope is fixed at the 6 roles listed above; the
  structural/overlay roles are deliberately out of solver scope, entered
  manually as extra rows inside the same drag-and-drop grid component
  (typed/picked from a name list; the two room-scoped overlay roles also
  accept dropping a helper's existing chip onto their own room's cell) and
  merged in at export time.
- The web app's buildings/rooms layout defaults to a bundled copy of the most
  recent season's config and persists separately in
  `data/buildings-config.yaml` (`rostering/persistence/config_store.py`),
  distinct from the per-run `data/workspace/state.json` blob — so it
  survives "start over" resets and app restarts instead of needing to be
  re-entered by hand each time.
