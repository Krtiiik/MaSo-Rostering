---
name: run-rostering
description: Build, run, and drive the rostering app (FastAPI backend + Vite/React frontend). Use when asked to start rostering, run its backend/frontend dev servers, upload a survey file, take a screenshot of its UI, or interact with the running app end-to-end.
---

This is a Python FastAPI backend (`rostering/webapp/`) serving a
React/Vite frontend (`frontend/`). Drive it by starting both dev
servers, then running the committed Playwright script at
`frontend/e2e/smoke.mjs` (or `npm run e2e:smoke` from `frontend/`),
which navigates the app, uploads a raw survey `.xlsx`, and screenshots
the result. All paths below are relative to the repo root
(`e:\Code\rostering`).

## Prerequisites

Python virtualenv already exists at `E:\Code\.venvs\rostering` with the
package installed editable (`pip install -e ".[dev]"` per `README.md`)
— this gives you `E:\Code\.venvs\rostering\Scripts\rostering.exe` as
the CLI entrypoint. Node 18+ for the frontend. Playwright's Chromium is
already downloaded on this machine at
`C:\Users\lukas\AppData\Local\ms-playwright\chromium-1243` — confirm
with `npx playwright install chromium --dry-run` (compare the printed
"Install location" to that path) before assuming a download is needed.

## Setup

Frontend deps (includes `playwright`, a real devDependency used by the
smoke driver):

```bash
cd frontend && npm install
```

No setup needed on the Python side beyond the existing venv.

## Build

No separate build step is required to *run* the app in dev mode (see
below). `npm run build` inside `frontend/` produces `frontend/dist/`,
which the FastAPI backend auto-mounts and serves at `/` if present —
only needed for the "serve built assets from one process" path, not
for iterating on the frontend.

## Run (agent path)

Start the backend with an isolated workspace dir (so you don't clobber
real helper data in `data/workspace/`), confirm nothing else already
owns the port first, then poll until healthy:

```bash
netstat -ano | grep -E ":(5173|8000)" | grep LISTENING   # must be empty before you start

ROSTERING_WORKSPACE_DIR=/e/tmp/rostering-run-workspace \
  "/e/Code/.venvs/rostering/Scripts/rostering.exe" serve --port 8000 \
  > /e/tmp/rostering-backend.log 2>&1 &
disown

timeout 15 bash -c 'until curl -sf http://127.0.0.1:8000/api/state >/dev/null 2>&1; do sleep 1; done' && echo BACKEND_UP
```

Then the frontend dev server (Vite proxies `/api` to `127.0.0.1:8000`
per `frontend/vite.config.ts`):

```bash
cd frontend && npm run dev > /e/tmp/rostering-frontend.log 2>&1 &
disown

timeout 30 bash -c 'until curl -sf http://localhost:5173/ >/dev/null 2>&1; do sleep 1; done' && echo FRONTEND_UP
```

Note: check `http://localhost:5173/`, not `http://127.0.0.1:5173/` —
in this environment the IPv4 form doesn't reliably resolve to Vite's
`[::1]` listener even though the server is up.

Drive it with the smoke script (from `frontend/`):

```bash
node e2e/smoke.mjs ../data/seasons/2026-jaro/raw-response.xlsx
```

or equivalently `npm run e2e:smoke -- ../data/seasons/2026-jaro/raw-response.xlsx`.
With no path argument it only checks the app shell loads (file input
visible). With a path, it uploads that `.xlsx` via the Upload tab,
waits for `table.helpers-table` to render, and — if any unresolved
friend-name chips are present — resolves one via its "Match to…"
select and dismisses another via its "Not attending" button, so both
code paths get exercised on every run.

Screenshots land in `frontend/e2e/screenshots/` (`01-app-loaded.png`,
`02-helpers-table.png`, `03-after-friend-actions.png`). The script
prints a summary line per step and exits non-zero if any browser
console error fired.

Stop both servers when done — Windows/git-bash has no `lsof`, so find
listeners via `netstat` and kill by PID:

```bash
netstat -ano | grep -E ":(5173|8000)" | grep LISTENING
taskkill //PID <pid> //F //T   # double-slash form, one per PID — repeat for each listener
```

Killing only the `npm run dev` wrapper PID is not enough — Vite spawns
a child process that keeps the port open; `taskkill //T` (kill the
whole tree) is what actually frees it. Re-check `netstat` after
killing — a stale process can still be listening and will make the
*next* backend launch fail to bind with a silent-looking success (see
Gotchas).

## Run (human path)

```bash
cd frontend && npm run build   # once, or after frontend changes
rostering serve                # from repo root, with the venv active
```

Open `http://127.0.0.1:8000`. Ctrl-C to stop. Uses the real
`data/workspace/` — don't use this path for throwaway verification;
use the isolated `ROSTERING_WORKSPACE_DIR` agent path instead.

## Test

```bash
"/e/Code/.venvs/rostering/Scripts/python.exe" -m pytest tests/test_webapp_api.py -q
```

16 tests pass (as of this writing). Backend API tests use `TestClient`
directly and don't need the dev servers running.

```bash
cd frontend && npx tsc --noEmit
```

Frontend type-check, no test runner configured beyond that + the
Playwright smoke script.

---

## Gotchas

- **A driver script placed outside `frontend/` fails with
  `ERR_MODULE_NOT_FOUND: playwright`.** Node's ESM resolver walks up
  from the *script's own file location*, not the process's cwd, and
  `NODE_PATH` does not fix this for ESM. This is why the smoke driver
  lives at `frontend/e2e/smoke.mjs` and not inside this skill
  directory — it must stay physically under `frontend/` so it resolves
  `playwright` from `frontend/node_modules`.
- **A stale backend process can make a fresh `rostering serve` silently
  no-op.** If an old process from a previous session is still bound to
  port 8000, a new `rostering serve --port 8000` logs `[Errno 10048]
  ... only one usage of each socket address` and exits — but if you
  already have a health-check loop polling that port, it can report
  `BACKEND_UP` against the *old* process and you won't notice the new
  one never started. Always confirm `netstat` shows exactly one
  listener on the port you expect right after launching, not just that
  the health check passed.
- **`curl -sf http://127.0.0.1:5173/` can fail even though Vite is up.**
  Vite's dev server listens on `[::1]:5173` in this environment; use
  `localhost:5173` for health checks, not the literal IPv4 loopback.
- **`taskkill //PID <pid> //F` alone can leave the port held.** `npm run
  dev` (and `rostering serve`) spawn child processes; killing just the
  wrapper PID doesn't free the port. Use `//T` to kill the whole
  process tree, and re-check `netstat` afterward.

## Troubleshooting

- **`ERR_MODULE_NOT_FOUND: Cannot find package 'playwright'`** running
  `node e2e/smoke.mjs`: you ran it with a copy of the script outside
  `frontend/`, or `frontend/node_modules` doesn't have `playwright`
  installed. Run `cd frontend && npm install` and invoke the script
  from inside `frontend/` (or via `npm run e2e:smoke`).
- **`waiting for locator('input[type="file"]') to be visible` timeout**
  in the smoke script: the frontend dev server isn't actually up (check
  `curl -sf http://localhost:5173/`), or `ROSTERING_FRONTEND_URL` points
  somewhere wrong. Also check for the stale-backend gotcha above — a
  half-started backend can leave the frontend proxying `/api` calls
  that hang, which doesn't block the file input directly but is worth
  ruling out first.
