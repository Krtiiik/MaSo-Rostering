# Contributing

This is the developer guide. For what the app does and how to install a
release, see the [README](README.md).

## Where things are documented

- [CONTEXT.md](.claude/CONTEXT.md): the project's glossary (Season, Helper,
  Organizer, Building, Room, Role, ...) and the Czech front-end rules. Use these
  terms exactly in code, commits and discussion.
- [ARCHITECTURE.md](.claude/ARCHITECTURE.md): components, data flow, the
  reasons behind design choices and the implementation notes. Read it before
  changing structure or adding a component.
- [CLAUDE.md](.claude/CLAUDE.md): the working rules (commits, changelog, tests)
  for the AI assistant used on this project; they apply to people just as well.

The web app's front end is in Czech (every user-facing string); code,
identifiers and developer docs stay English.

## Running from source

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
rostering serve
```

That is the whole setup: the web app has no frontend build step (no Node/npm).

`rostering serve` opens <http://127.0.0.1:8000> in your browser. Options:
`--port` to change the port, `--headless` not to open a tab, `--reload` to
restart the server on code changes while you work on it.

For a throwaway run that does not touch your real data, set
`ROSTERING_WORKSPACE_DIR` (Seasons then live under `<dir>/seasons`) or
`ROSTERING_SEASONS_DIR`.

## How the web app stores things

A single-process [NiceGUI](https://nicegui.io) app — no separate
frontend/backend split. Each Season lives in its own directory
`data/seasons/<label>/` (saved state in `state.json`, its Versions in
`versions/`), next to any hand-placed `raw-response.xlsx`/`config.yaml`; the
open Season is recorded in `data/seasons/open-season.json`. Everything is under
`data/` (gitignored, since it holds real helper data). A state saved by an
earlier version (`data/workspace/`) is moved into a Season on first launch.

Importing Seasons from a `.zip` backs the stored Seasons up as a `.zip` in
`data/backups/` (next to `data/seasons/`) before changing anything.

## Code layout

The app's code lives in `rostering/webapp/`: `mutations.py` and
`forced_groups.py` hold the UI-free state-mutation functions, and `ui/` the
NiceGUI screens (`ui/app.py` is the page, `ui/tabs/` one module per tab). The
drag-and-drop roster grid is `ui/grid/`: Python builds its HTML and a small
hand-written JavaScript module (`roster_grid.js`, served as is) handles the
dragging and clicking.

## Tests

Tests use pytest (with pytest-asyncio) in a flat `tests/` folder, one
`test_<feature>.py` per feature. The web app tests drive NiceGUI's async user
simulation.

```
python -m pytest -q
```

The full suite takes about 90 seconds. While working on a change, run the file
for the area you touched first, e.g. `python -m pytest tests/test_tags.py -q`.

- Reproduce a bug with a failing test before fixing it, and keep that test.
- Ship tests with new or changed behaviour in the same change.
- When a test fails, fix the code; change a test only when it is wrong or the
  requested behaviour changed.

## Commits and changelog

- Commit messages use [Conventional Commits](https://www.conventionalcommits.org/)
  prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`, ...) with a
  short imperative summary, and an optional `(scope)` when the change is
  confined to one area. One logical change per commit.
- `CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/): log
  every user-facing change under `## [Unreleased]` in the same commit as the
  change.
- Versions follow [Semantic Versioning](https://semver.org/).

## Releasing and building executables

A release means moving `[Unreleased]` under a new `## [X.Y.Z] - YYYY-MM-DD`
heading, bumping `version` in `pyproject.toml` to match, and tagging the commit
(`git tag -a vX.Y.Z -m "vX.Y.Z"`). Pushing a `vX.Y.Z` tag builds the standalone
executables and publishes them to that tag's
[GitHub Release](https://github.com/Krtiiik/MaSo-Rostering/releases) via
`.github/workflows/build-executables.yml`.

To build one yourself:

```
pip install -e ".[packaging]"
pyinstaller packaging/rostering.spec --noconfirm --clean
dist/rostering/rostering --help
```

See `packaging/rostering.spec` for why this is a one-directory build (a
`dist/rostering/` folder) rather than a single `--onefile` executable.

## The Czech manual

The screenshots in [docs/manual/navod.md](docs/manual/navod.md) are generated
on made-up data by `docs/manual/tools/make_screenshots.py`; regenerate them when
the UI they show changes. The banner at the top of the README is
[docs/banner.svg](docs/banner.svg).
