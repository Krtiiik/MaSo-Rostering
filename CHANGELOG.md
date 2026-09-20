# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
