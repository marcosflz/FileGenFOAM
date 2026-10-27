"""Mesh generation.

Two meshers are used deliberately:

* blockMesh for the rectangular cavity/duct templates: deterministic,
  structured hexahedra, available in every OpenFOAM/BlueCFD version.
* gmsh for the cylinder template and imported STL obstacles: named physical
  groups, followed by OpenFOAM's gmshToFoam converter.
"""

from __future__ import annotations

import math
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .models import Project

GMSH_LOCK = threading.Lock()


def invalidate_mesh(project: Project) -> None:
    """Remove the generated mesh and results after a geometry/mesh change."""
    from .case_writer import clean_results

    shutil.rmtree(project.case / "constant" / "polyMesh", ignore_errors=True)
    shutil.rmtree(project.root / "mesh", ignore_errors=True)
    clean_results(project)
    project.mesh.cell_count = None
    project.mesh.nodes = None
    project.mesh.patches = []
    project.mesh.quality = {}
    project.mesh.generated_at = None
    project.last_run = {}


def mesh_method(project: Project) -> str:
    return "blockMesh" if project.geometry.kind in ("cavity", "duct") else "gmsh"


def block_counts(project: Project) -> tuple[int, int, int]:
    g = project.geometry
    lc = max(1e-5, float(project.mesh.base_size))
    nx = max(2, int(round(float(g.length) / lc)))
    ny = max(2, int(round(float(g.height) / lc)))
    nz = 1
    return nx, ny, nz


def _block_dict(project: Project) -> str:
    g = project.geometry
    nx, ny, nz = block_counts(project)
    lx, ly, lz = float(g.length), float(g.height), float(g.depth)
    if project.geometry.kind == "duct":
        boundary = f"""    inlet
    {{
        type patch;
        faces ((0 4 7 3));
    }}
    outlet
    {{
        type patch;
        faces ((1 2 6 5));
    }}
    walls
    {{
        type wall;
        faces ((0 1 5 4) (3 7 6 2));
    }}
    frontAndBack
    {{
        type empty;
        faces ((0 3 2 1) (4 5 6 7));
    }}"""
    else:
        boundary = f"""    movingWall
    {{
        type wall;
        faces ((3 7 6 2));
    }}
    fixedWalls
    {{
        type wall;
        faces ((0 4 7 3) (1 2 6 5) (0 1 5 4));
    }}
    frontAndBack
    {{
        type empty;
        faces ((0 3 2 1) (4 5 6 7));
    }}"""
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Website:  https://openfoam.org                  |
|   \\\\  /    A nd           | Version:  v2412                                 |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

scale 1;

