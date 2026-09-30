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
  directly. Single-workspace design: the Workspace is the one open Season —
  upload a raw survey export (which creates the Season when none is open),
  configure buildings/rooms directly in the browser, solve, drag helpers
  between cells, save/restore named versions, export to Excel. Every Season
  stays stored and is managed from the sidebar's Seasons panel (open, rename,
  delete, New Season); the open Season's label shows in a header above the
  tabs. Run via `rostering serve` (see README.md).
- Season storage (`rostering/persistence/workspace.py`, label rules in
  `season_label.py`): each Season is a directory `data/seasons/<label>/`
  holding `state.json` and `versions/*.json`, next to any hand-placed
  `raw-response.xlsx`/`config.yaml`; a directory without a `state.json` is
  not a stored Season and is ignored. `data/seasons/open-season.json` points
  at the open Season by id. The state carries its identity as
  `state["season"] = {"id", "label"}`, owned by `Workspace` (stamped on every
  save, never snapshotted into or rolled back from a Version); a rename
  renames the directory but never the id. With no Season open, the Workspace
  is an in-memory blank draft (New Season, or a fresh install) that an upload
  turns into a Season. Deleting a Season removes only its `state.json` and
  `versions/` (hand-placed files stay). `ROSTERING_SEASONS_DIR` overrides the
  seasons directory; `ROSTERING_WORKSPACE_DIR` is the pre-Seasons location
  (`state.json` + `versions/`), read once for the first-launch migration
  (`mutations.migrate_legacy_workspace`), and when set on its own it also
  isolates the seasons under `<dir>/seasons`. Uploads store their
  submission timestamps (`export_timestamps`), which the label prefill and the
  migration use; a legacy state has none, so its migration asks for the label
  (prefilled from the file's last-modified date).
- Persons (`rostering/persons.py`): there is no Person registry. Every Helper
  record in a saved state carries `email` (normalized: trimmed, lower-cased;
  read through the `email` column mapping) and a never-reused random
  `person_id`, distinct from the per-Season Helper `id`. `upload_responses`
  links each row by identical normalized e-mail to the newest matching record
  across every stored Season (`Workspace.person_records()`, the open Season's
  previous upload included) and otherwise mints a fresh `person_id`; a Person's
  e-mails and normalized names (`mutations.list_persons`) are derived from
  those records, so Start over and Season deletion forget what only they held.
  A state saved before Persons existed gets `person_id`s written back on first
  load. Duplicate rows with one e-mail collapse inside `parse_raw_survey`
  (latest submission wins) before ids are assigned. Uncertain (same-name)
  matches are derived, not stored: `persons.uncertain_candidates` proposes,
  for each unsettled Helper of the open Season (one that shares its
  `person_id` with no other record and has no `link_confirmed`), every other
  Person with a record of the same normalized name, minus rejected pairings
  (`rejected_person_ids` on the Helper record, checked from either side).
  `mutations.get_uncertain_matches` / `link_helper` / `reject_person_match` /
  `unlink_helper` / `get_person_links` back the upload tab's review list and
  "Person links" expander. Links, rejections and `link_confirmed` live on the
  Helper record (so Versions roll them back) and are carried over a re-upload
  onto the record with the same `person_id`. The survey's phone (`phone`
  column mapping, `Helper.phone`) is captured for display only.
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
- Equipment eligibility is a **hard** rule (see `CONTEXT.md`), meaning the
  solver bends it only last. Hard rules are never constraints that can make a
  solve infeasible: `rostering/solver/rules.py` relaxes each through a slack
  penalized in fixed, dominance-ordered tiers (`Tier`: minimums, Tag
  restrictions, Forced-friend groups, Equipment), and `solve_competition`
  returns a full roster with `SolveResult.broken_rules`. Only the one-Room /
  one-Role shape and `fixed_assignments` never bend. A new rule family (Tags,
  Forced friends) registers a `RuleFamily` via `register_rule_family`; each
  `Relaxation` it returns carries the `RuleInstance` identity (rule kind +
  entity), and the family must also give a `check` (a `RuleFamily` without
  one cannot be registered) that the live checker runs. The one remaining
  failure is the time limit expiring with no roster (`NoRosterFound`,
  surfaced as "No roster found within N seconds").
