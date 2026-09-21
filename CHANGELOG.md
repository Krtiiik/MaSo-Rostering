# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Roster grid: helper names assigned to the same room/role cell were laid
  out horizontally, overflowing the cell instead of stacking. Cells now
  stack names vertically, one per line.
- Roster grid: the previous fix applied `display: flex` directly to each
  `<td>`, which overrides its table-cell display and made the browser
  collapse every room's column into the first one — all buildings' helpers
  visually piled into a single leftmost column. The flex-column layout now
  lives on an inner wrapper `<div>` inside each cell instead, so rooms keep
  their own columns while names still stack vertically within each cell.

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