vertices
(
    (0 0 0)
    ({_n(lx)} 0 0)
    ({_n(lx)} {_n(ly)} 0)
    (0 {_n(ly)} 0)
    (0 0 {_n(lz)})
    ({_n(lx)} 0 {_n(lz)})
    ({_n(lx)} {_n(ly)} {_n(lz)})
    (0 {_n(ly)} {_n(lz)})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges
();

boundary
(
{boundary}
);

mergePatchPairs
();

// ************************************************************************* //
"""


def _n(value: float) -> str:
    return f"{float(value):.10g}"


def write_block_mesh_dict(project: Project) -> Path:
    path = project.case / "system" / "blockMeshDict"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_block_dict(project), encoding="utf-8", newline="\n")
    return path


def _gmsh_mesh(project: Project, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Generate the cylinder mesh with gmsh (2D extrusion, one empty layer)."""
    import gmsh

    g = project.geometry
    lx, ly, lz = float(g.length), float(g.height), float(g.depth)
    lc = max(1e-5, float(project.mesh.base_size))
    r = float(g.diameter) / 2.0
    cx, cy = float(g.center_x), float(g.center_y)
    if r <= 0 or cx - r <= 0 or cx + r >= lx or cy - r <= 0 or cy + r >= ly:
        raise ValueError("El cilindro debe estar completamente dentro del dominio")

    msh = project.root / "mesh" / "case.msh"
    msh.parent.mkdir(parents=True, exist_ok=True)
    with GMSH_LOCK:
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("General.Verbosity", 2)
            gmsh.option.setNumber("General.NumThreads", 1)
            gmsh.option.setNumber("Mesh.MeshSizeMax", lc)
            gmsh.option.setNumber("Mesh.MeshSizeMin", 0.2 * lc)
            gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
            gmsh.option.setNumber("Mesh.Binary", 0)
            gmsh.option.setNumber("Mesh.SaveAll", 0)
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 1)
            gmsh.option.setNumber("Mesh.Algorithm", 8)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.model.add("cylinder")
            occ = gmsh.model.occ
            rect = occ.addRectangle(0, 0, 0, lx, ly)
            disk = occ.addDisk(cx, cy, 0, r, r)
            cut, _ = occ.cut([(2, rect)], [(2, disk)], removeObject=True, removeTool=True)
            occ.synchronize()
            if not cut:
                raise RuntimeError("gmsh no pudo recortar el cilindro")
            surface = cut[0][1]
            tol = max(1e-7, 5e-6 * max(lx, ly, lz, r))
            outer: dict[str, list[int]] = {"x0": [], "xL": [], "y0": [], "yL": []}
            hole_curves: list[int] = []
            for dim, tag in gmsh.model.getEntities(1):
                xmin, ymin, _, xmax, ymax, _ = gmsh.model.getBoundingBox(1, tag)
                if abs(xmin) < tol and abs(xmax) < tol:
                    outer["x0"].append(tag)
                elif abs(xmin - lx) < tol and abs(xmax - lx) < tol:
                    outer["xL"].append(tag)
                elif abs(ymin) < tol and abs(ymax) < tol:
                    outer["y0"].append(tag)
                elif abs(ymin - ly) < tol and abs(ymax - ly) < tol:
                    outer["yL"].append(tag)
                else:
                    hole_curves.append(tag)
            if project.mesh.refine_obstacle > 0 and hole_curves:
                dist = gmsh.model.mesh.field.add("Distance")
                gmsh.model.mesh.field.setNumbers(dist, "CurvesList", hole_curves)
                gmsh.model.mesh.field.setNumber(dist, "Sampling", 200)
                threshold = gmsh.model.mesh.field.add("Threshold")
                gmsh.model.mesh.field.setNumber(threshold, "InField", dist)
                gmsh.model.mesh.field.setNumber(
                    threshold, "SizeMin", lc / max(1.0, project.mesh.refine_obstacle)
                )
                gmsh.model.mesh.field.setNumber(threshold, "SizeMax", lc)
                gmsh.model.mesh.field.setNumber(threshold, "DistMin", 0.15 * r)
                gmsh.model.mesh.field.setNumber(threshold, "DistMax", 0.60 * r)
                gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
                gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
                gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            # Structured outer rectangle if the cut kept the four edges intact.
            if all(len(v) == 1 for v in outer.values()):
                nx = max(2, int(round(lx / lc)) + 1)
                ny = max(2, int(round(ly / lc)) + 1)
                gmsh.model.mesh.setTransfiniteCurve(outer["y0"][0], nx)
                gmsh.model.mesh.setTransfiniteCurve(outer["yL"][0], nx)
                gmsh.model.mesh.setTransfiniteCurve(outer["x0"][0], ny)
                gmsh.model.mesh.setTransfiniteCurve(outer["xL"][0], ny)
            gmsh.model.mesh.generate(2)
            out = occ.extrude([(2, surface)], 0, 0, lz, numElements=[1], recombine=True)
            gmsh.model.occ.synchronize()
            volumes = [tag for dim, tag in out if dim == 3]
            if len(volumes) != 1:
                raise RuntimeError(f"gmsh esperaba un volumen, obtuvo {volumes}")
            gmsh.model.mesh.generate(3)
            _name_groups(gmsh, project, lz, cx, cy, r, volumes[0])
            vgroup = gmsh.model.addPhysicalGroup(3, volumes)
            gmsh.model.setPhysicalName(3, vgroup, "internalMesh")
            gmsh.write(str(msh))
            types, tags, _nodes = gmsh.model.mesh.getElements(3)
            cells = sum(len(t) for t in tags)
            nodes = len(gmsh.model.mesh.getNodes()[0])
            group_count = len(gmsh.model.getPhysicalGroups(2))
        finally:
            gmsh.finalize()
    if log:
        log(f"gmsh: {nodes} nodos, {cells} celdas, {group_count} grupos de contorno")
    return {"msh": str(msh), "nodes": int(nodes), "cells": int(cells), "groups": int(group_count)}


