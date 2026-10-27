"""OpenFOAM case generation.

Only the dictionaries that FileGenFOAM Studio owns are written.  The mesh is
written by :mod:`foamstudio.meshing`; results and logs are left untouched
except when the user explicitly asks for a clean run.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Iterable

from .models import Boundary, Physics, Project

HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Website:  https://openfoam.org                  |
|   \\\\  /    A nd           | Version:  v2412                                 |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      {fmt};
    class       {cls};
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

"""

FOOTER = "\n// ************************************************************************* //\n"


def _foam_header(obj: str, cls: str = "dictionary", fmt: str = "ascii") -> str:
    return HEADER.format(fmt=fmt, cls=cls, obj=obj)


def _num(value: float) -> str:
    """Format numbers without exponent surprises and without trailing zeros."""
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return "0"
    text = f"{value:.10g}"
    return text


def _vec(value: Iterable[float]) -> str:
    vals = list(value)
    while len(vals) < 3:
        vals.append(0.0)
    return "(" + " ".join(_num(float(v)) for v in vals[:3]) + ")"


def patch_type_map(project: Project) -> dict[str, str]:
    result: dict[str, str] = {}
    for boundary in project.physics.boundaries:
        if boundary.kind == "empty":
            result[boundary.name] = "empty"
        elif boundary.kind == "symmetry":
            result[boundary.name] = "symmetry"
        elif boundary.kind in ("wall", "movingWall", "obstacle"):
            result[boundary.name] = "wall"
        else:
            result[boundary.name] = "patch"
    return result


def _bc_u(boundary: Boundary, physics: Physics) -> str:
    if boundary.kind == "empty":
        return "    {\n        type            empty;\n    }\n"
    if boundary.kind == "symmetry":
        return "    {\n        type            symmetry;\n    }\n"
    if boundary.kind == "inlet":
        velocity = list(boundary.velocity)
        if not any(abs(v) > 1e-15 for v in velocity):
            velocity = [physics.inlet_speed, 0.0, 0.0]
        return (
            "    {\n"
            "        type            fixedValue;\n"
            f"        value           uniform {_vec(velocity)};\n"
            "    }\n"
        )
    if boundary.kind == "outlet":
        return "    {\n        type            zeroGradient;\n    }\n"
    if boundary.kind == "movingWall":
        return (
            "    {\n"
            "        type            fixedValue;\n"
            f"        value           uniform {_vec(boundary.velocity)};\n"
            "    }\n"
        )
    return "    {\n        type            noSlip;\n    }\n"


def _bc_p(boundary: Boundary) -> str:
    if boundary.kind == "empty":
        return "    {\n        type            empty;\n    }\n"
    if boundary.kind == "symmetry":
        return "    {\n        type            symmetry;\n    }\n"
    if boundary.kind == "outlet":
        return (
            "    {\n"
            "        type            fixedValue;\n"
            f"        value           uniform {_num(boundary.pressure)};\n"
            "    }\n"
        )
    return "    {\n        type            zeroGradient;\n    }\n"


def _field_u(project: Project) -> str:
    lines = [
        _foam_header("U", "volVectorField"),
        "dimensions      [0 1 -1 0 0 0 0];\n\n",
        "internalField   uniform (0 0 0);\n\n",
        "boundaryField\n{\n",
    ]
    for boundary in project.physics.boundaries:
        lines.append(f"    {boundary.name}\n")
        lines.append(_bc_u(boundary, project.physics))
        lines.append("\n")
    lines.append("}\n")
    lines.append(FOOTER)
    return "".join(lines)


def _field_p(project: Project) -> str:
    lines = [
        _foam_header("p", "volScalarField"),
        "dimensions      [0 2 -2 0 0 0 0];\n\n",
        "internalField   uniform 0;\n\n",
        "boundaryField\n{\n",
    ]
    for boundary in project.physics.boundaries:
        lines.append(f"    {boundary.name}\n")
        lines.append(_bc_p(boundary))
        lines.append("\n")
    lines.append("}\n")
    lines.append(FOOTER)
    return "".join(lines)


