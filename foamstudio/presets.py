"""Guided templates exposed as cards on the Geometry stage."""

from __future__ import annotations

from typing import Any

from .models import Boundary, Geometry, MeshSettings, Physics, Project, RunSettings, slugify


FLUIDS: dict[str, dict[str, Any]] = {
    "water": {"label": "Agua (20 °C)", "density": 998.2, "nu": 1.0e-6},
    "air": {"label": "Aire (20 °C)", "density": 1.225, "nu": 1.5e-5},
    "oil": {"label": "Aceite pesado", "density": 900.0, "nu": 1.0e-2},
    "light_oil": {"label": "Aceite ligero", "density": 880.0, "nu": 1.0e-4},
    "custom": {"label": "Personalizado", "density": 1000.0, "nu": 1.0e-6},
}

PRESETS: dict[str, dict[str, Any]] = {
    "cavity": {
        "label": "Cavidad con tapa móvil",
        "short": "Cavidad",
        "description": "Caso clásico de validación. La pared superior se desliza y genera un vórtice.",
        "icon": "cavity",
        "tag": "Validación",
        "solver": "icoFoam",
        "accent": "#4cc9f0",
        "geometry": {
            "kind": "cavity",
            "length": 1.0,
            "height": 1.0,
            "depth": 0.1,
        },
        "mesh": {"base_size": 0.0125},
        "physics": {
            "solver": "icoFoam",
            "fluid": "oil",
            "density": 900.0,
            "nu": 1.0e-2,
            "inlet_speed": 1.0,
            "boundaries": [
                {
                    "name": "movingWall",
                    "kind": "movingWall",
                    "velocity": [1.0, 0.0, 0.0],
                    "description": "Tapa superior móvil (U = 1 m/s)",
                },
                {"name": "fixedWalls", "kind": "wall", "description": "Paredes fijas sin deslizamiento"},
                {"name": "frontAndBack", "kind": "empty", "description": "Caras laterales 2D"},
            ],
        },
        "run": {"end_time": 0.5, "delta_t": 0.005, "write_interval": 0.05},
        "camera": {"position": [1.45, 1.05, 1.75], "target": [0.5, 0.5, 0.05]},
    },
    "duct": {
        "label": "Conducto recto",
        "short": "Conducto",
        "description": "Flujo interno estacionario entre dos placas. ideal para practicar BCs de entrada y salida.",
        "icon": "duct",
        "tag": "Flujo interno",
        "solver": "simpleFoam",
        "accent": "#7bdcb5",
        "geometry": {
            "kind": "duct",
            "length": 2.0,
            "height": 0.2,
            "depth": 0.1,
        },
        "mesh": {"base_size": 0.008},
        "physics": {
            "solver": "simpleFoam",
            "fluid": "air",
            "density": 1.225,
            "nu": 1.5e-5,
            "inlet_speed": 0.075,
            "boundaries": [
                {
                    "name": "inlet",
                    "kind": "inlet",
                    "velocity": [0.075, 0.0, 0.0],
                    "description": "Entrada de velocidad uniforme",
                },
                {"name": "outlet", "kind": "outlet", "pressure": 0.0, "description": "Salida a presión 0"},
                {"name": "walls", "kind": "wall", "description": "Paredes sin deslizamiento"},
                {"name": "frontAndBack", "kind": "empty", "description": "Caras laterales 2D"},
            ],
        },
        "run": {"end_time": 600, "delta_t": 1.0, "write_interval": 100, "convergence": 1.0e-5},
        "camera": {"position": [2.6, 0.65, 1.15], "target": [1.0, 0.1, 0.05]},
    },
    "cylinder": {
        "label": "Cilindro en flujo cruzado",
        "short": "Cilindro",
        "description": "Flujo alrededor de un cilindro (Re = 100). Estela periódica y capa límite.",
        "icon": "cylinder",
        "tag": "Externo",
        "solver": "icoFoam",
        "accent": "#f4a261",
        "geometry": {
            "kind": "cylinder",
            "length": 2.0,
            "height": 0.4,
            "depth": 0.1,
            "diameter": 0.1,
            "center_x": 0.5,
            "center_y": 0.2,
        },
        "mesh": {"base_size": 0.008, "refine_obstacle": 1.8},
        "physics": {
            "solver": "icoFoam",
            "fluid": "light_oil",
            "density": 880.0,
            "nu": 1.0e-4,
            "inlet_speed": 0.1,
            "boundaries": [
                {
                    "name": "inlet",
                    "kind": "inlet",
                    "velocity": [0.1, 0.0, 0.0],
                    "description": "Entrada uniforme (U = 0.1 m/s)",
                },
                {"name": "outlet", "kind": "outlet", "pressure": 0.0, "description": "Salida a presión 0"},
                {"name": "walls", "kind": "wall", "description": "Paredes superior e inferior"},
                {"name": "cylinderWall", "kind": "wall", "description": "Superficie del cilindro"},
                {"name": "frontAndBack", "kind": "empty", "description": "Caras laterales 2D"},
            ],
        },
        "run": {"end_time": 8.0, "delta_t": 0.02, "write_interval": 0.4},
        "camera": {"position": [2.5, 0.75, 1.25], "target": [1.0, 0.2, 0.05]},
    },
    "stl": {
        "label": "Importar modelo STL",
        "short": "STL",
        "description": "Carga una pieza cerrada y malla el volumen exterior. Experimental en el MVP.",
        "icon": "stl",
        "tag": "Experimental",
        "solver": "simpleFoam",
        "accent": "#b39ddb",
        "geometry": {
            "kind": "stl",
            "length": 2.0,
            "height": 0.8,
            "depth": 0.8,
            "diameter": 0.25,
            "center_x": 0.6,
            "center_y": 0.4,
            "stl_scale": 1.0,
        },
        "mesh": {"base_size": 0.03},
        "physics": {
            "solver": "simpleFoam",
            "fluid": "air",
            "density": 1.225,
            "nu": 1.5e-5,
            "inlet_speed": 0.2,
            "boundaries": [
                {"name": "inlet", "kind": "inlet", "velocity": [0.2, 0.0, 0.0]},
                {"name": "outlet", "kind": "outlet", "pressure": 0.0},
                {"name": "walls", "kind": "wall"},
                {"name": "obstacle", "kind": "wall"},
                {"name": "frontAndBack", "kind": "wall"},
            ],
        },
        "run": {"end_time": 400, "delta_t": 1.0, "write_interval": 100, "convergence": 1.0e-5},
        "camera": {"position": [2.8, 1.4, 2.2], "target": [1.0, 0.4, 0.4]},
    },
}