def _name_groups(
    gmsh: Any, project: Project, lz: float, cx: float, cy: float, r: float, volume: int
) -> None:
    groups: dict[str, list[int]] = {}
    tol = max(1e-7, 5e-6 * max(project.geometry.length, project.geometry.height, lz, r))
    boundary = [
        int(tag)
        for dim, tag in gmsh.model.getBoundary([(3, volume)], oriented=False, combined=False)
        if dim == 2
    ]
    caps = [tag for tag in boundary if abs(gmsh.model.getBoundingBox(2, tag)[5] - gmsh.model.getBoundingBox(2, tag)[2]) <= tol]
    sides = [tag for tag in boundary if tag not in caps]
    groups["frontAndBack"] = caps
    for tag in sides:
        xmin, ymin, _, xmax, ymax, _ = gmsh.model.getBoundingBox(2, tag)
        if abs(xmin) < tol and abs(xmax) < tol:
            groups.setdefault("inlet", []).append(tag)
        elif abs(xmin - project.geometry.length) < tol and abs(xmax - project.geometry.length) < tol:
            groups.setdefault("outlet", []).append(tag)
        elif (abs(ymin) < tol and abs(ymax) < tol) or (
            abs(ymin - project.geometry.height) < tol and abs(ymax - project.geometry.height) < tol
        ):
            groups.setdefault("walls", []).append(tag)
        else:
            groups.setdefault("cylinderWall", []).append(tag)
    assigned = sum(len(tags) for tags in groups.values())
    if assigned != len(boundary):
        raise RuntimeError(f"Clasificación de superficies incompleta: {assigned}/{len(boundary)}")
    for name, tags in groups.items():
        if not tags:
            raise RuntimeError(f"Grupo de contorno vacío: {name}")
        pg = gmsh.model.addPhysicalGroup(2, tags)
        gmsh.model.setPhysicalName(2, pg, name)
    if project.geometry.kind == "cylinder" and "cylinderWall" not in groups:
        raise RuntimeError("No se pudo identificar la superficie del cilindro en la malla")


def _parse_msh(project: Project) -> dict[str, Any] | None:
    msh = project.root / "mesh" / "case.msh"
    if not msh.exists():
        return None
    import gmsh

    with GMSH_LOCK:
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.open(str(msh))
            node_tags, coords, _ = gmsh.model.mesh.getNodes()
            lookup = {int(tag): i for i, tag in enumerate(node_tags)}
            verts = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
            points = np.round(verts, 6).reshape(-1).tolist()
            indices: list[int] = []
            types, elem_tags, elem_nodes = gmsh.model.mesh.getElements(2)
            for etype, tags, nodes in zip(types, elem_tags, elem_nodes):
                props = gmsh.model.mesh.getElementProperties(int(etype))
                nnode = int(props[3])
                arr = np.asarray(nodes, dtype=np.int64).reshape(-1, nnode)
                for row in arr:
                    local = [lookup.get(int(n), -1) for n in row]
                    if nnode == 3:
                        indices.extend(local)
                    elif nnode == 4:
                        indices.extend([local[0], local[1], local[2], local[0], local[2], local[3]])
                    elif nnode >= 6:
                        # Second-order triangles/quads: use the corner nodes.
                        corners = [local[i] for i in range(3 if props[1] == "Triangle" else 4)]
                        if len(corners) == 3:
                            indices.extend(corners)
                        else:
                            indices.extend([corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]])
            if not indices:
                return None
            return {
                "points": points,
                "indices": [i for i in indices if i >= 0],
                "point_count": len(verts),
                "triangle_count": len(indices) // 3,
            }
        finally:
            gmsh.finalize()