def _control_dict(project: Project, foam_run: bool = False) -> str:
    run = project.run
    transient = project.physics.solver == "icoFoam"
    delta_t = max(run.delta_t, 1e-9)
    if transient:
        steps = max(1, int(round(run.write_interval / delta_t)))
    else:
        steps = max(1, int(round(run.write_interval)))
    end_time = run.end_time
    application = "foamRun" if foam_run else project.physics.solver
    solver_line = "solver          incompressibleFluid;\n\n" if foam_run else ""
    return (
        _foam_header("controlDict")
        + f"application     {application};\n\n"
        + solver_line
        + "startFrom       startTime;\n\n"
        + "startTime       0;\n\n"
        + "stopAt          endTime;\n\n"
        + f"endTime         {_num(end_time)};\n\n"
        + f"deltaT          {_num(delta_t)};\n\n"
        + "writeControl    timeStep;\n\n"
        + f"writeInterval   {steps};\n\n"
        + "purgeWrite      0;\n\n"
        + "writeFormat     ascii;\n\n"
        + "writePrecision  7;\n\n"
        + "writeCompression off;\n\n"
        + "timeFormat      general;\n\n"
        + "timePrecision   8;\n\n"
        + "runTimeModifiable true;\n"
        + FOOTER
    )


def _fv_schemes(project: Project) -> str:
    transient = project.physics.solver == "icoFoam"
    ddt = "Euler" if transient else "steadyState"
    div_u = "Gauss linear" if transient else "bounded Gauss linearUpwind grad(U)"
    return (
        _foam_header("fvSchemes")
        + "ddtSchemes\n{\n"
        + f"    default         {ddt};\n"
        + "}\n\n"
        + "gradSchemes\n{\n    default         Gauss linear;\n}\n\n"
        + "divSchemes\n{\n"
        + "    default         none;\n\n"
        + f"    div(phi,U)      {div_u};\n"
        + "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        + "}\n\n"
        + "laplacianSchemes\n{\n    default         Gauss linear corrected;\n}\n\n"
        + "interpolationSchemes\n{\n    default         linear;\n}\n\n"
        + "snGradSchemes\n{\n    default         corrected;\n}\n\n"
        + FOOTER
    )


def _fv_solution(project: Project) -> str:
    transient = project.physics.solver == "icoFoam"
    has_fixed_pressure = any(b.kind == "outlet" for b in project.physics.boundaries)
    if transient:
        return (
            _foam_header("fvSolution")
            + "solvers\n{\n"
            + "    p\n    {\n"
            + "        solver          PCG;\n"
            + "        preconditioner  DIC;\n"
            + "        tolerance       1e-07;\n"
            + "        relTol          0.05;\n"
            + "    }\n\n"
            + "    pFinal\n    {\n"
            + "        solver          PCG;\n"
            + "        preconditioner  DIC;\n"
            + "        tolerance       1e-07;\n"
            + "        relTol          0;\n"
            + "    }\n\n"
            + "    U\n    {\n"
            + "        solver          smoothSolver;\n"
            + "        smoother        symGaussSeidel;\n"
            + "        tolerance       1e-06;\n"
            + "        relTol          0;\n"
            + "    }\n"
            + "}\n\n"
            + "PISO\n{\n"
            + "    nCorrectors     2;\n"
            + "    nNonOrthogonalCorrectors 0;\n"
            + "    pRefCell        0;\n"
            + "    pRefValue       0;\n"
            + "}\n"
            + FOOTER
        )

    ref = "" if has_fixed_pressure else "    pRefCell        0;\n    pRefValue       0;\n"
    return (
        _foam_header("fvSolution")
        + "solvers\n{\n"
        + "    p\n    {\n"
        + "        solver          GAMG;\n"
        + "        smoother        GaussSeidel;\n"
        + "        tolerance       1e-07;\n"
        + "        relTol          0.01;\n"
        + "    }\n\n"
        + "    U\n    {\n"
        + "        solver          smoothSolver;\n"
        + "        smoother        symGaussSeidel;\n"
        + "        tolerance       1e-06;\n"
        + "        relTol          0.1;\n"
        + "    }\n"
        + "}\n\n"
        + "SIMPLE\n{\n"
        + "    nNonOrthogonalCorrectors 0;\n"
        + "    consistent      yes;\n"
        + ref
        + "\n"
        + "    residualControl\n    {\n"
        + f"        p               {_num(project.run.convergence)};\n"
        + f"        U               {_num(project.run.convergence)};\n"
        + "    }\n"
        + "}\n\n"
        + "relaxationFactors\n{\n"
        + "    equations\n    {\n"
        + "        U               0.9;\n"
        + "        \".*\"            0.9;\n"
        + "    }\n"
        + "    fields\n    {\n"
        + "        p               0.7;\n"
        + "    }\n"
        + "}\n\n"
        + "PIMPLE\n{\n"
        + "    nOuterCorrectors 1;\n"
        + "    nCorrectors     2;\n"
        + "    nNonOrthogonalCorrectors 0;\n"
        + "    residualControl\n    {\n"
        + f"        p               {_num(project.run.convergence)};\n"
        + f"        U               {_num(project.run.convergence)};\n"
        + "    }\n"
        + "}\n"
        + FOOTER
    )


