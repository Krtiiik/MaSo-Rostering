# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add, edit and delete a Helper by hand: an "Add a helper by hand" form on the
  Upload tab needs only a name and a contact (a blank name or contact is
  rejected; a name or e-mail another Helper of the Season already has shows a
  warning but does not block). An e-mail-shaped contact is stored as the
  Helper's e-mail, so it takes part in Person matching (and links to the same
  Person if an earlier stored Season recorded that e-mail); any other contact
  is kept as a display contact and matching falls back to the name. Everything
  else is optional and defaults like a blank survey row: no Role preferences
  (each reads as Nevadí), no Building preference, no equipment, no friends,
  T-shirt size Unknown. The new Helper gets a fresh Helper id that is never
  reused, and is solved, shown in the grid, tagged and flagged Can't attend like
  any other, with no visual distinction. "Edit or delete a helper" changes any
  field at any time (an edit never moves anyone) and deletes a Helper; deleting
  one who holds an Assignment or Manual role entry asks first, exactly like
  Can't attend, then clears the Assignment (and its lock) and those entries and
  marks the roster stale. A deleted Helper is also dropped from other Helpers'
  Friend preferences (a friend name resolved only to them goes back to
  unresolved). The record remembers which fields were typed by hand.
- Can't attend: a "Can't attend" checkbox on every Helper row of the Upload
  tab's Helper list takes an absent person out of the picture. A flagged Helper
  is left out of the solver, the roster grid, the Unassigned pool, the
  Broken-rule check and the Excel export (roster sheet, T-shirt and per-Building
  sheets), with no special look in the grid, and a Friend preference naming them
  silently stops scoring (it is kept, so un-flagging restores it). Flagging a
  Helper who has no Assignment or Manual role entry applies at once. Flagging
  one who does asks first, naming what will be cleared; confirming clears their
  Assignment (and its lock) and every Organizer role and Additional role entry
  holding them, and cancelling changes nothing. Un-flagging only clears the flag:
  it restores nothing and does not re-solve, so the Helper returns to the pool
  for the next Solve. The flag is kept when the same Helper re-submits the
  survey (matched by e-mail, like a Returning helper), is per Season, and is
  saved with Versions. A flagged Helper can't be placed by hand.
- Stale-roster banner: clearing a placed Helper this way marks the roster stale.
  A banner with the reason appears next to the Solve button (and on the Upload
  tab), Export to Excel is disabled while it is up, and the next full Solve
  clears it. The flag is saved with Versions and reusable by any edit that
  invalidates a roster without moving anyone.
- Lock controls in the roster tab's bottom bar: "Lock all placed", "Clear all
  locks", a live "N locked" count, and a Solve button that reads "Solve (keeps N
  locked)" while any lock is set. A full Solve (also the Buildings tab's "Save &
  solve") that would replace unlocked Assignments first asks "N unlocked
  Assignments will be replaced", and does not ask when nothing would be lost. A
  Solve that had to drop locks because their Room or Building was removed says
  so ("N locks dropped: Room X no longer exists"); removing a Room is never
  blocked or prompted in the Buildings tab. Locking operations don't affect the
  Broken-rule check or the Excel export, saved Versions restore locks (an older
  Version without the flag restores as unlocked), and "Start over" clears them.
- Locked Assignments: a placed Helper's whole Assignment (Building, Room and
  Role) can be locked so that a full Solve keeps it and re-places everyone else
  around it. Ctrl/cmd-click a chip, or press the Lock/Unlock button on its hover
  card, to toggle the lock; a plain click and a drag are unchanged (a drag now
  starts only after the pointer has moved a few pixels), dragging a locked chip
  moves the lock with it, dragging an unlocked chip never locks it, and dropping
  a chip on an Additional-role overlay cell leaves the lock alone. A locked chip
  shows a padlock and a heavier solid border. Locked Helpers count toward Room
  and Building minimums and Friend-preference co-location, a locked Assignment
  that breaks a rule is still kept, and a lock whose Room no longer exists is
  dropped at the next Solve. Locks are saved with the Season and its Versions
  and are not written to the Excel export.
