# Rostering — project context

This project assigns registered helpers ("pomocníci") to buildings, rooms, and
roles for a Czech math competition ("MaSo"/"MaSe"), based on their preferences,
using an OR-Tools CP-SAT solver.

See `CONTEXT.md` for the shared glossary (Season, Helper, Organizer, Building,
Room, Role, Manual roles, etc.) — read it before making changes so terminology
stays consistent. This file covers everything else: implementation notes,
the data pipeline, known data quirks, and project status/decisions.

## Manual roles (implementation notes)

See `CONTEXT.md` for what Organizer role and Additional role mean and which
named roles belong to each. Implementation details not in the glossary:

- Of the three Additional roles, Registrace is scoped by **building**; the
  other two (Uvaděči účastníků, Focení předávání cen) are scoped by **room**
  (stricter) — so a helper can only be tagged into the slot for their own
  building/room, not a different one.
- In the roster grid, all three Additional roles can be filled either by
  drag-and-dropping a helper's existing chip onto their own building's/room's
  overlay cell (which duplicates them into that slot without moving their
  solved assignment — shown with a dotted border to mark it as a duplicate)
  or by typing/picking a name as with any other manual role.

## Building preference is a SET, not a single choice

The registration form's place question is a **multi-select checkbox** — model
it as the acceptable-building set described in `CONTEXT.md`, never as a
single ranked preference.

## Friend preference (ingestion)

See `CONTEXT.md` for the Friend preference concept and its `mode`/`symmetric`
configuration axes (default: `pairwise` + `symmetric`).

Helper-named friends are free text (often nicknames/diminutives — "Terka" for
"Tereza", "Verča" for "Veronika" — and occasionally jokes/non-names). Free-text
friend names must be resolved to helper IDs during ingestion via
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
   hand-entered Organizer/Additional role assignments, merged in at export time.
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
- Equipment eligibility is a **hard** constraint (see `CONTEXT.md`).
- The solver's role scope is fixed at the 6 roles (see `CONTEXT.md`); the
  Organizer/Additional roles are deliberately out of solver scope, entered
  manually as extra rows inside the same drag-and-drop grid component
  (typed/picked from a name list; the two room-scoped Additional roles also
  accept dropping a helper's existing chip onto their own room's cell) and
  merged in at export time.
- The web app's buildings/rooms layout defaults to a bundled copy of the most
  recent season's config and persists separately in
  `data/buildings-config.yaml` (`rostering/persistence/config_store.py`),
  distinct from the per-run `data/workspace/state.json` blob — so it
  survives "start over" resets and app restarts instead of needing to be
  re-entered by hand each time.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `Krtiiik/MaSo-Rostering`, using the
`gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root. See `docs/agents/domain.md`.
