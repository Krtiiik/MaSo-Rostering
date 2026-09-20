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

**Pick a port carefully if you're in a worktree.** If the working directory
is under `.claude/worktrees/...` rather than the main checkout, assume other
Claude Code sessions are running concurrently against this same repo — in
the main checkout, in another worktree, or both — and any of them may
already have their own `rostering serve` bound to the default port (8501).
Don't hardcode `--port 8501` in that case: probe for a free port first and
use that same port consistently through launch, health-check, and
`ROSTERING_APP_URL` for any driver script. A stale/leftover listener from an
earlier attempt in the *same* session is a different problem (see the
Gotchas entry below) — the check here is specifically about other,
independent sessions you don't control. From the main checkout (not a
worktree), 8501 is a reasonable default since you're less likely to collide,
but it's still worth a quick check if you've had a server running earlier in
this session.

```bash
port=8501
while netstat -ano | grep -E ":$port " | grep -q LISTENING; do
  port=$((port + 1))
done
echo "using port $port"
```

Start the app with an isolated workspace dir (so you don't clobber real
helper data in `data/workspace/`), then poll until healthy. Redirect stdin
from `/dev/null` explicitly — a backgrounded command that inherits a
non-`/dev/null` stdin can still hang on the first-run prompt above even with
the preempt files in place, if this is the very first time `rostering serve`
has run under this tool's shell:

```bash
ROSTERING_WORKSPACE_DIR=/e/tmp/rostering-run-workspace \
ROSTERING_BUILDINGS_CONFIG_PATH=/e/tmp/rostering-buildings-config.yaml \
  "/e/Code/.venvs/rostering/Scripts/rostering.exe" serve --port "$port" --headless \
  < /dev/null > /e/tmp/rostering-streamlit.log 2>&1 &
disown

timeout 30 bash -c "until curl -sf http://localhost:$port/ >/dev/null 2>&1; do sleep 1; done" && echo APP_UP
```

`--headless` maps to Streamlit's `--server.headless true` and stops it from
auto-opening a browser tab on launch — always pass it for agent/scripted
runs like this one (a real browser tab popping open on the user's machine
for a test run you're driving with Playwright is unwanted noise). Leave it
off for the human path below, where auto-opening is the point.

Drive it with the smoke script (from `scripts/e2e/`). If you picked a
non-default port above, set `ROSTERING_APP_URL` so the script targets it:

```bash
ROSTERING_APP_URL="http://localhost:$port" node smoke.mjs ../../data/seasons/2026-jaro/raw-response.xlsx
```

or equivalently `npm run smoke -- ../../data/seasons/2026-jaro/raw-response.xlsx`.
With no path argument it only checks the app shell loads (file input
attached). With a path, it uploads that `.xlsx` via the Upload tab, waits
for the parsed-helpers `st.dataframe` to render, resolves one unresolved
friend name to a candidate and dismisses another as "not attending" via
the inline per-name selectboxes in the "Resolve friend names" section (if
any unresolved names exist — each selectbox applies its choice immediately
on selection, there's no separate confirm button), switches to the
Buildings tab and clicks "Save & solve", switches to the Roster tab, drags
the first helper chip into the first grid cell (exercising the CCv2
component), and checks the Export button is present.

Screenshots land in `scripts/e2e/screenshots/` (`01-app-loaded.png`,
`02-helpers-loaded.png`, `03-after-friend-actions.png`,
`04-after-solve.png`, `05-after-drag.png`). The script prints a summary line
per step and exits non-zero if any browser console error fired.

Stop the server when done — Windows/git-bash has no `lsof`, so find the
listener via `netstat` and kill by PID (use whichever port you actually
launched on):

```bash
netstat -ano | grep -E ":$port" | grep LISTENING
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
  an old process — your own from earlier in this session, or (in a
  worktree) an unrelated session's — is still bound to the port you pick, a
  new launch logs `[Errno 10048] ... only one usage of each socket address`
  and exits — but if you already have a health-check loop polling that
  port, it can report `APP_UP` against the *old* process and you won't
  notice the new one never started. Always confirm `netstat` shows exactly
  one listener on the port you expect right after launching, not just that
  the health check passed. This is exactly why picking a free port up front
  (see "Run (agent path)" above) isn't optional in a worktree — it's not
  just about avoiding a bind error, it's about not silently testing against
  someone else's already-running server.
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

- **A `rostering serve` process must be restarted to pick up Python code
  changes**, not just have the browser tab reloaded. Streamlit's own file
  watcher only prompts "Source file changed — Rerun?" in the browser and
  won't auto-apply without a click (or `--reload`, which sets
  `server.runOnSave` and still needs the *browser* connected to receive
  it) — a background Playwright-driven run has no one to click that prompt.
  After editing any `rostering/` source, `taskkill` the old PID (see above)
  and relaunch before re-running the smoke script, or you'll silently test
  stale code.
- **`st.selectbox` renders as a virtualized `react-aria` combobox, not a
  native `<select>`.** Playwright must click the `[data-testid="stSelectbox"]`
  wrapper to open it, then wait for `[role="listbox"]` before querying
  `getByRole("option")` — with many options only a small visible window
  (around 11) is actually in the DOM at once, so targeting an option by
  name/index that isn't near the top requires scrolling the listbox first.
  If you control the options' order (as in the friend-name-resolution
  selectboxes), put anything a test needs to select — e.g. a "not
  attending" sentinel — right after the placeholder instead of at the end
  of a long candidate list, so it's always in the initial render window.

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
  script: the app isn't actually up (check `curl -sf http://localhost:$port/`
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