- A solve never fails because the hard rules clash. Room and Building
  minimums and Equipment eligibility now bend in a fixed order (minimums
  first, Equipment last, with room reserved for Tag restrictions and
  Forced-friend groups in between) and the solver always returns a full roster,
  keeping the ordinary preference and friend objective among rosters that
  break equally few rules. What it had to bend is printed by
  `rostering solve` and shown in the roster tab's Broken-rule banner (below).
  Export is not blocked by a bent rule.
- Live Broken rules: the roster tab now checks the current Assignments against
  the current rules on every render (nothing is stored) and shows a warning
  banner above the grid, replacing the status caption, with one line per broken
  rule grouped by family (Room and Building minimums as counts, e.g. "Room N4 ·
  Fotograf: 1 of 2 required (needs 1 more)", and Equipment, e.g. "Helper X has
  no camera but is Fotograf"). A family with more than ten broken instances
  collapses into an expandable summary. Each line has a "Go fix" button that
  switches to the Buildings tab (minimums) or the Helper list on the Upload tab
  (Equipment) and marks what to fix there until the rule holds again. The
  drag-and-drop grid lightly marks the affected Room headers, role cells and
  helper chips. A hand move is still never refused, and a drop that newly
  breaks Equipment eligibility shows a transient toast worded like the banner
  (nothing for a rule that was already broken, and never for minimums, which
  only appear in the banner and the grid marks). Export is never blocked and the
  exported sheet is unchanged by Broken rules.
- A "Time limit (seconds)" setting on the Buildings tab's solver settings.

- Uncertain-match review list: after an export is loaded, the Upload tab lists
  every Helper who has the same name as someone from an earlier Season (or
  another row of the same export) but no matching e-mail, with that Person's
  name, Season and e-mail and the phone as a hint (the survey's phone column is
  now read, for display only). Each candidate offers "Link" or "Not the same
  person"; a Helper with several candidates picks one or none. Unreviewed
  candidates stay unlinked, a rejected pairing is never proposed again, and a
  confirmed link is remembered independently of e-mail. A "Person links"
  expander on the Upload tab unlinks any Helper's link or links them by hand to
  any past Person; link edits never change a Helper id. Links and rejections
  are rolled back by Versions.
- Returning helpers are recognized across Seasons. The survey's e-mail column
  is now read at upload whatever its header wording (e.g. "E-mailová adresa",
  "Email Address", "Tvůj e-mail") and compared trimmed and lower-cased; a Helper
  whose e-mail matches one recorded in any stored Season is linked to the same
  Person automatically, even if their name changed (the most recent appearance
  wins if the e-mail is on record for several). Phone numbers are never used.
  The Upload tab counts Returning helpers and shows the earlier Seasons each
  was in. A Person exists only through the Seasons that record them, so Start
  over and deleting a Season forget what only they knew. Same-name rows
  without a matching e-mail are not linked automatically (see the review list
  above); an export without an e-mail column warns once.
- Duplicate rows in one export with the same e-mail now collapse to one Helper,
  the latest submission winning, with an upload warning naming who was
  collapsed; rows with different or blank e-mails are never merged.
- Stored Seasons: every Season is now a stored, labelled unit (a year plus
  `jaro`/`podzim`, e.g. `2026-jaro`; unique among stored Seasons, editable,
  and the key that orders them in time) in its own directory
  `data/seasons/<label>/` with its saved state and its Versions, and the
  Workspace is the open Season. Uploading with no Season open creates one,
  with the label prefilled from the export's submission timestamps (January to
  June is jaro, July to December is podzim) and editable; when the timestamps
  can't be read the label is asked for. Uploading while a Season is open is
  always a re-upload into it. The open Season's label shows in a header above
  every tab and can be renamed there (a rename renames the directory; a stable
  Season id survives it).