def mesh_preview(project: Project) -> dict[str, Any]:
    """Return the current mesh (or a generated coarse box grid) for the viewer."""
    method = mesh_method(project)
    if method == "blockMesh":
        nx, ny, _ = block_counts(project)
        g = project.geometry
        lx, ly, lz = float(g.length), float(g.height), float(g.depth)
        z = lz * 0.5
        verts: list[float] = []
        lines: list[int] = []

        def add(x: float, y: float) -> int:
            verts.extend([x, y, z])
            return len(verts) // 3 - 1

        for i in range(nx + 1):
            x = lx * i / nx
            a, b = add(x, 0), add(x, ly)
            lines.extend([a, b])
        for j in range(ny + 1):
            y = ly * j / ny
            a, b = add(0, y), add(lx, y)
            lines.extend([a, b])
        return {
            "available": True,
            "method": "blockMesh",
            "parts": [
                {
                    "name": "grid",
                    "kind": "edges",
                    "color": "#6dd3ff",
                    "opacity": 0.38,
                    "vertices": verts,
                    "indices": lines,
                }
            ],
            "cells": nx * ny,
            "dimensions": {"x": lx, "y": ly, "z": lz},
        }
    parsed = _parse_msh(project)
    if parsed:
        return {
            "available": True,
            "method": "gmsh",
            "parts": [
                {
                    "name": "mesh",
                    "kind": "mesh",
                    "color": "#6dd3ff",
                    "opacity": 0.22,
                    "vertices": parsed["points"],
                    "indices": parsed["indices"],
                }
            ],
            "cells": project.mesh.cell_count,
        }
    return {"available": False, "method": method, "parts": []}


def patch_summary(case_dir: Path) -> list[dict[str, Any]]:
    boundary = case_dir / "constant" / "polyMesh" / "boundary"
    if not boundary.exists():
        return []
    lines = boundary.read_text(encoding="utf-8", errors="replace").splitlines()
    patches: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and stripped not in ("(", ")") and i + 1 < len(lines) and lines[i + 1].strip() == "{":
            name = stripped
            patch: dict[str, Any] = {"name": name}
            j = i + 2
            while j < len(lines) and lines[j].strip() != "}":
                parts = lines[j].strip().split()
                if len(parts) >= 2:
                    key = parts[0]
                    if key == "type":
                        patch["type"] = parts[1].rstrip(";")
                    elif key == "nFaces":
                        try:
                            patch["n_faces"] = int(parts[1].rstrip(";"))
                        except ValueError:
                            pass
                j += 1
            if "type" in patch:
                patches.append(patch)
            i = j
        i += 1
    return patches


def rewrite_boundary_types(project: Project) -> list[dict[str, Any]]:
    """gmshToFoam marks every patch as 'patch'; restore wall/empty semantics."""
    from .case_writer import patch_type_map

    case = project.case
    boundary = case / "constant" / "polyMesh" / "boundary"
    if not boundary.exists():
        return []
    text = boundary.read_text(encoding="utf-8", errors="replace")
    mapping = patch_type_map(project)
    for name, patch_type in mapping.items():
        pattern = re.compile(
            r"(\n\s*" + re.escape(name) + r"\s*\n\s*\{\s*\n\s*type\s+)\w+(\s*;)",
            re.MULTILINE,
        )
        text, count = pattern.subn(lambda m: m.group(1) + patch_type + m.group(2), text, count=1)
        if count == 0:
            # Fallback for boundary files with unusual indentation.
            block = re.compile(
                r"(^\s*" + re.escape(name) + r"\s*\n\s*\{[^}]*?type\s+)\w+(\s*;)",
                re.MULTILINE | re.DOTALL,
            )
            text = block.sub(lambda m: m.group(1) + patch_type + m.group(2), text, count=1)
    boundary.write_text(text, encoding="utf-8", newline="\n")
    return patch_summary(case)


def parse_checkmesh(log_lines: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in log_lines:
        text = line.strip()
        for key, target in (("cells:", "cells"), ("points:", "points"), ("faces:", "faces")):
            if text.lower().startswith(key) and target not in result:
                try:
                    result[target] = int(text.split()[-1])
                except ValueError:
                    pass
        match = re.search(r"Max aspect ratio\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
        if match:
            result["max_aspect_ratio"] = float(match.group(1))
        match = re.search(r"Max skewness\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
        if match:
            result["max_skewness"] = float(match.group(1))
        match = re.search(r"Min volume\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
        if match:
            result["min_volume"] = float(match.group(1))
        if "Mesh OK" in text:
            result["ok"] = True
        if text.startswith("Failed"):
            result["ok"] = False
            result["failure"] = text
    return result


def estimate_cells(project: Project) -> int:
    if mesh_method(project) == "blockMesh":
        nx, ny, nz = block_counts(project)
        return nx * ny * nz
    g = project.geometry
    area = max(1e-12, float(g.length) * float(g.height) - math.pi * (float(g.diameter) / 2) ** 2)
    return max(1, int(area / max(1e-12, float(project.mesh.base_size) ** 2)))
