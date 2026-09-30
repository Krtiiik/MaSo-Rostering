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
  Helper record (so Versions roll them back) and stay put through a re-upload,
  which updates the recognized record in place. The survey's phone (`phone`
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
  never touches the flag (the recognized record is updated in place). The stale
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
  for the re-upload, which never overwrites them; a hand edit of any Helper adds to it,
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
  roster stale. The forms live in `streamlit_app/tabs/helper_forms.py`. A
  re-upload keeps hand-added records (they are never listed as "missing from the
  export"); a row with the same e-mail updates one in place, skipping the fields
  in its `hand_typed`. A same-name row with no e-mail match is a new registrant
  on the review list whose candidate has `merges_into` (the hand-added Helper's
  id, `_hand_added_merge_target`); `link_helper` then does not link two records
  but folds the row into the hand-added Helper (`_merge_into_hand_added`): the
  survey answers go through `_refresh_from_survey` (so `hand_typed` wins and
  defaults fill), Tags are unioned, the row's Assignment and lock move over only
  if the Helper has none, every Friend preference, `friend_name_decisions` and
  Manual role entry naming the row's id is repointed, the row's record and its
  `upload_summary` entries disappear, and the Helper stays `hand_added` with
  `link_confirmed`. The Helper's own flags (Can't attend) win; the row's are not
  carried. Typed Manual role names (`helper_id` None, `helper_name` text) are
  matched live by normalized name against the attending Helpers
  (`get_typed_role_link_offers`, one offer per typed name with its candidates
  and slots; shown above the review list in the Upload tab);
  `link_typed_role_name` rewrites every such entry to `{helper_id, helper_name:
  None}` (dropping one whose slot the Helper already holds) and
  `decline_typed_role_link` records the pair in `state["declined_typed_role_links"]`
  (name key + Helper id) so it is never offered again.
- Re-upload (`mutations.upload_responses` with a Season open, via
  `_merge_survey_rows`): `parse_raw_survey` still numbers its rows 1..N, so the
  merge maps each parsed id to a real one first (`_recognize_rows`: an identical
  normalized e-mail against the Season's own Helpers, else the Person
  `link_persons` finds if a Season Helper carries it; a row is never taken by two
  Helpers) and gives a new registrant `_next_helper_id`. A recognized record is
  refreshed in place by `_refresh_from_survey`: `_SURVEY_FIELDS` (name, role
  preferences, Building set, equipment, e-mail, phone) except those in
  `hand_typed`; friend names keep their `friend_name_decisions` only while the
  same name is still unresolved in the row (`friend_name_order` is refreshed);
  the T-shirt size takes the row unless it was set by hand while the last
  survey answer (`survey_tshirt_size` on the record, written by every upload) is
  unchanged. Assignments, locks, manual roles, merges, Tags, Can't attend and
  every other non-survey key are never touched, and only the friend-pair
  diagnostics are recomputed. On a re-upload of a Season that had Helpers,
  `state["upload_summary"]` (`new`, `changed`, `missing`; hand-added Helpers are
  never "missing") accumulates until `dismiss_upload_summary`, and
  `upload_summary(workspace)` adds the live `uncertain` matches. A placed
  Helper whose Building set, Preferences (blank = Nevadí) or equipment changed
  gets `answers_changed` (the field labels) on the record, shown as a chip mark
  in the grid (`answers_changed` helper prop); it is cleared by `move_helper`,
  locking (`set_lock`, `lock_all_placed`), a full Solve for the Helpers it
  re-places, and losing the Assignment, never by dismissing the summary
  (`answers_changed_since_placed` reads it, ignoring an unplaced Helper).
  Export gate: `unplaced_helpers` / `unplaced_reason` (attending Helpers with no
  Assignment once a roster exists) feed `export_blockers` and
  `export_xlsx_bytes`; unlike `stale_reasons` it is derived live, so placing the
  newcomers by hand lifts it. UI: `tabs/upload_summary_ui.py` (top of the Upload
  and Roster tabs), the Roster tab's warning above Solve. A same-name row with
  no e-mail match is a new registrant plus a review-list entry, so re-uploading
  an export with no e-mail column duplicates every Helper as one to review.
