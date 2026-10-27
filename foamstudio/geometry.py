"""Lightweight geometry previews (no VTK or gmsh needed)."""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any

import numpy as np

from .models import Geometry, Project


def _box_vertices(lx: float, ly: float, lz: float) -> tuple[list[float], list[int]]:
    v = [
        0, 0, 0,
        lx, 0, 0,
        lx, ly, 0,
        0, ly, 0,
        0, 0, lz,
        lx, 0, lz,
        lx, ly, lz,
        0, ly, lz,
    ]
    faces = [
        0, 2, 1, 0, 3, 2,  # bottom
        4, 5, 6, 4, 6, 7,  # top
        0, 1, 5, 0, 5, 4,  # front
        3, 7, 6, 3, 6, 2,  # back
        0, 4, 7, 0, 7, 3,  # left
        1, 2, 6, 1, 6, 5,  # right
    ]
    return v, faces


def _cylinder_vertices(
    cx: float, cy: float, z0: float, z1: float, radius: float, segments: int = 48
) -> tuple[list[float], list[int]]:
    vertices: list[float] = []
    for z in (z0, z1):
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            vertices.extend([cx + radius * math.cos(angle), cy + radius * math.sin(angle), z])
    faces: list[int] = []
    for i in range(segments):
        j = (i + 1) % segments
        # side
        faces.extend([i, j, segments + j, i, segments + j, segments + i])
        # caps
        faces.extend([i, j, segments + i])  # bottom-ish (z0)
        faces.extend([segments + i, segments + j, j])  # top-ish (z1)
    return vertices, faces


def parse_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    head = data[:512].lower()
    ascii_hint = head.lstrip().startswith(b"solid") and b"facet" in head
    if not ascii_hint and len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if count > 0 and len(data) >= 84 + count * 50:
            vertices = np.empty((count * 3, 3), dtype=np.float32)
            offset = 84
            for i in range(count):
                # skip normal (12 bytes), read 3 vertices (36 bytes), skip attr
                vals = struct.unpack_from("<9f", data, offset + 12)
                vertices[i * 3 : i * 3 + 3] = np.array(vals, dtype=np.float32).reshape(3, 3)
                offset += 50
            faces = np.arange(count * 3, dtype=np.int32).reshape(-1, 3)
            return vertices, faces
    # ASCII
    verts: list[list[float]] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            try:
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                continue
    if not verts or len(verts) % 3:
        raise ValueError("No se pudo leer el STL: archivo vacío o formato no reconocido")
    vertices = np.asarray(verts, dtype=np.float32)
    faces = np.arange(len(verts), dtype=np.int32).reshape(-1, 3)
    return vertices, faces


def transform_stl(vertices: np.ndarray, geometry: Geometry) -> np.ndarray:
    """Centre the model in the domain and keep it comfortably inside the box."""
    v = np.asarray(vertices, dtype=np.float64).copy()
    v *= max(0.001, float(geometry.stl_scale or 1.0))
    mins = v.min(axis=0)
    maxs = v.max(axis=0)
    size = maxs - mins
    domain = np.array([geometry.length, geometry.height, geometry.depth], dtype=np.float64)
    limit = 0.62 * float(np.min(domain[np.array([geometry.length, geometry.height, geometry.depth]) > 0]))
    max_extent = float(np.max(size))
    if max_extent > limit > 0:
        v *= limit / max_extent
        mins = v.min(axis=0)
        maxs = v.max(axis=0)
        size = maxs - mins
    center = (mins + maxs) / 2.0
    target = np.array([geometry.length / 2.0, geometry.height / 2.0, geometry.depth / 2.0])
    v += target - center
    return v


def geometry_preview(project: Project) -> dict[str, Any]:
    geometry = project.geometry
    lx, ly, lz = float(geometry.length), float(geometry.height), float(geometry.depth)
    parts: list[dict[str, Any]] = []
    patches = [{"name": b.name, "kind": b.kind} for b in project.physics.boundaries]
    markers: dict[str, Any] = {}

    if geometry.kind == "stl" and geometry.stl_file:
        path = Path(project.root) / geometry.stl_file
        if path.exists():
            try:
                verts, faces = parse_stl(path)
                verts = transform_stl(verts, geometry)
                parts.append(
                    {
                        "name": "obstacle",
                        "kind": "solid",
                        "color": "#b39ddb",
                        "opacity": 0.85,
                        "vertices": np.round(verts, 5).reshape(-1).tolist(),
                        "indices": faces.reshape(-1).tolist(),
                    }
                )
            except Exception as exc:
                parts.append({"name": "error", "kind": "error", "message": str(exc)})

    v, f = _box_vertices(lx, ly, lz)
    parts.append(
        {
            "name": "domain",
            "kind": "domain",
            "color": "#4cc9f0",
            "opacity": 0.10,
            "vertices": v,
            "indices": f,
        }
    )
    # A visible wire box for the domain.
    edges = [
        0, 1, 1, 2, 2, 3, 3, 0,
        4, 5, 5, 6, 6, 7, 7, 4,
        0, 4, 1, 5, 2, 6, 3, 7,
    ]
    parts.append(
        {
            "name": "bounds",
            "kind": "edges",
            "color": "#5d6b82",
            "opacity": 0.8,
            "vertices": v,
            "indices": edges,
        }
    )

    if geometry.kind == "cylinder":
        cx = float(geometry.center_x)
        cy = float(geometry.center_y)
        radius = max(0.001, float(geometry.diameter) / 2.0)
        cv, cf = _cylinder_vertices(cx, cy, 0.0, lz, radius)
        parts.append(
            {
                "name": "cylinder",
                "kind": "solid",
                "color": "#f4a261",
                "opacity": 0.95,
                "vertices": cv,
                "indices": cf,
            }
        )
        markers["obstacle"] = {"position": [cx, cy, lz / 2], "label": "Cilindro"}

    if geometry.kind in ("duct", "cylinder", "stl"):
        markers["inlet"] = {
            "position": [0.0, ly / 2.0, lz / 2.0],
            "direction": [1, 0, 0],
            "label": "Entrada",
        }
        markers["outlet"] = {
            "position": [lx, ly / 2.0, lz / 2.0],
            "direction": [1, 0, 0],
            "label": "Salida",
        }
    if geometry.kind == "cavity":
        markers["movingWall"] = {
            "position": [lx / 2.0, ly, lz / 2.0],
            "direction": [1, 0, 0],
            "label": "Tapa móvil",
        }

    return {
        "kind": geometry.kind,
        "bounds": [0.0, lx, 0.0, ly, 0.0, lz],
        "parts": parts,
        "patches": patches,
        "markers": markers,
        "dimensions": {"x": lx, "y": ly, "z": lz},
    }