- Live Broken-rule check (`rostering/solver/checker.py`: `check_roster`,
  `newly_broken`; per-family checks live next to the relaxations in
  `rules.py`): a pure function of the config, Helpers and current
  Assignments, run on every render and never stored, returning
  `BrokenRule`s with the same identity/family/amount/line the solver reports
  plus `cells` (grid cells; a `None` role marks a whole Room), `helper_ids`
  (chips) and a `FixTarget`. `tests/test_live_broken_rules.py` asserts the
  checker equals the solver's own bent rules. Through the mutation layer:
  `mutations.broken_rules(state)` (empty before the first solve),
  `newly_broken_rules(before, after)`, `move_toast_lines(before, after)`
  (every family except minimums) and `broken_rule_marks(...)`. The grid tab
  renders the banner (family sections collapse above 10 instances), passes the
  marks to the grid component (`broken_marks`) and stores the drop's toast
  lines in session state to emit after the rerun; `fix_focus.py` carries a
  "Go fix" target to the Buildings/Upload tab and drops it once the rule
  holds. `move_helper` has no validation gate. `diagnostics["broken_rules"]`
  in the saved state is only the solver's report as of the last solve and is
  not shown anywhere.
- Locked Assignments: the lock is an optional `locked: true` on an entry of
  `state["assignments"]` (missing = unlocked; `Assignment.locked`, carried by
  `assignment_to_dict`/`assignment_from_dict`), so Versions snapshot it for free.
  `mutations.set_lock` (placed Helpers only), `move_helper` (a lock moves with
  its Helper; a move never creates one) and `solve` (passes the locked
  Assignments as `fixed_assignments`, re-flags them in the result, and drops a
  lock whose Helper or Room no longer exists) are the only code that reads or
  writes it. The grid component reports a toggle as the `lock` trigger
  (`{helper_id, locked}`, from ctrl/cmd-click on a placed chip or the hover
  card's Lock/Unlock button); its drag needs a 6px activation distance so a
  click stays a click. The hover card is interactive (`pointer-events: auto`)
  and closes after a short grace period so the cursor can reach its button.
  Bulk control lives in the Roster tab's bottom bar: `lock_all_placed`,
  `clear_all_locks`, `locked_count`, and `unlocked_assignments_replaced` (what
  a full Solve would throw away, a to-be-dropped lock included; zero means no
  confirmation). `streamlit_app/solve_prompt.py` shows that confirmation for
  both the Roster tab's Solve and the Buildings tab's "Save & solve" (which
  saves the config first so the count uses the new layout). `solve` records
  the locks it dropped as lines in `diagnostics["dropped_locks"]` ("N locks
  dropped: Room X no longer exists"), which the Roster tab shows once after
  the solve. Locks live only in the Season's own `assignments`, so a new
  Season or a Tag import never carries them.
- Can't attend: `cant_attend: true` on the Helper record in the Season's state
  (`Helper.cant_attend`; absent = off), set only by
  `mutations.set_cant_attend(workspace, helper_id, flag, confirmed=False)`.
  The one rule for "who takes part" is `Competition.attending()`, applied by
  `solve_competition`, `check_roster` and the export (`export/people.py`
  `without_absent`), and by `mutations._build_competition`; the grid tab
  filters its own helper list, name suggestions and friend ids. Flagging a
  Helper with an Assignment or Manual role entries raises
  `mutations.ConfirmationRequired` (`.lines` name what goes) unless
  `confirmed=True`, then clears them and sets the stale flag. A re-upload
  carries the flag over by `person_id` (`_carry_over_cant_attend`). The stale
  flag is `state["stale_reasons"]` (list of lines; `mutations.stale_reasons`,
  `mark_stale`), cleared by `solve`, refusing `export_xlsx_bytes`, snapshotted
  by Versions like the rest of the state; the Roster tab shows it above the
  Solve button and disables Export, the Upload tab shows it above the Helper
  list. The Upload tab's confirmation opens on the rerun after the checkbox
  edit (the table's widget key is bumped so it shows the saved state meanwhile).
- Hand-added Helpers: `mutations.add_helper` / `update_helper` /
  `delete_helper` (and `helper_collisions`, the non-blocking name/e-mail
  warning) write ordinary Helper records into `state["helpers"]`, so the
  solver, grid, export, Tags and Can't attend have no second code path. A
  record gets `hand_added: true` and `hand_typed` (the fields typed by hand,
  for the not-yet-built re-upload merge; a hand edit of any Helper adds to it,
  and the T-shirt table edit does for a hand-added one) — both live on the
  record dict only, not on the `Helper` dataclass. An e-mail-shaped contact is
  the normalized `email`, any other contact is `phone` (display-only). Ids come
  from `state["next_helper_id"]`, a high-water mark also bumped by a delete, so
  an id is never reused (Versions snapshot it with the rest of the state). The
  Person link is a confident e-mail match against *earlier* stored Seasons only
  (`link_persons`), else fresh. `delete_helper` reuses `cant_attend_impact` and
  `ConfirmationRequired`, then clears Assignment, lock and Manual role entries,
  prunes the id from every `friends` list and `friend_name_decisions` (a name
  left with no target returns to `unresolved_friend_names`) and marks the
  roster stale. The forms live in `streamlit_app/tabs/helper_forms.py`. Note a
  re-upload still replaces the Season's whole Helper list, so it does not yet
  keep hand-added records.
- Tags (`rostering/tags.py`, the Tags mutations in `mutations.py`): the
  Season's Tag tree is `state["tags"]` (dicts `id`, `name`, `colour`, `note`,
  `parent_id`; ids from the high-water mark `state["next_tag_id"]`, never
  reused), and a Helper's *direct* Tags are the Tag ids in its record's
  `tags`. Effective Tags (direct plus every ancestor) are never stored:
  `tags.effective_tag_ids` / `implied_tag_ids` / `via_tag_id` are pure
  functions of the Tag definitions and the direct ids, reached through
  `mutations.helper_tags`, `tag_carriers` and `tag_helper_counts`. Writes are
  `add_tag` / `update_tag` (unique name ignoring case, hex colour, parent
  refused when it is the Tag itself or a descendant) / `delete_tag` (raises
  `ConfirmationRequired` for a Tag with carriers or children unless
  `confirmed`; then strips it and re-parents its children) and
  `set_helper_tags` / `add_tag_to_helpers` / `remove_tag_from_helper`. Tags
  are part of every Version, empty after Start over, and stay through a
  re-upload (`_carry_over_tags`, matched by `person_id`); `Workspace` gives a
  state saved before Tags existed an empty tree on read. UI: `tabs/tags_tab.py`
  (the "3. Tags" tab) and `tabs/helper_tags.py` (a fragment above the Upload
  tab's Helper table), both drawing pills through `tag_pills.py`. Tag
  constraints, the grid's Tag pills and filter, and Tag import are separate
  tickets and not built yet.
- The solver's role scope is fixed at the 6 roles (see `CONTEXT.md`); the
  Organizer/Additional roles are deliberately out of solver scope, entered
  manually as extra rows inside the same drag-and-drop grid component
  (typed/picked from a name list; the two room-scoped Additional roles also
  accept dropping a helper's existing chip onto their own room's cell) and
  merged in at export time.
- The web app's buildings/rooms layout defaults to a bundled copy of the most
  recent season's config and persists separately in
  `data/buildings-config.yaml` (`rostering/persistence/config_store.py`),
  distinct from each Season's saved state (which carries its own snapshot
  of the layout it used) — so it
  survives "start over" resets and app restarts instead of needing to be
  re-entered by hand each time.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `Krtiiik/MaSo-Rostering`, using the
`gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root. See `docs/agents/domain.md`.
