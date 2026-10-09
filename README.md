# Rostering

Assigns registered helpers to buildings/rooms/roles for the MaSo math
competition. See [CLAUDE.md](.claude/CLAUDE.md) for the domain glossary and context.

## Setup

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

That is the whole setup: the web app has no frontend build step (no Node/npm).

## Usage

### CLI

```
# 1. Convert a raw Google Forms export into the canonical helpers CSV
rostering ingest raw-response.xlsx -o helpers.csv

# 2. Solve and export a roster
rostering solve config.yaml helpers.csv \
    -o roster.xlsx --manual-roles manual-roles.yaml
```

See `examples/buildings.example.yaml`, `examples/helpers.example.csv`, and
`examples/manual-roles.example.yaml` for the input file formats.

### Interactive web app

A single-process [NiceGUI](https://nicegui.io) app — no separate
frontend/backend split, no build step:

```
rostering serve
```

It opens http://127.0.0.1:8000 in your browser (`--port` to change it,
`--headless` not to open a tab). Upload the raw survey export on the People
tab, then use "Pokračovat na štítky" and work through the Tags, Forced
friends, Buildings and Solver tabs, solve, then drag helpers between cells on
the Roster tab to adjust. Everything that waits on a decision (possible
returning helpers to link, the Tag import offer, what a re-upload changed)
collects in the "K vyřízení" panel behind the checklist button in the header.
Save named versions, restore/delete them from the left drawer, and export the
current roster to Excel from the Roster tab.

Every Season is stored and labelled (a year plus `jaro`/`podzim`, e.g.
`2026-jaro`). Uploading with no Season open creates one, with the label
prefilled from the export's submission timestamps (editable); the sidebar's
Seasons panel opens, renames and deletes stored Seasons, and "New Season"
starts a blank one. Each Season lives in its own directory
`data/seasons/<label>/` (saved state in `state.json`, its Versions in
`versions/`), next to any hand-placed `raw-response.xlsx`/`config.yaml`; the
open Season is recorded in `data/seasons/open-season.json`. Everything is
under `data/` (gitignored, since it holds real helper data). A state saved by
an earlier version (`data/workspace/`) is moved into a Season on first
launch. For a throwaway run, set `ROSTERING_WORKSPACE_DIR` (Seasons then live
under `<dir>/seasons`) or `ROSTERING_SEASONS_DIR`.

The buildings/rooms layout is pre-filled with a default (seeded from the most
recent season's roster) and persists separately in `data/buildings-config.yaml`
— it's saved there whenever you edit it on the Buildings tab, so it survives
"start over" resets and app restarts.

The app's code lives in `rostering/webapp/`: `mutations.py` and
`forced_groups.py` hold the UI-free state-mutation functions, and `ui/` the
NiceGUI screens (`ui/app.py` is the page, `ui/tabs/` one module per tab). The
drag-and-drop roster grid is `ui/grid/`: Python builds its HTML and a small
hand-written JavaScript module (`roster_grid.js`, served as is) handles the
dragging and clicking. `rostering serve --reload` restarts the server on code
changes while you work on it.

### Standalone executables

Every `vX.Y.Z` tag push builds and publishes standalone executables (no
Python install required) for Windows, Linux, and macOS to that tag's
[GitHub Release](../../releases), via
`.github/workflows/build-executables.yml`. Download the archive for your
platform, extract it, and run `rostering` (or `rostering.exe` on Windows)
from inside the extracted folder — it's the same CLI documented above
(`ingest`, `solve`, `serve`).

To build one locally:

```
pip install -e ".[packaging]"
pyinstaller packaging/rostering.spec --noconfirm --clean
dist/rostering/rostering --help
```

See `packaging/rostering.spec` for why this is a one-directory build (a
`dist/rostering/` folder) rather than a single `--onefile` executable.

## Tests

```
pytest
```