- Place new registrants (`mutations.place_new_registrants`; Roster tab bottom
  bar button, enabled while `unplaced_reason` is set): `solve_competition` with
  *every* standing Assignment as `fixed_assignments` (`_standing_assignments`,
  the shared filter behind `_split_locks`: it skips one whose Helper, Building or
  Room is gone), then only the newcomers' Assignments are taken from the result
  and appended, so every existing record stays byte-for-byte as it was (lock
  flag included). Never reads or writes a lock beyond reporting, in
  `diagnostics["dropped_locks"]`, a lock on a vanished Room (that Helper has no
  usable Assignment, so is placed afresh with the newcomers and its
  `answers_changed` marker cleared). Unlike `solve` it leaves `stale_reasons`
  alone, needs no confirmation (nothing placed can be lost) and raises
  `RosteringError` when there is no roster yet or nobody is unassigned.
  `diagnostics` come from the shared `_solve_diagnostics`, and the Broken-rule
  banner judges the result live like after any solve. Forced-friend groups
  need no code here: the rule family applies to the newcomers through the same
  fixed-Assignment solve.
  roster stale. The forms live in `streamlit_app/tabs/helper_forms.py`. Note a
  re-upload still replaces the Season's whole Helper list, so it does not yet
  keep hand-added records.
- Organizers (`rostering/organizers.py`, the Organizers section of
  `mutations.py`): the Season's Organizers are `state["organizers"]` (dicts `id`,
  `person_id`, `name`, `email`, `building`, `room`; ids from the high-water mark
  `state["next_organizer_id"]`, never reused), part of every Version. They are
  not Helpers: `Competition.organizers` (domain `Organizer`) carries them to the
  export only, the solver never sees them. The four leadership slots hold them by
  `organizer_id` on a `manual_roles["structural"]` entry; the placement
  (`building`/`room`) on the record is derived, only ever written by
  `_sync_placements` from those entries (so `assign_organizer`,
  `unassign_organizer`, `set_slot_holders`, `delete_organizer` and
  `put_manual_roles` all end by re-deriving it). `organizers.SLOT_SCOPES` /
  `check_slot` define a slot's address (Vedoucí budovy and Technická podpora:
  Building only; Vedoucí místností: Building and Room; Pravá ruka: either), a
  mismatch being a `RosteringError`, never a rule matter. `assign_organizer`
  moves the placement (removing the Organizer's entries at another Building/Room;
  entries at the same one stay) and a single-holder cell replaces its holder.
  `set_slot_holders` backs the grid: a typed name picks a tracked Organizer
  (normalized-name match) or creates one on the spot, a legacy entry named in the
  cell is kept. A *legacy* entry (no `organizer_id`; a `helper_id` or typed
  `helper_name`) stays in `manual_roles`, exports as before, shows with a "not
  tracked" badge (`mutations.legacy_slot_entries`, `legacy` on the grid's
  `manual_entries`) and is dropped when a single-holder cell gets a new holder or
  its chip is removed; `put_manual_roles` stays lenient about legacy entries
  (only validating `organizer_id` ones). Person recognition: `records_from_state`
  yields Organizer records too (`PersonRecord.kind`, ids are per kind), so
  `list_persons`, e-mail matching (`add_organizer`/`update_organizer`) and the
  Helper review list (`get_uncertain_matches`, which thus offers a link to a
  Person known as an Organizer) cover them; `get_uncertain_organizer_matches` /
  `link_organizer` / `reject_organizer_match` / `unlink_organizer` mirror the
  Helper ones and have no UI yet. Promotion of a Helper, Friend preference toward
  an Organizer and Organizer Can't attend/Tags are separate, later tickets.
