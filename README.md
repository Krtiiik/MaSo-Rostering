# Rostering

Assigns registered helpers (*pomocníci*) to buildings, rooms and roles for the
MaSo math competition, based on their preferences, and lets you tidy up the
result by hand before exporting it to Excel.

The app's interface is in Czech.

## Getting started (using a release)

You do not need Python or any other tool installed. Download the build for
your system and run it.

1. Open the [latest release](https://github.com/Krtiiik/MaSo-Rostering/releases/latest)
   and download the archive for your platform:

   | Platform | File |
   |---|---|
   | Windows | `rostering-vX.Y.Z-windows-x64.zip` |
   | Linux | `rostering-vX.Y.Z-linux-x64.tar.gz` |
   | macOS (Apple silicon) | `rostering-vX.Y.Z-macos-arm64.tar.gz` |

2. Extract the archive. You get a `rostering` folder; keep everything in it
   together.
3. Run `rostering.exe` (Windows) or `rostering` (Linux/macOS) from inside that
   folder. On Windows a double-click is enough.
4. Your browser opens the app at <http://127.0.0.1:8000>. Keep the program's
   window open while you work; closing it stops the app.

The builds are not code-signed, so your system may ask you to confirm that you
want to run the program the first time.

### What the app does

The six numbered tabs along the top follow the order of the work:

1. **Lidé** (People) — load the helpers' Google Forms export with
   "Načíst pomocníky" (and, optionally, the organizers' with "Načíst
   organizátory"). The first upload creates a Season.
2. **Štítky** (Tags) — label people and restrict where a tag's carriers may
   work.
3. **Vynucené skupinky kamarádů** (Forced friends) — groups that must end up
   together.
4. **Budovy** (Buildings) — buildings, rooms and how many helpers each role
   needs.
5. **Parametry rozřazování** (Solver) — the solver's weights.
6. **Rozdělení pomocníků** (Roster) — solve, then drag helpers between cells to
   adjust the result, and export it to Excel.

Anything waiting on a decision (possible returning helpers to link, what a
re-upload changed, ...) collects in the **K vyřízení** panel behind the
checklist button in the header. Named versions of the roster can be saved,
restored and deleted from the left drawer.

A step-by-step guide in Czech, with screenshots, is in
[docs/manual/navod.md](docs/manual/navod.md).

### Your data

Every Season (a year plus `jaro` or `podzim`, e.g. `2026-jaro`) is stored
automatically and can be opened, renamed or deleted from the **Ročníky** panel
in the left drawer. The data is kept in a `data/` folder created in the folder
you start the program from — for the executable, the extracted `rostering`
folder if you double-click it. It holds real helpers' personal data, so do not
share or publish it. To move to a new version of the app, copy your `data/`
folder next to the new one.

## Running from source

For development, or if you would rather not use a release:

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
rostering serve
```

That is the whole setup: the web app has no frontend build step (no Node/npm).

`rostering serve` opens http://127.0.0.1:8000 in your browser. Options:
`--port` to change the port, `--headless` not to open a tab, `--reload` to
restart the server on code changes while you work on it.

For a throwaway run that does not touch your real data, set
`ROSTERING_WORKSPACE_DIR` (Seasons then live under `<dir>/seasons`) or
`ROSTERING_SEASONS_DIR`.

### How the web app stores things

A single-process [NiceGUI](https://nicegui.io) app — no separate
frontend/backend split. Each Season lives in its own directory
`data/seasons/<label>/` (saved state in `state.json`, its Versions in
`versions/`), next to any hand-placed `raw-response.xlsx`/`config.yaml`; the
open Season is recorded in `data/seasons/open-season.json`. Everything is under
`data/` (gitignored, since it holds real helper data). A state saved by an
earlier version (`data/workspace/`) is moved into a Season on first launch.

The sidebar's Seasons panel can export chosen Seasons (with or without their
Versions) to one `.zip` and import such a file elsewhere — to move to another
machine, hand a Season to a colleague, or seed a fresh install. Before an import
changes anything, the stored Seasons are backed up as a `.zip` in `data/backups/`
(next to `data/seasons/`).

A new Season starts with no buildings. Bring the layout in from an earlier
Season (the "Rozložení budov" part of the import from an earlier Season), load it
from the "Pomocníci v místnostech" sheet, or enter it on the Buildings tab; it is
saved with the Season like everything else.

The app's code lives in `rostering/webapp/`: `mutations.py` and
`forced_groups.py` hold the UI-free state-mutation functions, and `ui/` the
NiceGUI screens (`ui/app.py` is the page, `ui/tabs/` one module per tab). The
drag-and-drop roster grid is `ui/grid/`: Python builds its HTML and a small
hand-written JavaScript module (`roster_grid.js`, served as is) handles the
dragging and clicking. See [CLAUDE.md](.claude/CLAUDE.md) for the domain
glossary and implementation notes.

## Building an executable locally

Every `vX.Y.Z` tag push builds and publishes the standalone executables to
that tag's [GitHub Release](../../releases) via
`.github/workflows/build-executables.yml`. To build one yourself:

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