def _transport_properties(project: Project) -> str:
    return (
        _foam_header("transportProperties")
        + "transportModel  Newtonian;\n\n"
        + f"nu              {_num(project.physics.nu)};\n"
        + FOOTER
    )


def _turbulence_properties(project: Project) -> str:
    simulation = "laminar" if project.physics.turbulence == "laminar" else "RAS"
    return (
        _foam_header("turbulenceProperties")
        + f"simulationType  {simulation};\n"
        + ("\nRAS\n{\n    model           kOmegaSST;\n    turbulence      on;\n    printCoeffs     on;\n}\n" if simulation == "RAS" else "")
        + FOOTER
    )


def _physical_properties(project: Project) -> str:
    return (
        _foam_header("physicalProperties")
        + "viscosityModel  constant;\n\n"
        + f"nu              {_num(project.physics.nu)};\n"
        + FOOTER
    )


def _momentum_transport(project: Project) -> str:
    return (
        _foam_header("momentumTransport")
        + "simulationType  laminar;\n"
        + FOOTER
    )


def _case_foam(project: Project) -> Path:
    marker = project.case / f"{project.case.name}.foam"
    marker.touch(exist_ok=True)
    return marker


def write_case(project: Project, foam_run: bool = False) -> Path:
    """Write all user-editable OpenFOAM dictionaries for the current project."""
    project.ensure_dirs()
    case = project.case
    (case / "0").mkdir(parents=True, exist_ok=True)
    (case / "constant").mkdir(parents=True, exist_ok=True)
    (case / "system").mkdir(parents=True, exist_ok=True)

    files = {
        case / "0" / "U": _field_u(project),
        case / "0" / "p": _field_p(project),
        case / "constant" / "transportProperties": _transport_properties(project),
        case / "constant" / "turbulenceProperties": _turbulence_properties(project),
        case / "constant" / "physicalProperties": _physical_properties(project),
        case / "constant" / "momentumTransport": _momentum_transport(project),
        case / "system" / "controlDict": _control_dict(project, foam_run=foam_run),
        case / "system" / "fvSchemes": _fv_schemes(project),
        case / "system" / "fvSolution": _fv_solution(project),
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    _case_foam(project)
    return case


def clean_results(project: Project) -> list[str]:
    """Remove time directories other than 0 before a fresh solver run."""
    removed: list[str] = []
    case = project.case
    if not case.exists():
        return removed
    for item in case.iterdir():
        if not item.is_dir():
            continue
        try:
            value = float(item.name)
        except ValueError:
            continue
        if value > 0:
            shutil.rmtree(item, ignore_errors=True)
            removed.append(item.name)
    project.last_run = {}
    return removed


def time_directories(case: Path) -> list[tuple[float, str]]:
    result: list[tuple[float, str]] = []
    if not case.exists():
        return result
    for item in case.iterdir():
        if item.is_dir() and (item / "U").exists():
            try:
                result.append((float(item.name), item.name))
            except ValueError:
                pass
    return sorted(result)