def public_presets() -> list[dict[str, Any]]:
    """Preset metadata safe to send to the browser (without internal defaults)."""
    return [
        {
            "id": key,
            "label": value["label"],
            "short": value["short"],
            "description": value["description"],
            "icon": value["icon"],
            "tag": value["tag"],
            "solver": value["solver"],
            "accent": value["accent"],
            "camera": value["camera"],
        }
        for key, value in PRESETS.items()
    ]


def build_project(preset_id: str, name: str, root: str) -> Project:
    preset = PRESETS.get(preset_id, PRESETS["cavity"])
    geometry = Geometry.from_dict(preset["geometry"])
    mesh = MeshSettings.from_dict(preset["mesh"])
    physics = Physics.from_dict(preset["physics"])
    run = RunSettings.from_dict(preset["run"])
    project = Project(
        name=name or preset["label"],
        path=root,
        preset=preset_id if preset_id in PRESETS else "cavity",
        geometry=geometry,
        mesh=mesh,
        physics=physics,
        run=run,
        stage="geometry",
    )
    project.ensure_dirs()
    return project


def project_folder_name(preset_id: str, name: str) -> str:
    base = slugify(name or PRESETS.get(preset_id, PRESETS["cavity"])["label"])
    return base


def apply_preset(project: Project, preset_id: str, keep_name: bool = True) -> Project:
    """Reset geometry/physics to a preset while keeping the project folder."""
    preset = PRESETS.get(preset_id)
    if not preset:
        raise KeyError(f"Unknown preset: {preset_id}")
    project.preset = preset_id
    project.geometry = Geometry.from_dict(preset["geometry"])
    project.mesh = MeshSettings.from_dict(preset["mesh"])
    project.physics = Physics.from_dict(preset["physics"])
    project.run = RunSettings.from_dict(preset["run"])
    project.stage = "geometry"
    project.last_run = {}
    if not keep_name:
        project.name = preset["label"]
    return project


def sync_boundaries(project: Project, patch_names: list[str], kinds: dict[str, str] | None = None) -> None:
    """Keep user edits for patches that still exist and create defaults for new ones."""
    existing = {b.name: b for b in project.physics.boundaries}
    result: list[Boundary] = []
    for name in patch_names:
        if name in existing:
            result.append(existing[name])
            continue
        kind = (kinds or {}).get(name, "wall")
        velocity = [0.0, 0.0, 0.0]
        if kind == "inlet":
            velocity = [project.physics.inlet_speed, 0.0, 0.0]
        result.append(Boundary(name=name, kind=kind, velocity=velocity))
    project.physics.boundaries = result
