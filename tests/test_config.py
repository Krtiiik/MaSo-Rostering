from pathlib import Path

from rostering.config import load_buildings
from rostering.domain import Role

REPO_ROOT = Path(__file__).resolve().parents[1]


GENERATED_CONFIG = """Alfa:
  A1:
    Opravovatel: 3
    Menic: 2
  A2:
    Opravovatel: 1
  A3: {}
  Fotograf: 2
Beta:
  B1:
    Kreslic: 4
    Skenovac: 1
Gama:
  G1:
    Opravovatel: 2
"""


def test_load_generated_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(GENERATED_CONFIG, encoding="utf-8")
    buildings = load_buildings(path)
    assert set(buildings) == {"Alfa", "Beta", "Gama"}

    alfa = buildings["Alfa"]
    assert {r.name for r in alfa.rooms} == {"A1", "A2", "A3"}
    assert alfa.capacities[Role.Fotograf].minimum == 2

    a1 = next(r for r in alfa.rooms if r.name == "A1")
    assert a1.capacities[Role.Opravovatel].minimum == 3
    assert a1.capacities[Role.Menic].minimum == 2


def test_load_example_config():
    buildings = load_buildings(REPO_ROOT / "examples" / "buildings.example.yaml")
    s4 = next(r for r in buildings["Malá Strana"].rooms if r.name == "S4")
    assert s4.capacities[Role.Kreslic].minimum == 2


def test_missing_config_produces_no_buildings(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_buildings(empty) == {}


def test_old_style_min_max_mapping_ignores_max(tmp_path):
    # Files written before the maximum-headcount cap was removed may still
    # carry a {min, max} mapping — max should just be ignored.
    old_style = tmp_path / "old_style.yaml"
    old_style.write_text("B:\n  R1:\n    Kreslic: {min: 2, max: 4}\n", encoding="utf-8")
    buildings = load_buildings(old_style)
    r1 = next(r for r in buildings["B"].rooms if r.name == "R1")
    assert r1.capacities[Role.Kreslic].minimum == 2
