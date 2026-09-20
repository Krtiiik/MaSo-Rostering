---
name: run-rostering
description: Build, run, and drive the rostering app (a single-process Streamlit app with one custom drag-and-drop component). Use when asked to start rostering, run its dev server, upload a survey file, take a screenshot of its UI, or interact with the running app end-to-end.
---

This is a single-process Python [Streamlit](https://streamlit.io) app
(`rostering/streamlit_app/`), plus one custom drag-and-drop component
(`components/rostering-assignment-grid/`, a packaged CCv2 component —
React + dnd-kit — with its built JS/CSS bundle checked into git). There is
no separate frontend dev server and no HTTP API to proxy — `rostering serve`
launches Streamlit directly. Drive it with the committed Playwright script
at `scripts/e2e/smoke.mjs` (or `npm run smoke` from `scripts/e2e/`), which
navigates the app, uploads a raw survey `.xlsx`, solves, drags a helper chip
in the grid, and screenshots each step. All paths below are relative to the
repo root (`e:\Code\rostering`).

## Prerequisites

Python virtualenv already exists at `E:\Code\.venvs\rostering` with both
packages installed editable (`pip install -e ".[dev]"` and
`pip install -e components/rostering-assignment-grid`, per `README.md`) —
this gives you `E:\Code\.venvs\rostering\Scripts\rostering.exe` as the CLI
entrypoint. Node is only needed for the Playwright driver (`scripts/e2e/`)
or if you're editing the grid component's frontend — not to run the app
itself, since its bundle is checked in. Playwright's Chromium is already
downloaded on this machine at
`C:\Users\lukas\AppData\Local\ms-playwright\chromium-1243` — confirm with
`npx playwright install chromium --dry-run` (compare the printed "Install
location" to that path) before assuming a download is needed.

**First run only**: Streamlit prompts interactively for an email address on
its very first launch on a machine, which hangs a backgrounded/non-TTY
`rostering serve` forever waiting on stdin. Preempt it once per machine:

```bash
mkdir -p ~/.streamlit
printf '[browser]\ngatherUsageStats = false\n' > ~/.streamlit/config.toml
printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
```

(`~` here is the real Windows user profile, e.g. `C:\Users\lukas`, the same
one Python's `Path.home()` resolves to — confirm with `echo $HOME` in
git-bash if unsure.) `gatherUsageStats = false` alone is not enough; the
prompt is specifically gated on `credentials.toml` not existing yet.

## Setup

```bash
cd scripts/e2e && npm install
```

No setup needed on the Python side beyond the two editable installs in
`README.md`. No frontend build step is needed to *run* the app — only to
*edit* the grid component's JS (see `README.md` "Interactive web app").

## Run (agent path)

Start the app with an isolated workspace dir (so you don't clobber real
helper data in `data/workspace/`), confirm nothing else already owns the
port first, then poll until healthy. Redirect stdin from `/dev/null`
explicitly — a backgrounded command that inherits a non-`/dev/null` stdin
can still hang on the first-run prompt above even with the preempt files in
place, if this is the very first time `rostering serve` has run under this
tool's shell:

```bash
netstat -ano | grep -E ":8501" | grep LISTENING   # must be empty before you start

ROSTERING_WORKSPACE_DIR=/e/tmp/rostering-run-workspace \
ROSTERING_BUILDINGS_CONFIG_PATH=/e/tmp/rostering-buildings-config.yaml \
  "/e/Code/.venvs/rostering/Scripts/rostering.exe" serve --port 8501 \
  < /dev/null > /e/tmp/rostering-streamlit.log 2>&1 &
disown

timeout 30 bash -c 'until curl -sf http://localhost:8501/ >/dev/null 2>&1; do sleep 1; done' && echo APP_UP
```

Drive it with the smoke script (from `scripts/e2e/`):

```bash
node smoke.mjs ../../data/seasons/2026-jaro/raw-response.xlsx
```

or equivalently `npm run smoke -- ../../data/seasons/2026-jaro/raw-response.xlsx`.
With no path argument it only checks the app shell loads (file input
attached). With a path, it uploads that `.xlsx` via the Upload tab, waits
for the parsed-helpers `st.dataframe` to render, resolves one unresolved
friend name via its "Match" button and dismisses another via "Not
attending" (if any unresolved names exist), switches to the Buildings tab
and clicks "Save & solve", switches to the Roster tab, drags the first
helper chip into the first grid cell (exercising the CCv2 component), and
checks the Export button is present.

Screenshots land in `scripts/e2e/screenshots/` (`01-app-loaded.png`,
`02-helpers-loaded.png`, `03-after-friend-actions.png`,
`04-after-solve.png`, `05-after-drag.png`). The script prints a summary line
per step and exits non-zero if any browser console error fired.

Stop the server when done — Windows/git-bash has no `lsof`, so find the
listener via `netstat` and kill by PID:

```bash
netstat -ano | grep -E ":8501" | grep LISTENING
taskkill //PID <pid> //F //T   # double-slash form
```

`rostering serve` runs Streamlit via `subprocess.call`, and on Windows this
spawns as a direct child (unlike the old `npm run dev`/Vite case), so a
single `taskkill //PID <pid> //F //T` on the listening PID is normally
enough — but re-check `netstat` after killing, same as always, before
trusting a fresh launch will bind cleanly.

## Run (human path)

```bash
rostering serve                # from repo root, with the venv active
```

Open `http://127.0.0.1:8501`. Ctrl-C to stop. Uses the real
`data/workspace/` — don't use this path for throwaway verification; use the
isolated `ROSTERING_WORKSPACE_DIR` agent path instead.

## Test

```bash
"/e/Code/.venvs/rostering/Scripts/python.exe" -m pytest tests/test_streamlit_mutations.py -q
```

These call the `mutations.*` functions directly against an isolated
`Workspace` — no running server needed, no `TestClient`/HTTP layer at all
(that went away with FastAPI).

## Gotchas

- **The grid component renders in a shadow root, not an iframe.** CCv2
  (Streamlit's current custom-component API) doesn't use iframes at all —
  unlike the old v1-API/dnd-kit-in-an-iframe assumption that's common in
  older Streamlit component examples. Playwright's `page.locator(...)`
  pierces open shadow roots automatically for standard CSS selectors, so
  `page.locator("div.helper-chip")` etc. just works without
  `page.frameLocator(...)` — don't reach for that.
- **dnd-kit needs real pointer events, not a high-level "dragTo" call.**
  `elementHandle.dragTo(...)` doesn't reliably trigger dnd-kit's activation-
  distance constraint. Use `page.mouse.move/down/move.../up` with a few
  intermediate `move` steps instead (see `scripts/e2e/smoke.mjs`).
- **A stale process can make a fresh `rostering serve` silently no-op.** If
  an old process from a previous session is still bound to port 8501, a new
  launch logs `[Errno 10048] ... only one usage of each socket address` and
  exits — but if you already have a health-check loop polling that port, it
  can report `APP_UP` against the *old* process and you won't notice the new
  one never started. Always confirm `netstat` shows exactly one listener on
  the port you expect right after launching, not just that the health check
  passed.
- **Streamlit's tab strip (`st.segmented_control`) is keyed to
  `st.session_state["_active_tab"]`.** Switching tabs from Python (the
  Upload tab's "Continue →" CTA, the post-solve jump to Roster) goes through
  `session.switch_tab(...)`, which queues the change in `_pending_tab` and
  applies it in `app.py` *before* the widget renders on the next run — not
  a direct `st.session_state["_active_tab"] = ...` write. Streamlit raises
  `StreamlitWidgetAlreadyInstantiatedError` if you write a widget's own
  session-state key after that widget has already rendered earlier in the
  same script run (which is exactly the situation inside a tab's own button
  handler, since the tab strip renders before any tab's `render()` is
  called) — if you add a new cross-tab navigation action, reuse
  `session.switch_tab`, don't hand-roll the session-state write.

## Troubleshooting

- **App hangs forever after launching, no log output beyond "Welcome to
  Streamlit!"**: this machine hasn't had the first-run email prompt
  preempted yet (see Prerequisites) — either you skipped that step, or
  you're running as a different OS user/HOME than before. Kill the hung
  process, write the two files, relaunch.
- **`ERR_MODULE_NOT_FOUND: Cannot find package 'playwright'`** running
  `node smoke.mjs`: you ran it with a copy of the script outside
  `scripts/e2e/`, or `scripts/e2e/node_modules` doesn't have `playwright`
  installed. Run `cd scripts/e2e && npm install` and invoke the script from
  inside `scripts/e2e/` (or via `npm run smoke`).
- **`waiting for locator('input[type="file"]')` timeout** in the smoke
  script: the app isn't actually up (check `curl -sf http://localhost:8501/`
  and `netstat`), or `ROSTERING_APP_URL` points somewhere wrong.
- **`StreamlitAPIException: Component '...' must be declared in
  pyproject.toml with asset_dir to use file-backed js`** on `rostering
  serve` startup: the `rostering-assignment-grid` package isn't installed
  editable, or its frontend hasn't been built (`frontend/build/` missing —
  check `components/rostering-assignment-grid/rostering_assignment_grid/frontend/build/`
  contains `index-*.js`/`index-*.css`). Also double-check the import package
  name matches the distribution name (hyphens → underscores) if you ever
  rename this component — Streamlit's manifest scanner resolves a packaged
  component's manifest via `importlib.util.find_spec(<normalized dist
  name>)` for editable installs, so a mismatched import name (e.g. a package
  called `assignment_grid` inside a distribution called
  `rostering-assignment-grid`) fails discovery silently with this exact
  error, even though the package imports fine on its own.
