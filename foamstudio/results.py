"""OpenFOAM result reading and compact serialization for the three.js viewer."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

from .case_writer import time_directories

VTK_LOCK = threading.Lock()
FIELD_LABELS = {
    "p": "Presión",
    "U": "Velocidad",
    "U_mag": "|U|",
    "U_x": "Ux",
    "U_y": "Uy",
    "U_z": "Uz",
}


class ResultError(RuntimeError):
    pass


def _marker(case_dir: Path) -> Path:
    markers = sorted(case_dir.glob("*.foam"))
    if markers:
        return markers[0]
    marker = case_dir / f"{case_dir.name}.foam"
    marker.touch(exist_ok=True)
    return marker


def list_times(case_dir: Path) -> list[dict[str, Any]]:
    return [{"value": value, "label": label} for value, label in time_directories(case_dir)]


def _reader(case_dir: Path) -> vtk.vtkOpenFOAMReader:
    reader = vtk.vtkOpenFOAMReader()
    reader.SetFileName(str(_marker(case_dir)))
    reader.UpdateInformation()
    return reader


def _time_values(reader: vtk.vtkOpenFOAMReader) -> list[float]:
    values = reader.GetTimeValues()
    return [float(values.GetValue(i)) for i in range(values.GetNumberOfValues())]


def _internal_grid(reader: vtk.vtkOpenFOAMReader) -> vtk.vtkUnstructuredGrid:
    output = reader.GetOutput()
    if output is None:
        raise ResultError("El lector VTK no devolvió datos")
    if output.IsA("vtkMultiBlockDataSet"):
        block = output.GetBlock(0)
        if block is None:
            raise ResultError("El caso no contiene una malla interna")
        return block
    return output


def _point_grid(grid: vtk.vtkUnstructuredGrid) -> vtk.vtkUnstructuredGrid:
    convert = vtk.vtkCellDataToPointData()
    convert.SetInputData(grid)
    convert.PassCellDataOn()
    convert.Update()
    return convert.GetOutput()


def _field_values(data: vtk.vtkPointData, field: str) -> tuple[np.ndarray, str]:
    if field in ("U", "U_mag", "U_x", "U_y", "U_z"):
        array = data.GetArray("U")
        if array is None:
            raise ResultError("El campo U no está disponible en este instante")
        values = vtk_to_numpy(array)
        if values.ndim == 1:
            values = values.reshape(-1, 1)
        if field == "U":
            return np.linalg.norm(values, axis=1), FIELD_LABELS["U_mag"]
        if field == "U_mag":
            return np.linalg.norm(values, axis=1), FIELD_LABELS["U_mag"]
        index = {"U_x": 0, "U_y": 1, "U_z": 2}[field]
        return values[:, index], FIELD_LABELS[field]
    array = data.GetArray(field)
    if array is None:
        raise ResultError(f"El campo '{field}' no está disponible en este instante")
    return vtk_to_numpy(array), FIELD_LABELS.get(field, field)


def _polydata_payload(polydata: vtk.vtkPolyData, field: str) -> dict[str, Any]:
    points = polydata.GetPoints()
    polys = polydata.GetPolys()
    if points is None or polys is None or points.GetNumberOfPoints() == 0:
        raise ResultError("El corte no intersecta la malla. Prueba otra posición.")
    values, label = _field_values(polydata.GetPointData(), field)

    coords = vtk_to_numpy(points.GetData()).astype(np.float32, copy=False)
    indices: list[int] = []
    if hasattr(polys, "GetOffsetsArray"):
        offsets = vtk_to_numpy(polys.GetOffsetsArray())
        connectivity = vtk_to_numpy(polys.GetConnectivityArray())
        for i in range(len(offsets) - 1):
            cell = connectivity[offsets[i] : offsets[i + 1]]
            if len(cell) >= 3:
                for j in range(1, len(cell) - 1):
                    indices.extend((int(cell[0]), int(cell[j]), int(cell[j + 1])))
    else:  # pragma: no cover - older VTK fallback
        connectivity = vtk_to_numpy(polys.GetData())
        i = 0
        while i < len(connectivity):
            n = int(connectivity[i])
            if n >= 3:
                for j in range(1, n - 1):
                    indices.extend((int(connectivity[i + 1]), int(connectivity[i + 1 + j]), int(connectivity[i + 2 + j])))
            i += n + 1
    if not indices:
        raise ResultError("La superficie no contiene triángulos")

    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ResultError("El campo no contiene valores válidos")
    vmin = float(np.min(finite))
    vmax = float(np.max(finite))
    p2, p98 = np.percentile(finite, [2, 98]) if finite.size > 20 else (vmin, vmax)

    return {
        "points": np.round(coords.reshape(-1), 6).tolist(),
        "indices": indices,
        "values": np.round(np.asarray(values, dtype=np.float64), 6).tolist(),
        "field": field,
        "field_label": label,
        "range": [vmin, vmax],
        "range_focus": [float(p2), float(p98)],
        "bounds": list(polydata.GetBounds()),
        "point_count": int(points.GetNumberOfPoints()),
        "triangle_count": len(indices) // 3,
    }


def load_field(
    case_dir: Path,
    time_value: float,
    field: str = "p",
    mode: str = "slice",
    axis: str = "z",
    position: float | None = None,
) -> dict[str, Any]:
    """Read one time step and return a triangle mesh with scalar values."""
    if not case_dir.exists():
        raise ResultError("No se encontró la carpeta del caso")
    with VTK_LOCK:
        reader = _reader(case_dir)
        times = _time_values(reader)
        if not times:
            raise ResultError("El caso no tiene resultados")
        closest = min(times, key=lambda t: abs(t - float(time_value)))
        reader.UpdateTimeStep(closest)
        grid = _internal_grid(reader)
        if grid is None or grid.GetNumberOfCells() == 0:
            raise ResultError("La malla no contiene celdas")
        point_grid = _point_grid(grid)
        bounds = point_grid.GetBounds()
        if mode == "surface":
            surface = vtk.vtkDataSetSurfaceFilter()
            surface.SetInputData(point_grid)
            surface.Update()
            polydata = surface.GetOutput()
        else:
            origin = [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]
            normals = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}
            index = {"x": 1, "y": 3, "z": 5}.get(axis, 5)
            value = origin[0 if axis == "x" else 1 if axis == "y" else 2] if position is None else float(position)
            origin[0 if axis == "x" else 1 if axis == "y" else 2] = value
            plane = vtk.vtkPlane()
            plane.SetOrigin(*origin)
            plane.SetNormal(*normals.get(axis, (0, 0, 1)))
            cutter = vtk.vtkCutter()
            cutter.SetInputData(point_grid)
            cutter.SetCutFunction(plane)
            cutter.Update()
            triangulate = vtk.vtkTriangleFilter()
            triangulate.SetInputData(cutter.GetOutput())
            triangulate.Update()
            polydata = triangulate.GetOutput()
        payload = _polydata_payload(polydata, field)
        payload["time"] = closest
        payload["mode"] = mode
        payload["axis"] = axis
        payload["mesh_bounds"] = list(bounds)
        return payload


def result_summary(case_dir: Path) -> dict[str, Any]:
    times = time_directories(case_dir)
    if not times:
        return {"available": False, "times": 0}
    return {
        "available": True,
        "times": len(times),
        "first": times[0][0],
        "last": times[-1][0],
    }
