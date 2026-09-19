from pathlib import Path

from rostering.config import load_buildings
from rostering.domain import Role

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_real_2026_jaro_config():
    buildings = load_buildings(REPO_ROOT / "data" / "seasons" / "2026-jaro" / "config.yaml")
    assert set(buildings) == {"Mala Strana", "Karlov", "Troja", "Karlin"}

    ms = buildings["Mala Strana"]
    assert {r.name for r in ms.rooms} == {"S3", "S4", "S5", "S9"}
    assert ms.capacities[Role.Fotograf].minimum == 2
    assert ms.capacities[Role.Fotograf].maximum is None

    s3 = next(r for r in ms.rooms if r.name == "S3")
    assert s3.capacities[Role.Opravovatel].minimum == 3
    # Záloha must always be an unbounded overflow sink.
    assert s3.capacities[Role.Zaloha].maximum is None


def test_load_example_config_with_explicit_max():
    buildings = load_buildings(REPO_ROOT / "examples" / "buildings.example.yaml")
    s4 = next(r for r in buildings["Malá Strana"].rooms if r.name == "S4")
    assert s4.capacities[Role.Kreslic].minimum == 2
    assert s4.capacities[Role.Kreslic].maximum == 4


def test_missing_config_produces_no_buildings(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_buildings(empty) == {}
