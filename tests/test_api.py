from __future__ import annotations

from pathlib import Path

import pytest

from foamstudio.api import create_app
from foamstudio.settings import Settings


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(projects_dir=str(tmp_path / "projects"), last_project=None)
    app = create_app(settings)
    # Keep tests independent from the host runtime and from VTK-heavy demo reads.
    app.config["CTX"].runtimes.discover = lambda force=False: []
    app.config["CTX"].runtimes.select = lambda runtime_id=None, force=False: __import__(
        "foamstudio.runtimes", fromlist=["Runtime"]
    ).Runtime(id="none", label="Sin motor", kind="none", available=False, detail="test")
    return app.test_client(), app.config["CTX"]


def test_health(client) -> None:
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_create_project_and_state(client) -> None:
    c, ctx = client
    r = c.post("/api/project/new", json={"preset": "cavity", "name": "API Test"})
    assert r.status_code == 201
    project = r.get_json()["project"]
    assert project["name"] == "API Test"
    assert Path(project["path"]).exists()
    assert (Path(project["path"]) / "project.json").exists()
    state = c.get("/api/state").get_json()
    assert state["project"]["has_mesh"] is False
    assert state["project"]["mesh_method"] == "blockMesh"
    assert state["project"]["estimate_cells"] > 0
    preview = c.get("/api/geometry/preview").get_json()
    assert preview["kind"] == "cavity"
    assert any(part["name"] == "domain" for part in preview["parts"])


def test_geometry_and_physics_updates(client) -> None:
    c, _ = client
    c.post("/api/project/new", json={"preset": "duct", "name": "Duct API"})
    r = c.post("/api/geometry", json={"length": 3.0, "height": 0.25})
    assert r.status_code == 200
    assert r.get_json()["project"]["geometry"]["length"] == pytest.approx(3.0)
    r = c.post(
        "/api/physics",
        json={
            "solver": "simpleFoam",
            "nu": 2e-5,
            "boundaries": [
                {"name": "inlet", "kind": "inlet", "velocity": [0.2, 0, 0]},
                {"name": "outlet", "kind": "outlet", "pressure": 0},
                {"name": "walls", "kind": "wall"},
                {"name": "frontAndBack", "kind": "empty"},
            ],
        },
    )
    assert r.status_code == 200
    physics = r.get_json()["project"]["physics"]
    assert physics["solver"] == "simpleFoam"
    assert physics["nu"] == pytest.approx(2e-5)
    assert physics["boundaries"][0]["velocity"][0] == pytest.approx(0.2)
    # Switching to a transient solver restores sensible defaults.
    r = c.post("/api/physics", json={"solver": "icoFoam"})
    assert r.status_code == 200
    run = r.get_json()["project"]["run"]
    assert run["end_time"] == pytest.approx(0.5)
    assert run["delta_t"] == pytest.approx(0.005)


def test_invalid_physics_rejected(client) -> None:
    c, _ = client
    c.post("/api/project/new", json={"preset": "cavity", "name": "Invalid"})
    r = c.post("/api/physics", json={"solver": "not-a-solver"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_mesh_requires_runtime(client) -> None:
    c, _ = client
    c.post("/api/project/new", json={"preset": "cavity", "name": "No Runtime"})
    r = c.post("/api/mesh")
    assert r.status_code == 409


def test_project_update_and_save(client) -> None:
    c, ctx = client
    c.post("/api/project/new", json={"preset": "cavity", "name": "Rename"})
    r = c.post("/api/project/update", json={"name": "Renamed", "stage": "physics"})
    assert r.status_code == 200
    assert r.get_json()["project"]["name"] == "Renamed"
    assert r.get_json()["project"]["stage"] == "physics"
    r = c.post("/api/project/save")
    assert r.status_code == 200
    assert ctx.project.project_file.exists()
