---
name: run-rostering
description: Build, run, and drive the rostering app (a single-process NiceGUI web app with a native drag-and-drop roster grid). Use when asked to start rostering, run its dev server, upload a survey file, take a screenshot of its UI, or interact with the running app end-to-end.
---

This is a single-process Python [NiceGUI](https://nicegui.io) app
(`rostering/webapp/ui/`, over the UI-free `rostering/webapp/mutations.py`).
There is no separate frontend, no build step and no HTTP API of our own —
`rostering serve` starts the NiceGUI server directly. The roster grid's
browser half is a plain ES module (`rostering/webapp/ui/grid/roster_grid.js`)
served as is. Drive the running app with the committed Playwright script at
`scripts/e2e/smoke.mjs` (or `npm run smoke` from `scripts/e2e/`), which
uploads a raw survey `.xlsx`, matches a friend name, solves, drags a chip in
the grid, checks the Overlays / Tag filter / details card, and screenshots
each step. Paths below are relative to the repo root.

## Prerequisites

A virtualenv with the project installed editable (`pip install -e ".[dev]"`,
per `README.md`) — that gives you the `rostering` CLI and NiceGUI. Node is only
needed for the Playwright driver (`scripts/e2e/`). Playwright needs a browser:
either its own (`npx playwright install chromium`) or an installed one picked
with `PLAYWRIGHT_CHANNEL` (`msedge`, `chrome`, `chromium`) — on Windows,
`PLAYWRIGHT_CHANNEL=msedge` uses the Edge that is always there.

A worktree's checkout is usually *not* the one the venv's editable install
points at. To run the worktree's own code, put the worktree first on the path:
`python -c "import sys; sys.path.insert(0, r'<worktree>'); from rostering.cli import main; main(['serve', ...])"`
(pytest run from the worktree already imports the worktree's code).

## Setup

```bash
cd scripts/e2e && npm install
```

## Run (agent path)

**Pick a free port**, especially in a worktree: other sessions may already run
their own server on the default port (8000).

```bash
port=8000
while netstat -ano | grep -E ":$port " | grep -q LISTENING; do
  port=$((port + 1))
done
echo "using port $port"
```

Start the app against throwaway data (never the real `data/seasons/`), then
poll until healthy. `--headless` stops it from opening a browser tab:

```bash
ROSTERING_SEASONS_DIR=/tmp/rostering-run/seasons \
  rostering serve --port "$port" --headless > /tmp/rostering-run/serve.log 2>&1 &

timeout 30 bash -c "until curl -sf http://127.0.0.1:$port/ >/dev/null 2>&1; do sleep 1; done" && echo APP_UP
```

Drive it with the smoke script (from `scripts/e2e/`), against an *empty*
seasons dir (the upload must create the Season):

```bash
PLAYWRIGHT_CHANNEL=msedge ROSTERING_APP_URL="http://127.0.0.1:$port/" \
  node smoke.mjs ../../data/seasons/2026-jaro/raw-response.xlsx
```

With no path argument it only checks the app shell loads. Screenshots land in
`scripts/e2e/screenshots/` (`01-app-loaded.png` … `06-tag-filter.png`). The
script prints one `ok:`/`FAILED:` line per check and exits non-zero on a failed
check or any browser console error. A Solve may use its whole time limit
(60 s by default), so the script waits up to 3 minutes for it.

Stop the server when done (git-bash has no `lsof`):

```bash
netstat -ano | grep -E ":$port" | grep LISTENING
taskkill //PID <pid> //F //T
```

## Run (human / development path)

```bash
rostering serve                 # opens http://127.0.0.1:8000 in the browser
rostering serve --reload        # restarts on every .py/.js change under rostering/
```

Both use the real `data/seasons/` — use the agent path above for throwaway
verification. `--reload` runs `rostering/webapp/ui/dev_server.py` as a script
(NiceGUI's reloader re-executes the main script and refuses `python -m`).

## Test

```bash
python -m pytest -q
```

The mutation tests call `rostering.webapp.mutations` directly against an
isolated `Workspace`. The UI tests (`tests/test_webapp_ui.py`) drive the real
page in-process with NiceGUI's user simulation (`user_simulation(root=root)`,
`asyncio_mode = "auto"`), finding widgets by their `.mark(...)` markers and
firing the grid's events with `.trigger(...)`; `tests/test_webapp_grid.py`
tests the grid's view model and HTML without a browser.

## Gotchas

- **A redraw replaces the view a handler came from.** Every mutation redraws
  the active tab (deferred to the next event-loop turn, see
  `UiSession.refresh`). A handler that awaits after a mutation must open
  dialogs through `dialogs.page_dialog(client=session.client)` / pass
  `client=` to `dialogs.confirm` / `ask_text`, or run inside
  `with session.client:` (as `UiSession.act` and `solving.*` do) — otherwise
  NiceGUI can no longer find the page ("The parent element this slot belongs
  to has been deleted").
- **Never name a grid event after a DOM event** (`drop`, `click`, …): NiceGUI's
  `.on(...)` also hears the browser's native event of that name.
- **Never use a bare Quasar utility class name in the grid's HTML** (`dimmed`,
  `disabled`, `hidden`, `fit`, …): Quasar styles them globally (`.dimmed` lays a
  dark overlay over the nearest positioned ancestor).
- **The grid is native HTML5 drag-and-drop.** In Playwright,
  `locator.dragTo(target)` works; real mouse drags in a browser pane work too.
- **Elements returned by `user.find(...).elements` are a set**: `.pop()` removes
  the element from that interaction, so find again before triggering on it.
- **A stale process can make a fresh `rostering serve` silently no-op** (the new
  one fails to bind and exits while a health check passes against the old one).
  Confirm `netstat` shows exactly one listener on your port after launching.
- **Windows path length**: a PyInstaller build run from a very long path (the
  session scratchpad) fails to load OR-Tools' DLL ("The filename or extension is
  too long"); copy `dist/rostering` somewhere short before running it.
