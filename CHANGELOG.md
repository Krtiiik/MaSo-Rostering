# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The overlay role "Uvaděči / Předávání cen" is now two separate,
  room-scoped roles: **Uvaděči účastníků** and **Focení předávání cen**.
  Both can still be filled by typing/picking a name, and now also accept
  dragging a helper's existing chip directly onto the overlay cell for the
  room they're already solved into — this duplicates them into that
  overlay slot (shown with a dotted chip border to mark it as a
  duplicate) without moving their solved-role assignment. A cross-room
  drop (a different room than the helper's own) is rejected.

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
  purple = someone else requested to room with them).
- `StructuralAssignment`/`OverlayAssignment` (`rostering.domain`) now
  accept a `helper_name` in addition to `helper_id`, for manual-role
  entries referring to someone who isn't a registered helper.

### Changed

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
