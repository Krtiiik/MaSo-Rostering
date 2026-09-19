# Rostering

Assigns registered helpers to buildings/rooms/roles for the MaSo math
competition. See [CLAUDE.md](CLAUDE.md) for the domain glossary and context.

## Setup

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

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

Build the frontend once (requires Node 18+):

```
cd frontend
npm install
npm run build
```

Then run the server, which also serves the built frontend:

```
rostering serve
```

Open http://127.0.0.1:8000. Upload the raw survey export, then use the
"Continue to buildings & rooms →" button to configure buildings/rooms, solve,
then drag helpers between cells to adjust. Save named versions, restore/delete
them, and export the current roster to Excel from the same page. All working
state lives under `data/workspace/` (gitignored, since it holds real helper
data).

The buildings/rooms layout is pre-filled with a default (seeded from the most
recent season's roster) and persists separately in `data/buildings-config.yaml`
— it's saved there whenever you edit it on the Buildings page, so it survives
"start over" resets and app restarts.

For frontend development with hot reload, run the backend (`rostering
serve --port 8000`) and, in another terminal, `npm run dev` inside
`frontend/` (Vite on port 5173, proxying `/api` to the backend).

## Tests

```
pytest
```
