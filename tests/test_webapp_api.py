import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_2026 = REPO_ROOT / "data" / "seasons" / "2026-jaro" / "raw-response.xlsx"

SMALL_CONFIG = [
    {
        "name": "B",
        "rooms": [
            {
                "name": "R1",
                "capacities": {
                    "Opravovatel": {"minimum": 0, "maximum": None},
                    "Zaloha": {"minimum": 0, "maximum": None},
                },
            }
        ],
        "capacities": {},
    }
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERING_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("ROSTERING_BUILDINGS_CONFIG_PATH", str(tmp_path / "buildings-config.yaml"))
    from rostering.webapp import config_store as config_store_module

    importlib.reload(config_store_module)
    from rostering.webapp import workspace as workspace_module

    importlib.reload(workspace_module)
    from rostering.webapp import api as api_module

    importlib.reload(api_module)
    return TestClient(api_module.app)


def test_initial_state_has_default_config(client):
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["helpers"] == []
    assert data["assignments"] == []
    # Seeded from the bundled default (a copy of the latest season's
    # roster), not empty — see rostering/webapp/config_store.py.
    assert {b["name"] for b in data["config"]} == {"Mala Strana", "Karlov", "Troja", "Karlin"}


def test_config_persists_across_reset(client, tmp_path):
    client.put("/api/config", json=SMALL_CONFIG)
    assert client.post("/api/reset").json()["config"][0]["name"] == "B"
    # The persistent config file itself was overwritten too.
    assert (tmp_path / "buildings-config.yaml").exists()


@pytest.mark.skipif(not RAW_2026.exists(), reason="real season data not present on this machine")
def test_upload_ingests_real_survey(client):
    with open(RAW_2026, "rb") as f:
        resp = client.post("/api/upload", files={"file": ("raw-response.xlsx", f, "application/octet-stream")})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["helpers"]) > 100
    assert isinstance(data["ingestion_warnings"], list)


def test_config_round_trip(client):
    resp = client.put("/api/config", json=SMALL_CONFIG)
    assert resp.status_code == 200
    state = client.get("/api/state").json()
    assert state["config"][0]["name"] == "B"
    assert state["config"][0]["rooms"][0]["name"] == "R1"


def test_config_rejects_invalid_shape(client):
    resp = client.put("/api/config", json=[{"rooms": []}])  # missing "name"
    assert resp.status_code == 400


def test_solve_requires_helpers_and_config(client):
    resp = client.post("/api/solve")
    assert resp.status_code == 400


def _seed_two_helpers(client):
    helpers = [
        {
            "id": 1,
            "name": "Anna",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [2],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        },
        {
            "id": 2,
            "name": "Petr",
            "role_preferences": {},
            "building_preferences": [],
            "friends": [1],
            "can_bring_notebook": False,
            "can_bring_camera": False,
            "unresolved_friend_names": [],
        },
    ]
    # Directly seed the workspace state (bypassing /api/upload) so this test
    # doesn't depend on a real survey file being present.
    from rostering.webapp.api import workspace

    state = workspace.load()
    state["helpers"] = helpers
    workspace.save(state)


def test_solve_end_to_end_and_export(client):
    _seed_two_helpers(client)
    client.put("/api/config", json=SMALL_CONFIG)

    resp = client.post("/api/solve")
    assert resp.status_code == 200
    state = resp.json()
    assert len(state["assignments"]) == 2
    assert state["diagnostics"]["status"] in ("OPTIMAL", "FEASIBLE")

    export_resp = client.get("/api/export.xlsx")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("application/vnd.openxmlformats")


def test_manual_move_updates_assignment_and_recomputes_friend_pairs(client):
    _seed_two_helpers(client)
    client.put("/api/config", json=SMALL_CONFIG)
    client.post("/api/solve")

    resp = client.put("/api/assignments/1", json={"building": "B", "room": "R1", "role": "Zaloha"})
    assert resp.status_code == 200
    state = resp.json()
    moved = next(a for a in state["assignments"] if a["helper_id"] == 1)
    assert moved["role"] == "Zaloha"


def test_manual_move_unknown_helper_404s(client):
    resp = client.put("/api/assignments/999", json={"building": "B", "room": "R1", "role": "Zaloha"})
    assert resp.status_code == 404


def test_manual_roles_round_trip(client):
    _seed_two_helpers(client)
    manual = {
        "structural": [{"role": "VedouciBudovy", "building": "B", "room": None, "helper_id": 1}],
        "overlay": [{"role": "Registrace", "helper_id": 2}],
    }
    resp = client.put("/api/manual-roles", json=manual)
    assert resp.status_code == 200
    state = client.get("/api/state").json()
    assert state["manual_roles"]["structural"][0]["helper_id"] == 1
    assert state["manual_roles"]["overlay"][0]["role"] == "Registrace"


def test_version_lifecycle(client):
    _seed_two_helpers(client)
    client.put("/api/config", json=SMALL_CONFIG)
    client.post("/api/solve")

    created = client.post("/api/versions", json={"name": "Draft 1"}).json()
    assert created["name"] == "Draft 1"

    versions = client.get("/api/versions").json()
    assert any(v["slug"] == created["slug"] for v in versions)

    # Mutate current state, then restore the saved version and confirm the
    # mutation is gone.
    client.put("/api/assignments/1", json={"building": "B", "room": "R1", "role": "Skenovac"})
    restored = client.post(f"/api/versions/{created['slug']}/restore").json()
    moved = next(a for a in restored["assignments"] if a["helper_id"] == 1)
    assert moved["role"] != "Skenovac"

    delete_resp = client.delete(f"/api/versions/{created['slug']}")
    assert delete_resp.status_code == 200
    assert client.get(f"/api/versions/{created['slug']}").status_code == 404


def test_reset_clears_workspace(client):
    _seed_two_helpers(client)
    resp = client.post("/api/reset")
    assert resp.status_code == 200
    assert resp.json()["helpers"] == []
