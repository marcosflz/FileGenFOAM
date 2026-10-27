from __future__ import annotations

import json
from pathlib import Path

import pytest

from foamstudio.case_writer import clean_results, patch_type_map, time_directories, write_case
from foamstudio.geometry import parse_stl, transform_stl
from foamstudio.jobs import Job
from foamstudio.meshing import block_counts, parse_checkmesh, write_block_mesh_dict
from foamstudio.models import Boundary, Geometry, Project, slugify
from foamstudio.presets import build_project


@pytest.fixture()
def cavity(tmp_path: Path) -> Project:
    project = build_project("cavity", "Test Cavity", str(tmp_path / "cavity"))
    write_case(project)
    return project


def test_project_roundtrip(tmp_path: Path) -> None:
    project = build_project("duct", "Duct Project", str(tmp_path / "duct"))
    project.physics.boundaries[0].velocity = [0.2, 0.0, 0.0]
    project.mesh.cell_count = 123
    project.save()
    loaded = Project.load(project.root)
    assert loaded.name == "Duct Project"
    assert loaded.physics.boundaries[0].kind == "inlet"
    assert loaded.physics.boundaries[0].velocity[0] == pytest.approx(0.2)
    assert loaded.mesh.cell_count == 123
    assert loaded.path == str(project.root)


def test_case_writer_creates_expected_fields(cavity: Project) -> None:
    case = cavity.case
    assert (case / "0" / "U").exists()
    assert (case / "0" / "p").exists()
    assert (case / "system" / "controlDict").read_text(encoding="utf-8").count("application     icoFoam") == 1
    u = (case / "0" / "U").read_text(encoding="utf-8")
    assert "movingWall" in u
    assert "uniform (1 0 0)" in u
    assert "type            empty;" in u
    p = (case / "0" / "p").read_text(encoding="utf-8")
    assert "dimensions      [0 2 -2 0 0 0 0]" in p
    assert (case / "constant" / "transportProperties").exists()
    assert (case / "case.foam").exists()
    # Extra compatibility dictionaries are written for OpenFOAM 12 / BlueCFD 2024.
    assert (case / "constant" / "physicalProperties").exists()
    assert (case / "constant" / "momentumTransport").exists()


def test_patch_type_map(cavity: Project) -> None:
    types = patch_type_map(cavity)
    assert types["movingWall"] == "wall"
    assert types["frontAndBack"] == "empty"


def test_block_mesh_dict(cavity: Project) -> None:
    nx, ny, nz = block_counts(cavity)
    assert (nx, ny, nz) == (80, 80, 1)
    write_block_mesh_dict(cavity)
    text = (cavity.case / "system" / "blockMeshDict").read_text(encoding="utf-8")
    assert "hex (0 1 2 3 4 5 6 7) (80 80 1)" in text
    assert "movingWall" in text
    assert "frontAndBack" in text


def test_clean_results_and_times(cavity: Project) -> None:
    for name in ("0.1", "0.2", "not-a-time"):
        folder = cavity.case / name
        folder.mkdir()
        if name != "not-a-time":
            (folder / "U").write_text("dummy", encoding="utf-8")
    assert [v for v, _ in time_directories(cavity.case)] == [0.0, 0.1, 0.2]
    removed = clean_results(cavity)
    assert set(removed) == {"0.1", "0.2"}
    assert (cavity.case / "not-a-time").exists()
    assert time_directories(cavity.case) == [(0.0, "0")]


def test_residual_parser() -> None:
    job = Job(id="x", kind="run", label="run")
    lines = [
        "Time = 0.005",
        "smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 1e-07, No Iterations 5",
        "smoothSolver:  Solving for Uy, Initial residual = 0.5, Final residual = 1e-07, No Iterations 5",
        "DICPCG:  Solving for p, Initial residual = 0.25, Final residual = 1e-07, No Iterations 10",
        "time step continuity errors : sum local = 1e-08, global = -2e-09, cumulative = 3e-09",
        "Time = 0.010",
        "smoothSolver:  Solving for Ux, Initial residual = 0.1, Final residual = 1e-07, No Iterations 5",
        "smoothSolver:  Solving for Uy, Initial residual = 0.05, Final residual = 1e-07, No Iterations 5",
        "DICPCG:  Solving for p, Initial residual = 0.02, Final residual = 1e-07, No Iterations 10",
        "time step continuity errors : sum local = 2e-08, global = -4e-09, cumulative = 7e-09",
    ]
    for line in lines:
        job.append(line)
    job.finish("completed", 0)
    assert len(job.residuals) == 2
    assert job.residuals[0]["time"] == pytest.approx(0.005)
    assert job.residuals[0]["Ux"] == pytest.approx(1.0)
    assert job.residuals[0]["continuity"] == pytest.approx(2e-09)
    assert job.residuals[1]["Uy"] == pytest.approx(0.05)
    assert job.errors == []


def test_checkmesh_parser_handles_trailing_periods() -> None:
    lines = [
        "    points:           13122",
        "    faces:            25760",
        "    cells:            6400",
        "    Max aspect ratio = 1 OK.",
        "    Min volume = 1.5625e-05. Max volume = 1.5625e-05.",
        "    Max skewness = 5.329071e-14 OK.",
        "    Mesh OK.",
    ]
    stats = parse_checkmesh(lines)
    assert stats["cells"] == 6400
    assert stats["points"] == 13122
    assert stats["max_aspect_ratio"] == pytest.approx(1.0)
    assert stats["min_volume"] == pytest.approx(1.5625e-05)
    assert stats["ok"] is True


def test_ascii_stl_parse(tmp_path: Path) -> None:
    stl = tmp_path / "triangle.stl"
    stl.write_text(
        "solid t\n"
        "facet normal 0 0 1\nouter loop\n"
        "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
        "endloop\nendfacet\nendsolid t\n",
        encoding="utf-8",
    )
    vertices, faces = parse_stl(stl)
    assert len(vertices) == 3
    assert faces.shape == (1, 3)
    transformed = transform_stl(vertices, Geometry(kind="stl", length=2, height=2, depth=2))
    assert transformed.shape == (3, 3)


def test_slugify() -> None:
    assert slugify("Cavidad con tapa móvil") == "cavidad-con-tapa-movil"
    assert slugify("") == "untitled"
