# Rostering

Assigns registered helpers to buildings/rooms/roles for the MaSo math
competition. See [CLAUDE.md](CLAUDE.md) for the domain glossary and context.

## Setup

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

## Usage

```
# 1. Convert a raw Google Forms export into the canonical helpers CSV
rostering ingest data/seasons/2026-jaro/raw-response.xlsx -o data/seasons/2026-jaro/helpers.csv

# 2. Solve and export a roster
rostering solve data/seasons/2026-jaro/config.yaml data/seasons/2026-jaro/helpers.csv \
    -o roster.xlsx --manual-roles data/seasons/2026-jaro/manual-roles.yaml
```

See `buildings.example.yaml`, `helpers.example.csv`, and
`manual-roles.example.yaml` for the input file formats.

## Tests

```
pytest
```
