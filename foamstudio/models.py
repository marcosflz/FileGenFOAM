"""Serializable domain model for a FileGenFOAM Studio project.

The project is the single source of truth shared by the UI, the case writer,
the mesher and the solver runner.  Everything lives in ``project.json`` inside
the case directory so a project can be copied, inspected or versioned as a
normal folder.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _clean_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_. -]+", "", value or "").strip()
    return value or "Untitled"


@dataclass
class Geometry:
    kind: str = "cavity"  # cavity | duct | cylinder | stl
    length: float = 1.0
    height: float = 1.0
    depth: float = 0.1
    diameter: float = 0.1
    center_x: float = 0.35
    center_y: float = 0.2
    stl_file: str | None = None
    stl_scale: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Geometry":
        return cls(**(data or {}))


@dataclass
class MeshSettings:
    preset: str = "medium"  # coarse | medium | fine | custom
    base_size: float = 0.0125
    refine_obstacle: float = 1.6
    boundary_layers: int = 0
    cell_count: int | None = None
    nodes: int | None = None
    patches: list[str] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MeshSettings":
        return cls(**(data or {}))


@dataclass
class Boundary:
    name: str
    kind: str = "wall"  # inlet | outlet | wall | movingWall | empty | symmetry
    velocity: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    pressure: float = 0.0
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Boundary":
        data = dict(data)
        data["velocity"] = [float(v) for v in data.get("velocity", [0, 0, 0])]
        return cls(**data)


@dataclass
class Physics:
    solver: str = "icoFoam"  # icoFoam | simpleFoam
    fluid: str = "water"
    density: float = 998.2
    nu: float = 0.01
    inlet_speed: float = 1.0
    turbulence: str = "laminar"
    boundaries: list[Boundary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["boundaries"] = [b.to_dict() for b in self.boundaries]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Physics":
        data = dict(data or {})
        data["boundaries"] = [
            b if isinstance(b, Boundary) else Boundary.from_dict(b)
            for b in data.get("boundaries", [])
        ]
        return cls(**data)

    def boundary(self, name: str) -> Boundary | None:
        for item in self.boundaries:
            if item.name == name:
                return item
        return None


@dataclass
class RunSettings:
    end_time: float = 0.5
    delta_t: float = 0.005
    write_interval: float = 0.05
    max_iterations: int = 500
    convergence: float = 1e-4
    write_format: str = "ascii"
    purged_results: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RunSettings":
        return cls(**(data or {}))


@dataclass
class Project:
    name: str
    path: str
    preset: str = "cavity"
    geometry: Geometry = field(default_factory=Geometry)
    mesh: MeshSettings = field(default_factory=MeshSettings)
    physics: Physics = field(default_factory=Physics)
    run: RunSettings = field(default_factory=RunSettings)
    stage: str = "geometry"
    notes: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    last_run: dict[str, Any] = field(default_factory=dict)
    settings_schema: int = SCHEMA_VERSION

    @property
    def root(self) -> Path:
        return Path(self.path)

    @property
    def case(self) -> Path:
        return self.root / "case"

    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    @property
    def has_mesh(self) -> bool:
        return (self.case / "constant" / "polyMesh" / "owner").exists()

    @property
    def has_results(self) -> bool:
        if not self.case.exists():
            return False
        for item in self.case.iterdir():
            if item.is_dir() and _is_number(item.name) and float(item.name) > 0 and (item / "U").exists():
                return True
        return False

    def touch(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["geometry"] = self.geometry.to_dict()
        data["mesh"] = self.mesh.to_dict()
        data["physics"] = self.physics.to_dict()
        data["run"] = self.run.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        data = dict(data)
        data["geometry"] = Geometry.from_dict(data.get("geometry"))
        data["mesh"] = MeshSettings.from_dict(data.get("mesh"))
        data["physics"] = Physics.from_dict(data.get("physics"))
        data["run"] = RunSettings.from_dict(data.get("run"))
        data.pop("model_config", None)
        return cls(**data)

    def save(self) -> None:
        self.touch()
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_file.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        project_file = Path(path)
        if project_file.is_dir():
            project_file = project_file / "project.json"
        data = json.loads(project_file.read_text(encoding="utf-8"))
        project = cls.from_dict(data)
        # The folder is authoritative: projects must survive being moved/copied.
        project.path = str(project_file.parent)
        return project

    def ensure_dirs(self) -> None:
        for sub in ("case/0", "case/constant", "case/system", "uploads", "logs"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def slugify(value: str) -> str:
    import unicodedata

    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = _clean_name(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "project"
