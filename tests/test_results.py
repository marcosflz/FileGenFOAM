from __future__ import annotations

from pathlib import Path

import pytest

from foamstudio.api import create_app
from foamstudio.results import load_field
from foamstudio.settings import Settings


@pytest.fixture()
def demo_client(tmp_path: Path):
    settings = Settings(projects_dir=str(tmp_path / "projects"), last_project=None)
    app = create_app(settings)
    app.config["CTX"].runtimes.discover = lambda force=False: []
    return app.test_client(), app.config["CTX"]


def test_bundled_demo_is_precomputed(demo_client) -> None:
    c, ctx = demo_client
    assert ctx.project is not None
    assert ctx.project.has_mesh
    assert ctx.project.has_results
    state = c.get("/api/state").get_json()
    times = state["project"]["times"]
    assert len(times) >= 2
    assert times[-1]["value"] == pytest.approx(0.5)


def test_read_slice_fields(demo_client) -> None:
    c, ctx = demo_client
    for field in ("p", "U_mag"):
        payload = load_field(ctx.project.case, 0.5, field, mode="slice", axis="z", position=0.05)
        assert payload["point_count"] > 1000
        assert payload["triangle_count"] > 1000
        assert len(payload["points"]) == payload["point_count"] * 3
        assert len(payload["values"]) == payload["point_count"]
        assert payload["range"][0] < payload["range"][1]


def test_results_endpoint(demo_client) -> None:
    c, _ = demo_client
    r = c.get("/api/results/field?time=0.5&field=p&mode=slice&axis=z&position=0.05")
    assert r.status_code == 200
    data = r.get_json()
    assert data["field"] == "p"
    assert data["point_count"] > 0
    assert len(data["indices"]) % 3 == 0
    r = c.get("/api/results/field?time=0.5&field=invalid")
    assert r.status_code == 400