- A Seasons panel in the sidebar lists every stored Season (label, Helper
  count, open or stored) with Open, Rename and Delete (not offered on the open
  Season; the confirmation names what is lost, and the Season's Versions are
  deleted with it), and a "New Season" button that opens a blank Season.
- The first launch after this change moves an existing saved state and its
  Versions from `data/workspace/` into a Season (asking once for the label,
  prefilled from the file's date, since the old state kept no export
  timestamps). A Season directory with no saved state (e.g. a hand-placed raw
  export) is ignored.
- The exported roster draws a Large room across two columns in every Role
  band, automatically (no setting): a Room whose Room-band Helpers
  (Opravovatel to Fotograf; Záloha and Manual roles excluded) number at least
  1.5 times the median Room on the sheet, provided it is taller than the
  other Rooms in at least one band. The first column of each band fills to
  the tallest ordinary Room's height (raised if the Large room would need
  more than two columns), the second takes the rest, unused slots stay grey;
  the Room header and the Vedoucí místností / Pravá ruka cells merge across
  both columns and Building headers and Building-wide rows span the extra
  column. Fewer than three Rooms with Helpers, or a Room merged with a
  neighbour, never overflow. The in-app grid is unchanged. A Room merged for
  a Role stays one wide cell (one name per row) and may stretch that band
  only; a Large room in the same band fills its first column down to the
  stretched height, and needs a second column only if it is still taller
  than that height (the merged group's configured minimums count too).
- T-shirt size: each Helper now has a size (XS, S, M, L, XL, XXL, or
  Unknown), read from the survey question "Tvoje velikost trička" (matched
  ignoring case and surrounding whitespace). A blank, "?" or free-text
  answer becomes Unknown and adds an upload warning naming the Helper and the
  raw text; an export without the column warns once and leaves every Helper
  Unknown. The size is saved with the workspace (workspaces saved earlier
  load as Unknown) and in the helpers CSV written by `rostering ingest`
  (older CSVs without the column load as Unknown).
- A Helper's T-shirt size can be fixed by hand: the Helper list on the Upload
  tab shows a "T-shirt size" column with a dropdown (XS to XXL, or Unknown) to
  resolve the Unknowns flagged by the upload warnings. The edit is saved with
  the workspace and shows in the "Trička" sheet and per-Building lists of the
  next export. A size outside that set is rejected. (A hand-set size is not
  yet kept when a newer survey export is re-uploaded; re-upload still replaces
  all Helpers.)
- The exported workbook has a new "Trička" sheet right after the roster:
  T-shirt counts per size (XS to XXL, plus an Unknown row only when someone
  counted is Unknown) for each Building with Rooms, with a Celkem column and
  a total row, for the shirt order. It counts every solved Helper in their
  solved Building plus everyone holding an Organizer role in the Building
  that role names, each person once; a hand-typed-name Organizer-role holder
  counts as Unknown and an Organizer-role entry with no Building is not
  counted.
- The exported workbook now also has one helper-list sheet per Building with
  Rooms, after "Trička", in config order, for a Building lead to print:
  columns Jméno, Velikost trička, Místnost and Role (no phone numbers, no
  (n)/(f) tags). It lists the same people as "Trička", each once, sorted by
  Czech collation on the full name as entered ("ch" after "h", diacritics as
  tie-breaks; implemented in code, independent of the machine's locale). A
  Helper shows their solved Room and Role; an Organizer-role holder shows
  their Organizer role(s) instead (e.g. "Vedoucí budovy"), with the Room left
  empty when placed only at Building level. Sheet names are the Building name
  without `/ \ ? * [ ] :`, cut to Excel's 31 characters and made unique (a
  " (2)" suffix) if that makes two collide or clash with the roster or
  "Trička" sheet.

### Changed

- A solve that finds no roster before the time limit now says "No roster found
  within N seconds" with a hint to raise the limit or solve again, keeps the
  existing roster, and is no longer reported as INFEASIBLE.
- "Start over" now empties the open Season's state but keeps its label, Season
  id and Versions (and, as before, the saved buildings layout).
- A Version snapshots the whole Season except its identity, and restoring one
  asks for confirmation, saying that Person links, rejections, Tags,
  Forced-friend groups and Assignments are rolled back; the Season's label and
  id are never rolled back.
- `ROSTERING_SEASONS_DIR` sets the Seasons directory; `ROSTERING_WORKSPACE_DIR`
  (the old saved-state location) still isolates a throwaway run, with Seasons
  under `<dir>/seasons`.

### Fixed

- Solver: a Helper's Building preference is now matched against the Season
  config's buildings ignoring diacritics, case and spacing, and recognizing
  the survey's building aliases. Previously the comparison was an exact
  string match, so a config naming a building "Mala Strana", "Karlin" or
  "Troja" never matched the survey's "Malá Strana", "Karlín" or
  "Impakt + Troja" — every stated Building preference was then treated as
  unmet for those buildings, silently skewing the solved rosters.

### Removed

- Solver: bringing a laptop is no longer a hard constraint on being assigned
  Kreslič — a helper without a laptop can now be assigned that role. Bringing
  a camera is still required for Fotograf. Whether a helper can bring a
  laptop is still tracked and still shown in the roster export (the `(n)`
  tag).

## [1.0.0] - 2026-09-22

### Added

- The overlay role "Uvaděči / Předávání cen" is now two separate,
  room-scoped roles: **Uvaděči účastníků** and **Focení předávání cen**.
  All three overlay roles (these two plus the existing **Registrace**,
  which is building-scoped instead of room-scoped) can still be filled by
  typing/picking a name, and now also accept dragging a helper's existing
  chip directly onto the overlay cell for the room/building they're
  already solved into — this duplicates them into that overlay slot
  (shown with a dotted chip border to mark it as a duplicate) without
  moving their solved-role assignment. A drop onto a different room/
  building than the helper's own is rejected.
- Roster grid: adjacent rooms' *cells* can now be merged within a single
  row — like merging cells in Excel, not the whole column. Hover a cell to
  reveal a small edge handle and click it to merge with its neighbor
  (repeat to merge a third, fourth, ...); click the "⊟" icon on a merged
  cell to split it back apart. This only affects that one row (a solved
  role, or a room-scoped manual role) — the room header and every other
  row for the same rooms stay separate. Purely a display/export grouping
  (a season config's actual rooms, and each helper's exact room
  assignment, are untouched); a merged cell shows the combined content of
  its rooms, and dropping a helper into one assigns them to the group's
  first room. Unmerged by default, matching every existing season's
  layout. Reflected in the Excel export too, using the same per-row
  merged-cell approach (`ws.merge_range`).

- Roster grid: a helper chip with an unsatisfied friend request is marked
  orange; hovering it now highlights every friend they named, wherever
  they're placed in the grid — green if that particular request is
  satisfied (co-located), red if it isn't — instead of only a generic "has
  an unsatisfied request" marker with no way to see who the request was
  with. Hovering also highlights, in purple, any other helper who named
  *them* as a friend (independent of whether it's reciprocated), so both
  directions of the friend graph are visible from one chip. All of this is
  computed from each helper's raw friend list as entered on the form, not
  from the solver's satisfied/unsatisfied diagnostics — those are collapsed
  by the friend-scoring config's mode/symmetric settings and could make a
  one-directional request look mutual or disappear entirely from the grid.
- Roster grid: hovering a helper chip now shows a card with that helper's
  preferred building(s), a star-rating list of their preference for each of
  the 6 roles, and their friend requests — color-coded to match the grid's
  existing highlighting (green = friend co-located, red = friend elsewhere,
  purple = someone else requested to room with them). The card appears after
  a short hover delay (so it doesn't flash while skimming across the grid)
  anchored with one corner near the cursor tip, and follows the cursor while
  it stays over the chip. The role-preference list excludes Záloha, which
  isn't offered as a choice on the form.
- `StructuralAssignment`/`OverlayAssignment` (`rostering.domain`) now
  accept a `helper_name` in addition to `helper_id`, for manual-role
  entries referring to someone who isn't a registered helper.

### Fixed

- Buildings tab: clicking "Remove room" under a room could remove a
  different room (typically the rightmost one) instead of the one the
  button was under, and could also silently carry a removed room's stale
  name/capacity values into the room that shifted into its place. Caused
  by widgets being keyed by the room's position in the list rather than
  the room itself.

### Changed

- Upload tab's "Resolve friend names" now lets an unresolved name be matched
  to more than one helper (via a multi-select instead of a single-select),
  for cases where a free-text name actually refers to a group of people
  rather than one individual.
- Roster grid: the Vedoucí budovy, Pravá ruka, and Vedoucí místností manual
  role cells are now plain free-text input, with no autocomplete against
  registered helper names and no attempt to resolve a typed name to a
  helper record — these roles are typically filled by people (teachers,
  organizers) who never registered as a helper. Overlay roles and
  Technická podpora, which layer onto an already-registered, already-
  assigned helper, keep the registered-helper autocomplete.
- Roster grid: the Vedoucí budovy, Pravá ruka, and Vedoucí místností cells
  now hold at most one name each, since each is a single-holder role (one
  building lead, one deputy, one lead per room) — the add-input hides once
  a name is set, and an existing name must be removed before a new one can
  be entered.
- Pravá ruka (building lead's deputy) is now scoped per room instead of per
  building, matching Vedoucí místností — each room can have its own deputy.
  Applies to the roster grid, the Excel export, and the manual-roles YAML
  loader (`room:` is now meaningful for both roles).
- Excel roster export now matches the layout and styling of the historical
  hand-built rosters: a single sheet (previously split across a "Roster"
  sheet and a separate overlay sheet) with the structural roles (Vedoucí
  budovy, Pravá ruka, Vedoucí místností) listed above the 6 solved roles,
  followed by the overlay roles (Uvaděči / Předávání cen, Registrace),
  Záloha, and Technická podpora — plus matching per-role label/data cell
  colors, a bordered grid, Arial font, frozen first column, and "(n)"/"(f)"
  equipment tags appended to helper names. Empty helper slots (a role's
  row-block sized larger than a room's actual headcount) now get a neutral
  soft-gray fill instead of the role's color, so an empty slot reads as
  empty rather than as another filled cell in that role's block. Column
  widths are now sized to roughly fit their content instead of a fixed
  width for every column.
- Roster tab: the manual structural/overlay roles (Vedoucí budovy, Pravá
  ruka, Vedoucí místností, Uvaděči / Předávání cen, Registrace, Technická
  podpora) are now extra rows in the same assignment grid instead of a
  separate section of selectboxes/multiselects below it, matching the
  historical hand-built roster layout. Their cells are not drag-and-drop
  targets; each has a name input with autocomplete suggestions from
  registered helpers, plus the ability to type a new name for someone who
  isn't a registered helper (manual roles are commonly filled by people who
  never registered).

### Removed

- The per-role *maximum* headcount setting (buildings/rooms config, the
  Buildings tab's "Max" column, and the corresponding CP-SAT upper-bound
  constraint) — helper counts are small enough that capping a room's
  headcount was never actually needed. Only the *minimum* headcount setting
  remains. Older config files with a `{min, max}` mapping still load; `max`
  is now silently ignored.

### Fixed

- Excel roster export: a role's row-block was sized only from its
  configured *minimum* per-room headcount, so a room where the solver
  actually placed more helpers than that minimum (capacities are usually
  unbounded above) overflowed into the next role's rows instead of
  expanding its own block.

## [0.3.0] - 2026-09-21

### Changed

- The "Continue", "Save & solve", and "Solve"/"Export to Excel" buttons in
  each tab now live in a floating bar anchored to the bottom of the
  viewport (`st.bottom`) instead of being placed inline within each
  tab's content, so the main action is always in the same spot regardless
  of scroll position or which tab is active.

### Fixed

- Friend-name resolution (upload tab): picking a match (or dismissing)
  from a name's selectbox made that row disappear immediately, so the
  choice couldn't be reviewed or changed afterwards. The row now stays
  visible with the current decision selected, and re-picking it updates
  the friend link instead of duplicating or losing it.
- Buildings & rooms tab: the "+ Add room" column now stretches to match
  the capacity grid's actual height instead of a fixed, overly tall
  min-height. The "Remove building" button moved to the left of the
  building name field and is bottom-aligned with it.
- Buildings & rooms tab: the "+ Add room" column's height-matching CSS
  from the fix above still ballooned it to roughly the full page height
  in practice, because filling it via plain nested `height: 100%` triggers
  a Chromium flexbox layout runaway (each reflow re-measures a stale,
  ever-growing ancestor height). It's now anchored with absolute
  positioning against its already-correctly-stretched column instead,
  which can't feed back into an ancestor's auto-height calculation.
- Roster grid: helper names assigned to the same room/role cell were laid
  out horizontally, overflowing the cell instead of stacking. Cells now
  stack names vertically, one per line.
- Roster grid: the previous fix applied `display: flex` directly to each
  `<td>`, which overrides its table-cell display and made the browser
  collapse every room's column into the first one — all buildings' helpers
  visually piled into a single leftmost column. The flex-column layout now
  lives on an inner wrapper `<div>` inside each cell instead, so rooms keep
  their own columns while names still stack vertically within each cell.
- Roster grid: helpers within a cell, and in the "Unassigned" pool, are now
  always sorted by name instead of following assignment/upload order.

## [0.2.0] - 2026-09-20

### Added

- `rostering` with no subcommand (e.g. double-clicking the standalone
  `.exe` from Explorer) now defaults to `rostering serve`, so a
  non-technical user can launch the app without knowing about the CLI.

### Fixed

- Standalone executable: `rostering serve` crashed with
  `FileNotFoundError: ... rostering\streamlit_app\app.py` because
  `packaging/rostering.spec` only force-collected `streamlit`, `ortools`,
  and `rostering_assignment_grid` — the `rostering` package itself was left
  to PyInstaller's static import-graph analysis, which never discovers
  `rostering.streamlit_app.app` since it's only ever loaded by file path
  (via `streamlit.web.bootstrap`), never `import`ed. The whole
  `streamlit_app/` package was silently missing from every frozen build.
  Now `rostering` is `collect_all`'d too, and the build workflow verifies
  `app.py` actually lands in the bundle (the prior `serve` smoke test only
  curled `/`, which succeeds even with a broken script since script
  execution only starts once a browser session connects).

### Changed

- Buildings tab: the per-building capacity editor is now a single horizontal
  table (role rows, building-wide Min/Max columns, then a Min/Max column
  pair per room) using `number_input` steppers instead of a vertical
  `data_editor` per room, with remove-room buttons under each room and a
  vertical "+ Add room" button alongside the table.

## [0.1.0] - 2026-09-20

### Added

- GitHub Action (`.github/workflows/build-executables.yml`) that builds and
  publishes standalone Windows/Linux/macOS executables of the `rostering`
  CLI/app via PyInstaller, attaching them to a GitHub Release on `vX.Y.Z`
  tag pushes (or as workflow artifacts on manual dispatch).

### Changed

- `rostering serve` now launches Streamlit in-process via
  `streamlit.web.bootstrap` instead of shelling out to
  `sys.executable -m streamlit`, and explicitly disables Streamlit's
  `global.developmentMode`. Both are needed for the app to run correctly
  from a frozen executable (where `sys.executable` isn't a Python
  interpreter and Streamlit's own `__file__`-based install detection gets
  confused), but apply equally to normal installs.
