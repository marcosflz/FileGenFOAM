"""Local HTTP API and desktop shell."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import geometry as geometry_service
from . import meshing
from . import results as result_service
from .case_writer import clean_results, time_directories, write_case
from .jobs import Job, JobManager, run_shell_job
from .models import Boundary, Geometry, Project, slugify
from .presets import FLUIDS, PRESETS, build_project, public_presets
from .runtimes import RuntimeService
from .settings import Settings

APP_TITLE = "FileGenFOAM Studio"
APP_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DEMO_DIR = ROOT / "examples" / "lid-driven-cavity"
UPLOAD_LIMIT = 80 * 1024 * 1024


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.runtimes = RuntimeService(settings)
        self.jobs = JobManager()
        self.project: Project | None = None
        self.lock = threading.RLock()
        self._load_initial()

    def _load_initial(self) -> None:
        if self.settings.last_project:
            path = Path(self.settings.last_project)
            if (path / "project.json").exists():
                try:
                    self.project = Project.load(path)
                    return
                except Exception:
                    pass
        demo = self.settings.projects_path / "lid-driven-cavity"
        if (demo / "project.json").exists():
            try:
                self.project = Project.load(demo)
            except Exception:
                self.project = None

    def set_project(self, project: Project | None) -> None:
        with self.lock:
            self.project = project
            if project:
                self.settings.last_project = str(project.root)
                self.settings.first_run = False
            else:
                self.settings.last_project = None
            self.settings.save()

    def save(self) -> None:
        if self.project:
            self.project.save()

    def runtime(self):
        return self.runtimes.select()

    def state(self) -> dict[str, Any]:
        with self.lock:
            project = self.project
            runtime = self.runtimes.public()
            if not project:
                return {
                    "project": None,
                    "runtime": runtime,
                    "presets": public_presets(),
                    "fluids": FLUIDS,
                    "app": {"title": APP_TITLE, "version": APP_VERSION, "demo_available": (DEMO_DIR / "project.json").exists()},
                    "recent": self.recent_projects(),
                }
            data = project.to_dict()
            data["has_mesh"] = project.has_mesh
            data["has_results"] = project.has_results
            data["times"] = result_service.list_times(project.case) if project.has_results else []
            data["case_path"] = str(project.case)
            data["estimate_cells"] = meshing.estimate_cells(project)
            data["mesh_method"] = meshing.mesh_method(project)
            data["patches"] = meshing.patch_summary(project.case)
            data["logs"] = self.log_files(project)
            data["demo"] = project.root.name == "lid-driven-cavity"
            data["results"] = result_service.result_summary(project.case) if project.has_results else {"available": False}
            return {
                "project": data,
                "runtime": runtime,
                "presets": public_presets(),
                "fluids": FLUIDS,
                "app": {"title": APP_TITLE, "version": APP_VERSION, "demo_available": (DEMO_DIR / "project.json").exists()},
                "recent": self.recent_projects(),
            }

    def recent_projects(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            for child in self.settings.projects_path.iterdir():
                file = child / "project.json"
                if file.exists():
                    try:
                        data = json.loads(file.read_text(encoding="utf-8"))
                        items.append(
                            {
                                "name": data.get("name", child.name),
                                "path": str(child),
                                "preset": data.get("preset", ""),
                                "stage": data.get("stage", ""),
                                "updated_at": data.get("updated_at", ""),
                            }
                        )
                    except Exception:
                        continue
        except Exception:
            pass
        items.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        return items[:8]

    def log_files(self, project: Project) -> list[dict[str, Any]]:
        logs = project.root / "logs"
        if not logs.exists():
            return []
        files = sorted(logs.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime} for p in files[:12]]


def _project_payload(ctx: AppContext) -> dict[str, Any]:
    return ctx.state()


def _require_project(ctx: AppContext) -> Project:
    if not ctx.project:
        raise ApiError("No hay ningún proyecto abierto", 409)
    return ctx.project


def _ensure_idle(ctx: AppContext) -> None:
    active = ctx.jobs.active()
    if active:
        raise ApiError(f"Hay un trabajo en curso ({active.label}). Espera o deténlo antes de modificar el caso.", 409)


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _unique_folder(base: Path, name: str) -> Path:
    slug = slugify(name)
    candidate = base / slug
    index = 2
    while candidate.exists():
        candidate = base / f"{slug}-{index}"
        index += 1
    return candidate


def _copy_demo(settings: Settings) -> Project:
    if not (DEMO_DIR / "project.json").exists():
        raise ApiError("El caso demo no está incluido en esta instalación", 404)
    target = settings.projects_path / "lid-driven-cavity"
    if not (target / "project.json").exists():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(DEMO_DIR, target)
    project = Project.load(target)
    project.path = str(target)
    project.save()
    return project


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.load()
    settings.projects_path.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = UPLOAD_LIMIT
    app.config["CTX"] = AppContext(settings)
    ctx: AppContext = app.config["CTX"]
    if ctx.project is None and (DEMO_DIR / "project.json").exists():
        try:
            ctx.set_project(_copy_demo(settings))
        except Exception:
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return jsonify({"error": exc.message}), exc.status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.description}), exc.code
        return exc

    @app.errorhandler(Exception)
    def handle_error(exc: Exception):
        app.logger.exception("Unhandled API error")
        return jsonify({"error": str(exc)}), 500

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "version": APP_VERSION})

    @app.get("/api/state")
    def state():
        return jsonify(ctx.state())

    @app.post("/api/project/new")
    def project_new():
        payload = request.get_json(force=True, silent=True) or {}
        preset = payload.get("preset", "cavity")
        if preset not in PRESETS:
            raise ApiError(f"Plantilla desconocida: {preset}")
        name = (payload.get("name") or PRESETS[preset]["label"]).strip()
        folder = _unique_folder(ctx.settings.projects_path, name)
        project = build_project(preset, name, str(folder))
        project.save()
        ctx.set_project(project)
        return jsonify(_project_payload(ctx)), 201

    @app.post("/api/project/open")
    def project_open():
        payload = request.get_json(force=True, silent=True) or {}
        raw = payload.get("path")
        if not raw:
            raise ApiError("Falta la ruta del proyecto")
        path = Path(raw).expanduser()
        if not (path / "project.json").exists():
            raise ApiError("La carpeta no contiene project.json", 404)
        project = Project.load(path)
        ctx.set_project(project)
        return jsonify(_project_payload(ctx))

    @app.post("/api/project/save")
    def project_save():
        project = _require_project(ctx)
        project.save()
        return jsonify(_project_payload(ctx))

    @app.post("/api/project/update")
    def project_update():
        project = _require_project(ctx)
        payload = request.get_json(force=True, silent=True) or {}
        if "name" in payload and str(payload["name"]).strip():
            project.name = str(payload["name"]).strip()[:120]
        if "notes" in payload:
            project.notes = str(payload["notes"])[:5000]
        if "stage" in payload and payload["stage"] in ("geometry", "mesh", "physics", "run", "results"):
            project.stage = payload["stage"]
        project.save()
        return jsonify(_project_payload(ctx))

    @app.post("/api/project/demo")
    def project_demo():
        project = _copy_demo(ctx.settings)
        ctx.set_project(project)
        return jsonify(_project_payload(ctx))

    @app.post("/api/project/gallery")  # convenience alias for the welcome screen
    def project_gallery():
        return jsonify({"projects": ctx.recent_projects()})

    @app.post("/api/geometry")
    def geometry_update():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        payload = request.get_json(force=True, silent=True) or {}
        current = project.geometry.to_dict()
        current.update(payload)
        for key in ("length", "height", "depth", "diameter", "center_x", "center_y", "stl_scale"):
            try:
                current[key] = max(1e-6, float(current.get(key, getattr(project.geometry, key))))
            except (TypeError, ValueError):
                raise ApiError(f"Valor no válido para {key}")
        if current.get("kind") not in ("cavity", "duct", "cylinder", "stl"):
            raise ApiError("Tipo de geometría no soportado")
        old = project.geometry.to_dict()
        project.geometry = Geometry.from_dict(current)
        if old != project.geometry.to_dict():
            meshing.invalidate_mesh(project)
        project.save()
        return jsonify({"project": _project_payload(ctx)["project"], "preview": geometry_service.geometry_preview(project)})

    @app.get("/api/geometry/preview")
    def geometry_preview():
        project = _require_project(ctx)
        if request.args.get("mesh") == "1" and (project.has_mesh or (project.root / "mesh" / "case.msh").exists()):
            return jsonify(meshing.mesh_preview(project))
        return jsonify(geometry_service.geometry_preview(project))

    @app.post("/api/mesh/settings")
    def mesh_settings():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        payload = request.get_json(force=True, silent=True) or {}
        try:
            if "base_size" in payload:
                project.mesh.base_size = max(1e-5, float(payload["base_size"]))
            if "refine_obstacle" in payload:
                project.mesh.refine_obstacle = max(1.0, min(6.0, float(payload["refine_obstacle"])))
            if "preset" in payload:
                project.mesh.preset = str(payload["preset"])
        except (TypeError, ValueError):
            raise ApiError("Parámetros de malla no válidos")
        meshing.invalidate_mesh(project)
        project.save()
        return jsonify({"project": _project_payload(ctx)["project"]})

    @app.post("/api/physics")
    def physics_update():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        payload = request.get_json(force=True, silent=True) or {}
        from .models import Physics

        data = project.physics.to_dict()
        previous_solver = project.physics.solver
        data.update({k: v for k, v in payload.items() if k in ("solver", "fluid", "density", "nu", "inlet_speed", "turbulence", "boundaries")})
        if data.get("solver") not in ("icoFoam", "simpleFoam"):
            raise ApiError("Solver no soportado")
        if data.get("turbulence") not in ("laminar",):
            raise ApiError("En el MVP solo está disponible el régimen laminar")
        try:
            data["density"] = max(1e-6, float(data.get("density", project.physics.density)))
            data["nu"] = max(1e-12, float(data.get("nu", project.physics.nu)))
            data["inlet_speed"] = float(data.get("inlet_speed", project.physics.inlet_speed))
        except (TypeError, ValueError):
            raise ApiError("Valores físicos no válidos")
        boundaries = data.get("boundaries")
        if isinstance(boundaries, list):
            cleaned = []
            for boundary in boundaries:
                if not isinstance(boundary, dict) or not boundary.get("name"):
                    continue
                if boundary.get("kind") not in ("inlet", "outlet", "wall", "movingWall", "empty", "symmetry"):
                    raise ApiError("Tipo de condición de contorno no válido")
                cleaned.append(Boundary.from_dict(boundary))
            data["boundaries"] = cleaned
        project.physics = Physics.from_dict(data)
        if project.has_mesh:
            patches = meshing.rewrite_boundary_types(project)
            project.mesh.patches = [p["name"] for p in patches]
        # Sensible solver-specific defaults when switching regime.
        if project.physics.solver != previous_solver:
            if project.physics.solver == "simpleFoam" and project.run.end_time < 10:
                project.run.end_time = 500
                project.run.delta_t = 1.0
                project.run.write_interval = 50
            if project.physics.solver == "icoFoam" and project.run.end_time > 10:
                project.run.end_time = 0.5
                project.run.delta_t = 0.005
                project.run.write_interval = 0.05
        project.save()
        return jsonify(_project_payload(ctx))

    @app.post("/api/run/settings")
    def run_settings():
        project = _require_project(ctx)
        payload = request.get_json(force=True, silent=True) or {}
        try:
            if "end_time" in payload:
                project.run.end_time = max(1e-9, float(payload["end_time"]))
            if "delta_t" in payload:
                project.run.delta_t = max(1e-12, float(payload["delta_t"]))
            if "write_interval" in payload:
                project.run.write_interval = max(1e-9, float(payload["write_interval"]))
            if "convergence" in payload:
                project.run.convergence = max(1e-12, float(payload["convergence"]))
        except (TypeError, ValueError):
            raise ApiError("Parámetros de simulación no válidos")
        project.save()
        return jsonify(_project_payload(ctx))


    @app.post("/api/geometry/upload")
    def geometry_upload():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        upload = request.files.get("file")
        if not upload or not upload.filename:
            raise ApiError("No se recibió ningún archivo STL")
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in (".stl",):
            raise ApiError("Formato no soportado. Usa un STL ASCII o binario.")
        safe = slugify(Path(upload.filename).stem) + ".stl"
        target = project.root / "uploads" / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        upload.save(target)
        try:
            geometry_service.parse_stl(target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise ApiError(f"STL no válido: {exc}")
        project.geometry.kind = "stl"
        project.geometry.stl_file = str(target.relative_to(project.root)).replace("\\", "/")
        preset = PRESETS["stl"]
        from .models import Physics, RunSettings

        project.physics = Physics.from_dict(preset["physics"])
        project.run = RunSettings.from_dict(preset["run"])
        project.preset = "stl"
        meshing.invalidate_mesh(project)
        project.save()
        return jsonify(
            {
                "project": _project_payload(ctx)["project"],
                "preview": geometry_service.geometry_preview(project),
            }
        )

    @app.post("/api/mesh")
    def mesh_start():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        runtime = ctx.runtime()
        if not runtime.available:
            raise ApiError("No hay un motor OpenFOAM disponible. Instala BlueCFD-Core o configura WSL.", 409)
        if meshing.mesh_method(project) == "gmsh" and project.geometry.kind == "stl":
            raise ApiError("El mallado de STL estará disponible en la siguiente iteración. Usa cavidad, conducto o cilindro.")
        clean_results(project)
        project.last_run = {}
        project.mesh.cell_count = None
        project.mesh.generated_at = None
        project.mesh.quality = {}
        project.stage = "mesh"
        project.save()

        def worker(job: Job) -> dict[str, Any]:
            write_case(project)
            method = meshing.mesh_method(project)
            job.append(f"Mallador: {method}")
            if method == "blockMesh":
                meshing.write_block_mesh_dict(project)
                job.set_progress(0.08)
                run_shell_job(job, ["blockMesh"], progress_end=None)
                job.set_progress(0.55)
            else:
                job.append("Generando malla con gmsh...")
                info = meshing._gmsh_mesh(project, log=job.append)
                job.set_progress(0.4)
                if job.cancelled:
                    raise RuntimeError("Mallado cancelado")
                job.append("Convirtiendo a OpenFOAM con gmshToFoam...")
                run_shell_job(job, ["gmshToFoam", "../mesh/case.msh"], progress_end=None)
                job.set_progress(0.7)
            job.append("Aplicando tipos de patch (wall / empty)...")
            patches = meshing.rewrite_boundary_types(project)
            job.append("Ejecutando checkMesh...")
            run_shell_job(job, ["checkMesh"], parse_checkmesh=True)
            stats = meshing.parse_checkmesh(job.result.get("check", []))
            if not stats.get("cells"):
                stats["cells"] = meshing.estimate_cells(project)
            project.mesh.cell_count = stats.get("cells")
            project.mesh.nodes = stats.get("points")
            project.mesh.patches = [p["name"] for p in patches]
            project.mesh.quality = stats
            project.mesh.generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            project.save()
            job.set_progress(1.0)
            return {"cells": project.mesh.cell_count, "patches": project.mesh.patches, "quality": stats}

        job = ctx.jobs.start(
            "mesh",
            "Mallado",
            worker,
            log_path=project.root / "logs" / f"mesh-{time.strftime('%Y%m%d-%H%M%S')}.log",
            runtime=runtime,
            case_dir=project.case,
        )
        return jsonify({"job": job.public()}), 202

    @app.post("/api/run/check")
    def run_check():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        runtime = ctx.runtime()
        if not runtime.available:
            raise ApiError("No hay un motor OpenFOAM disponible", 409)
        if not project.has_mesh:
            raise ApiError("Primero genera la malla", 409)

        def worker(job: Job) -> dict[str, Any]:
            run_shell_job(job, ["checkMesh"], parse_checkmesh=True)
            stats = meshing.parse_checkmesh(job.result.get("check", []))
            project.mesh.quality = stats
            project.save()
            return {"quality": stats}

        job = ctx.jobs.start(
            "check",
            "checkMesh",
            worker,
            log_path=project.root / "logs" / f"check-{time.strftime('%Y%m%d-%H%M%S')}.log",
            runtime=runtime,
            case_dir=project.case,
        )
        return jsonify({"job": job.public()}), 202

    @app.post("/api/run")
    def run_start():
        project = _require_project(ctx)
        _ensure_idle(ctx)
        runtime = ctx.runtime()
        if not runtime.available:
            raise ApiError("No hay un motor OpenFOAM disponible. Instala BlueCFD-Core o configura WSL.", 409)
        if not project.has_mesh:
            raise ApiError("La malla no está lista. Genera la malla antes de simular.", 409)
        payload = request.get_json(force=True, silent=True) or {}
        clean = bool(payload.get("clean", True))
        solver = project.physics.solver
        foam_run = runtime.uses_foam_run and solver == "simpleFoam"
        write_case(project, foam_run=foam_run)
        if clean:
            clean_results(project)
        project.stage = "run"
        project.last_run = {"status": "running", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        project.save()
        end = float(project.run.end_time)

        def worker(job: Job) -> dict[str, Any]:
            job.append(f"Solver: {solver}" + (" (foamRun · incompressibleFluid)" if foam_run else ""))
            job.append(f"Caso: {project.case}")
            command = runtime.solver_command(solver)
            if runtime.kind == "wsl":
                command += ["-case", runtime.wsl_path(project.case)]
            try:
                run_shell_job(job, command, progress_end=end)
            except Exception:
                project.last_run = {
                    "status": "failed",
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "error": job.errors[-1] if job.errors else "Error del solver",
                    "series": job.residuals[-600:],
                }
                project.save()
                raise
            times = time_directories(project.case)
            last = job.residuals[-1] if job.residuals else {}
            project.last_run = {
                "status": "completed",
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "times": len(times),
                "last_time": times[-1][0] if times else 0,
                "residuals": last,
                "series": job.residuals[-600:],
                "cells": project.mesh.cell_count,
                "solver": solver,
            }
            project.stage = "results"
            project.save()
            return {"last_time": project.last_run.get("last_time"), "times": len(times)}

        job = ctx.jobs.start(
            "run",
            f"Simulación {solver}",
            worker,
            log_path=project.root / "logs" / f"run-{time.strftime('%Y%m%d-%H%M%S')}.log",
            runtime=runtime,
            case_dir=project.case,
        )
        return jsonify({"job": job.public()}), 202

    @app.post("/api/jobs/<job_id>/stop")
    def job_stop(job_id: str):
        job = ctx.jobs.get(job_id)
        if not job:
            raise ApiError("Trabajo no encontrado", 404)
        job.request_cancel()
        return jsonify({"ok": True, "job": job.public()})

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = ctx.jobs.get(job_id)
        if not job:
            raise ApiError("Trabajo no encontrado", 404)
        after = request.args.get("after", type=int, default=0)
        return jsonify({"job": job.public(after)})

    @app.get("/api/jobs/latest")
    def job_latest():
        job = ctx.jobs.latest()
        if not job:
            return jsonify({"job": None})
        after = request.args.get("after", type=int, default=0)
        return jsonify({"job": job.public(after)})

    @app.get("/api/results/times")
    def results_times():
        project = _require_project(ctx)
        return jsonify({"times": result_service.list_times(project.case)})

    @app.get("/api/results/field")
    def results_field():
        project = _require_project(ctx)
        time_value = request.args.get("time", type=float)
        if time_value is None:
            raise ApiError("Falta el parámetro time")
        field = request.args.get("field", "p")
        if field not in ("p", "U", "U_mag", "U_x", "U_y", "U_z"):
            raise ApiError("Campo no soportado")
        mode = request.args.get("mode", "slice")
        if mode not in ("slice", "surface"):
            raise ApiError("Modo de visualización no soportado")
        axis = request.args.get("axis", "z")
        if axis not in ("x", "y", "z"):
            raise ApiError("Eje no soportado")
        position = request.args.get("position", type=float)
        try:
            payload = result_service.load_field(project.case, time_value, field, mode, axis, position)
        except result_service.ResultError as exc:
            raise ApiError(str(exc))
        return jsonify(payload)

    @app.post("/api/settings")
    def settings_update():
        payload = request.get_json(force=True, silent=True) or {}
        for key in ("projects_dir", "runtime_id", "bluecfd_path", "wsl_distro", "wsl_env", "micromamba"):
            if key in payload:
                setattr(ctx.settings, key, payload[key])
        ctx.settings.save()
        ctx.runtimes.discover(force=True)
        return jsonify(ctx.state())

    @app.post("/api/runtime/select")
    def runtime_select():
        payload = request.get_json(force=True, silent=True) or {}
        runtime_id = payload.get("id", "auto")
        ctx.settings.runtime_id = runtime_id
        ctx.settings.save()
        return jsonify({"runtime": ctx.runtimes.public(force=True)})

    @app.post("/api/runtime/rescan")
    def runtime_rescan():
        return jsonify({"runtime": ctx.runtimes.public(force=True)})

    @app.post("/api/open-folder")
    def open_folder():
        project = _require_project(ctx)
        payload = request.get_json(force=True, silent=True) or {}
        which = payload.get("which", "case")
        path = project.case if which == "case" else project.root
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            raise ApiError(f"No se pudo abrir la carpeta: {exc}")
        return jsonify({"ok": True, "path": str(path)})

    @app.get("/api/logs/<path:name>")
    def log_file(name: str):
        project = _require_project(ctx)
        safe = Path(name).name
        path = project.root / "logs" / safe
        if not path.exists():
            raise ApiError("Log no encontrado", 404)
        text = path.read_text(encoding="utf-8", errors="replace")
        return jsonify({"name": safe, "content": text[-200_000:]})

    return app