- Forced friends groups (`rostering/forced_friends.py`, the lifecycle in
  `streamlit_app/forced_groups.py`, UI in `tabs/forced_friends_tab.py` — the
  "4. Forced friends" tab, Roster being "5. Roster"): a group is a dict in
  `state["forced_groups"]` (`id` from the high-water mark
  `next_forced_group_id`, `name`, canonical `axes` — Room implies Building —
  and `members`, each `{person_id, name}` with the last-known name), part of
  every Version, empty after Start over and untouched by a re-upload. Members
  are Persons; who they are this Season is derived on every read
  (`forced_groups.list_groups`: `active` = a Helper who is attending,
  `cant_attend`, `not_registered`), never stored, so un-flagging or a later
  registration recognized by `person_id` makes a member live again by itself.
  `forced_friends.group_rules(helpers, groups)` is the one shared definition of
  a group's rule for the solver and the checker: one `GroupRule` per active
  group (two or more attending members) and enforced axis (Room subsumes
  Building), identity `RuleInstance("forced_friends", (group_id, axis))`, size
  `split_units` (members outside the largest party sharing a value, so the
  Room axis compares `(building, room)`). `solver/rules.py`
  `FORCED_FRIENDS_FAMILY` (tier between Tag restrictions and Equipment) states
  it as a max-count slack per rule and `_check_forced_friends` judges it live
  (the line is the same wording in both, `GroupRule.line(assignments)`: `Group
  Rodina [Anna, Petr, Jana] is split across rooms N4 and N6`, naming the active
  members and the distinct places their Assignments occupy on the axis (a Room
  name shared by two Buildings is suffixed with its Building). Because a slack
  knows no places, `Relaxation` has an optional `describe_placed(units,
  assignments)` that `to_broken_rule` uses with the solved roster; its
  `FixTarget` is `("forced_friends", group_id)`, which `fix_focus` turns into
  the group's editor, opened for the group a still-broken "Go fix" points at). `Competition.forced_groups` carries the
  groups (`mutations._build_competition`, `attending()`). Mutations:
  `add_group` / `update_group` / `dissolve_group`; a create, or an edit of
  people or axes, marks an existing roster stale, a rename does not, and a
  dissolve does only if the group was active with two placed active members
  currently satisfying it (`_was_pulling`). Only registered people can be
  picked (a member already in the group is kept even when not registered).
  `list_groups` also gives each group a `status` (`active` / `dormant` /
  `violated`, the last from `mutations.broken_rules`, so never before a roster
  and never for a dormant group) and its `violations` lines; the tab's badge and
  the fold-out "Edit group" form read them. `mutations.grid_forced_groups(state)`
  gives the grid `{helper_id: ["Rodina (same Building, Room)"]}` for the active
  members of groups in force (a dormant group marks no one), passed as each
  helper's `forced_groups` prop; `HelperChip` shows a link mark whose tooltip
  lists them. The one blocking edit-time check is `forced_friends.tag_clashes`
  (the members' `tags.allowed_values` intersected per shared Building/Role axis;
  Room is judged as Building; a member with an empty allowed set of their own
  is left to the Helper dead-end check; Can't attend and unregistered members
  are not counted). `forced_groups._refuse_tag_clash` runs it on `add_group`
  and on an `update_group` that changes people or axes (a rename never blocks,
  and an already-clashing group can only be edited towards holding), and
  `mutations._stranded` / `_refuse_new_dead_ends` carry group clashes as
  `(group id, axis, "group")` entries next to the Helper dead ends, so
  `set_helper_tags`, `add_tag_to_helpers` and `update_tag` refuse a Tag change
  that newly empties a group's intersection. Not built yet: "make forced" and
  Organizer members (#61), the import section (#62).
  Helper ones and have no UI yet. Organizer Can't attend/Tags are separate,
  later tickets (the Organizer record already may carry a direct-Tag id list,
  `tags`, which promotion fills; nothing else reads it yet).
  Friend references: a Helper's `friends` is one list of unified references —
  a plain int is a Helper id, `{"organizer_id": n}` (`OrganizerRef` on the
  domain `Helper`; `serialize.friend_ref_to_json`/`friend_ref_from_json`) an
  Organizer; `mutations._friend_key` is their comparable form. Ingestion:
  `parse_raw_survey(path, organizers=...)` puts the Season's Organizers in the
  name-resolution pool next to the Helpers (same normalized/fuzzy matching, a
  Helper wins a shared name; `upload_responses` passes them), and
  `resolve_friend` takes `resolved_organizer_ids` too. Scoring:
  `scoring.build_organizer_requests` (none under `mutual`) feeds a term in
  `solve_competition` at the Helper-to-Helper weight — satisfied by the exact
  (Building, Room) when the Organizer has a Room, by any Room of the Building at
  Building level, never when unplaced; Organizers are constants there, never
  variables. `build_friend_pairs`, `SolveResult.*_friend_pairs`, the diagnostics
  and the grid's friend hover stay Helper-to-Helper only. `mutations.promote_helper`
  (confirmation like Can't attend when the Helper has an Assignment or Manual
  role entries) creates the Organizer (Person link with `link_confirmed` /
  `rejected_person_ids`, name, e-mail, `tags`), removes the Helper, and re-points
  others' `friends` and `friend_name_decisions` via `_repoint_friend`;
  `delete_organizer` drops an Organizer from them like `delete_helper`. A
  re-upload still replaces the whole Helper list, so it brings a promoted
  Helper back into the pool.
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
  re-upload (the recognized record is updated in place); `Workspace` gives a
  state saved before Tags existed an empty tree on read. UI: `tabs/tags_tab.py`
  (the "3. Tags" tab) and `tabs/helper_tags.py` (a fragment above the Upload
  tab's Helper table), both drawing pills through `tag_pills.py`.
- Tag import (`mutations.py`, "Tag import" section; UI in
  `tabs/tag_import_ui.py`): `import_from_season(workspace, source_season_id)`
  runs every `ImportSection` in `_IMPORT_SECTIONS` (`register_import_section`;
  Tags is the first, Forced friends will add a second) over one earlier stored
  Season (read through `Workspace.stored_state`, never written) against the open
  state, saved once, and returns `{"source", "sections"}`; the Tags section
  summary has `tags_created`, `tags_restored`, `tags_reused`, `helpers_tagged`,
  `dropped_constraint_entries`, `skipped_assignments`, `awaiting_review` and
  display `lines`. Offer helpers: `import_sources`, `default_import_source`,
  `tag_import_offer` (also the `banner` flag). A Tag record gains `origins`, a
  list of `{season_id, tag_id}` (a copy gets one; a same-name Tag already there
  is matched and gains one, without being changed), and the state gains
  `tag_imports`: source Season id -> `{label, deleted_tag_ids}` (`delete_tag`
  records a deleted imported Tag there, so an explicit re-import restores it and
  reports it; Class promotion adds `promoted_years` and `unpromoted_tag_ids` to
  the same entries). Tags are resolved origin first, then name (`_resolve_import_tag`),
  the name being the source Tag's as promoted so far (`_imported_name`), by the
  import, and by the late-link step `late_link_tag_offer` /
  `apply_late_link_tags` (the Person's direct Tags in every imported Season;
  never recreates a deleted Tag). Applying Tags to a Helper goes through
  `_add_valid_tags`, which skips (not refuses) what would newly strand them.
  Not done yet: Organizers receiving Tags on import (they do not exist).
- Class promotion (`mutations.py`, "Class promotion" section; the pure name
  rules `tags.is_class_name` / `promoted_class_name`, the year rule
  `season_label.school_years_crossed`; UI in `tabs/tag_import_ui.py`):
  `class_promotion_offer(workspace)` returns `suggestions` (class Tags with an
  origin that are a school year behind: `tag_id`, `name`, `target`, from the
  Tag's newest origin's Season label read fresh, so a rename of the source is
  followed), `other_tags` (everything else, `target` = the exact current name,
  for adding by hand) and `nothing_to_promote`; the years crossed are never
  exposed. `apply_class_promotion(workspace, {tag_id: target})` renames all
  ticked Tags at once in place (a target equal to the current name is no rename),
  refusing with `RosteringError` on what `class_promotion_conflicts` lists (an
  empty name, or a target another Tag keeps or is renamed to, case-insensitive;
  no merging). It also records, per source in `tag_imports`, `promoted_years`
  and `unpromoted_tag_ids` (source Tag ids of suggestions left unticked, still
  suggested next time). `import_from_season` returns `promotion_prompt` (current
  label podzim and a school year crossed), which makes the Upload/Tags tab open
  the dialog by itself (`_class_promotion_auto`); the Tags tab has an
  always-available "Promote classes" button.
- Roster grid Tag pills and filter: `mutations.grid_tag_pills(state)` (each
  Helper's `{direct, implied}` pills as `{name, colour}`, from `helper_tags`) and
  `mutations.dimmed_helper_ids(state, tag_ids, mode)` (over the pure
  `tags.matches_filter`: all-of / any-of, inherited Tags count, an empty filter
  or an unknown Tag id matches everyone) feed `grid_tab._render_tag_controls`
  (the "Show tags" toggle, the "Filter by tags" multiselect in tree order and
  the All of / Any of radio; the widget state lives under `_grid_show_tags` /
  `_grid_tag_filter` / `_grid_tag_mode`, pruned of deleted Tags on each run and
  dropped when another Season opens). The component takes each helper's `tags`,
  `show_tags` and `dimmed_helper_ids`: pills render inside `HelperChip` (Roster
  cells and the Unassigned pool, not the typed Manual role chips), dimming is a
  `dimmed` class (opacity, restored on hover so the hover card stays readable).
  The controls are always shown, the filter merely disabled while the Season has
  no Tags. Covered by `tests/test_grid_tags.py` and the smoke script
  (`scripts/e2e/smoke.mjs`).
- Tag constraints: a Tag record also carries `building_allow`, `building_deny`,
  `role_allow`, `role_deny` (lists of Building names / `Role.name`s, absent =
  empty; `Tag` in `rostering/tags.py` holds them as tuples). The single source
  of truth for what a Helper may do is `tags.restrictions` / `blocking` /
  `allowed_values` (a pure function of the Tag tree, the Helper's direct Tag
  ids and the axis universe: the Season's configured Buildings, or the six
  Roles), used by the solver's `tag_restrictions` `RuleFamily`
  (`solver/rules.py`, tier between minimums and Forced friends), the live
  checker and the edit-time validation. `Competition.tags` and `Helper.tags`
  (direct ids, read from the record's `tags`) carry them to the solver.
  Entries naming nothing in the universe are inert (an allow-list of only
  such entries does not narrow); Buildings are matched with `building_keys`,
  as Building preferences are. The relaxation has one instance per Helper and
  disallowed Building/Role (`tag_building` / `tag_role`, entity `(helper id,
  value)`), so the solver's line and the checker's are identical, and its
  `FixTarget` is `("tags", helper_id, tag_id)` (the first Tag that excludes
  the placement), which `fix_focus.go_fix` turns into `tags_tab.focus_tag`.
  Validation is one shared step in `mutations` (`_stranded` /
  `_refuse_new_dead_ends`), run by `set_helper_tags`, `add_tag_to_helpers` and
  `update_tag`: it refuses an edit that leaves a Helper with an empty allowed
  set that they did not already have, so a Helper stranded by a later
  configuration change never blocks unrelated edits; deleting a Tag or
  removing one from a Helper only widens, so is not checked. Read-side
  helpers: `mutations.helper_allowed` and `tag_constraint_entries` (which
  flags `in_season`).
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
