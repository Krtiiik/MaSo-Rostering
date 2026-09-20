# Rostering

Assigns registered helpers to buildings/rooms/roles for the MaSo math
competition. See [CLAUDE.md](CLAUDE.md) for the domain glossary and context.

## Setup

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pip install -e components/rostering-assignment-grid
```

The second install is the drag-and-drop assignment-grid widget used by the
web app's Roster tab — a small custom Streamlit component (CCv2), packaged
as its own distribution because Streamlit discovers CCv2 components by
scanning installed distributions, not nested subpackages. Its built JS/CSS
bundle is checked into git, so this is a plain editable install — no Node/npm
needed unless you're editing the component's frontend (see "Interactive web
app" below).

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

A single-process [Streamlit](https://streamlit.io) app — no separate
frontend/backend split, no build step for normal use:

```
rostering serve
```

Open http://127.0.0.1:8501 (Streamlit's default port; override with
`--port`). Upload the raw survey export, then use the "Continue to buildings
& rooms →" button to configure buildings/rooms, solve, then drag helpers
between cells on the Roster tab to adjust. Save named versions, restore/
delete them, and export the current roster to Excel from the sidebar/Roster
tab. All working state lives under `data/workspace/` (gitignored, since it
holds real helper data).

The buildings/rooms layout is pre-filled with a default (seeded from the most
recent season's roster) and persists separately in `data/buildings-config.yaml`
— it's saved there whenever you edit it on the Buildings tab, so it survives
"start over" resets and app restarts.

The app's code lives in `rostering/streamlit_app/` (`app.py` is the entry
point; `mutations.py` holds the Streamlit-free state-mutation functions the
tabs call into, mirroring what used to be the FastAPI route handlers).
The one piece with a JS build step is the drag-and-drop grid, a custom
Streamlit component at `components/rostering-assignment-grid/` (a React +
dnd-kit frontend, generated from Streamlit's official CCv2
`component-template`). To edit its frontend:

```
cd components/rostering-assignment-grid/rostering_assignment_grid/frontend
npm install
npm run build          # rebuild the checked-in bundle after any JS change
```

While iterating, `npm run dev` in that same directory rebuilds the bundle
into `frontend/build/` on every save (Vite in `--watch` mode); refresh the
Streamlit page to pick up each rebuild — Streamlit's CCv2 registers the
component from the built files, not a live dev server.

## Tests

```
pytest
```
