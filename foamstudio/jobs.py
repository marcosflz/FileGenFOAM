"""Background job execution with live logs, residuals and cancellation."""

from __future__ import annotations

import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .runtimes import NO_WINDOW, Runtime

TIME_RE = re.compile(r"^Time = ([0-9.eE+\-]+)\s*$")
RESIDUAL_RE = re.compile(
    r"Solving for ([A-Za-z0-9_]+), Initial residual = ([0-9.eE+\-]+), "
    r"Final residual = ([0-9.eE+\-]+), No Iterations ([0-9]+)"
)
CONTINUITY_RE = re.compile(
    r"time step continuity errors\s*:\s*sum local = ([0-9.eE+\-]+), "
    r"global = ([0-9.eE+\-]+), cumulative = ([0-9.eE+\-]+)"
)
ERROR_HINTS = (
    "FOAM FATAL ERROR",
    "FOAM FATAL IO ERROR",
    "FOAM exiting",
    "Segmentation fault",
    "error:",
    "ERROR:",
    "command not found",
)
CHECK_KEYS = (
    "cells:",
    "points:",
    "faces:",
    "internal faces:",
    "boundary faces:",
    "Max aspect ratio",
    "Min volume",
    "Max skewness",
    "Mesh OK",
    "Failed",
)


@dataclass
class Job:
    id: str
    kind: str
    label: str
    log_path: Path | None = None
    status: str = "running"
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = field(default_factory=time.time)
    ended_at: float | None = None
    returncode: int | None = None
    lines: list[str] = field(default_factory=list)
    total_lines: int = 0
    residuals: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    runtime: Runtime | None = None
    case_dir: Path | None = None
    process: subprocess.Popen[str] | None = None
    _cancel: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _current_residual: dict[str, float] = field(default_factory=dict)
    _current_time: float | None = None
    _file: Any = None

    def __post_init__(self) -> None:
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.log_path.open("a", encoding="utf-8", buffering=1)

    def append(self, line: str) -> None:
        clean = line.rstrip("\r\n")
        with self._lock:
            self.lines.append(clean)
            self.total_lines += 1
            if len(self.lines) > 6000:
                del self.lines[:1000]
            if self._file:
                self._file.write(clean + "\n")
        self._parse(clean)

    def append_many(self, text: str) -> None:
        for line in text.splitlines():
            self.append(line)

    def _parse(self, line: str) -> None:
        match = TIME_RE.match(line)
        if match:
            value = float(match.group(1))
            if self._current_time is not None and self._current_residual:
                self._commit_residual()
            self._current_time = value
            return
        match = RESIDUAL_RE.search(line)
        if match:
            field_name, initial = match.group(1), float(match.group(2))
            self._current_residual[field_name] = initial
            self._maybe_commit_residual()
            return
        match = CONTINUITY_RE.search(line)
        if match:
            self._current_residual["continuity"] = abs(float(match.group(2)))
            self._maybe_commit_residual()
            return
        if any(hint in line for hint in ERROR_HINTS):
            with self._lock:
                if "FOAM FATAL" in line:
                    self.result["fatal"] = line.strip()
                if line.strip() and line.strip() not in self.errors and not line.strip().startswith(("Traceback", "File \"", "During handling")):
                    self.errors.append(line.strip())

    def _maybe_commit_residual(self) -> None:
        # A residual block for a given time usually has Ux, Uy and p.  Keep
        # appending to the same point until the next Time header.
        if self._current_time is None:
            return
        if self.residuals and self.residuals[-1].get("time") == self._current_time:
            self.residuals[-1].update(self._current_residual)
        elif len(self._current_residual) >= 2:
            self.residuals.append({"time": self._current_time, **self._current_residual})

    def _commit_residual(self) -> None:
        if self._current_time is None:
            return
        if len(self._current_residual) >= 1:
            if self.residuals and self.residuals[-1].get("time") == self._current_time:
                self.residuals[-1].update(self._current_residual)
            else:
                self.residuals.append({"time": self._current_time, **self._current_residual})
        self._current_residual = {}

    def set_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, value))

    def finish(self, status: str, returncode: int | None = None, result: dict[str, Any] | None = None) -> None:
        self._commit_residual()
        with self._lock:
            self.status = status
            self.returncode = returncode
            self.ended_at = time.time()
            if result:
                self.result.update(result)
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    def public(self, after: int = 0) -> dict[str, Any]:
        with self._lock:
            lines = self.lines
            start = max(0, after - (self.total_lines - len(lines)))
            visible = lines[start:]
            cursor = self.total_lines
            payload = {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "status": self.status,
                "progress": self.progress,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "duration": (self.ended_at or time.time()) - (self.started_at or self.created_at),
                "returncode": self.returncode,
                "log": visible,
                "cursor": cursor,
                "residuals": list(self.residuals),
                "errors": list(self.errors),
                "result": dict(self.result),
            }
        return payload

    def request_cancel(self) -> None:
        self._cancel = True
        runtime = self.runtime
        case = self.case_dir
        if runtime and case:
            try:
                kill = runtime.kill_argv(case)
                if kill:
                    subprocess.run(kill, capture_output=True, timeout=15, creationflags=NO_WINDOW)
            except Exception:
                pass
        proc = self.process
        if proc and proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=15,
                    creationflags=NO_WINDOW,
                )
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    @property
    def cancelled(self) -> bool:
        return self._cancel


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def active(self) -> Job | None:
        with self._lock:
            for job in self._jobs.values():
                if job.status == "running":
                    return job
        return None

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self) -> Job | None:
        with self._lock:
            if not self._jobs:
                return None
            return max(self._jobs.values(), key=lambda j: j.created_at)

    def start(
        self,
        kind: str,
        label: str,
        worker: Callable[[Job], dict[str, Any] | None],
        *,
        log_path: Path | None = None,
        runtime: Runtime | None = None,
        case_dir: Path | None = None,
    ) -> Job:
        active = self.active()
        if active:
            raise RuntimeError(f"Ya hay un trabajo en curso: {active.label}")
        job = Job(
            id=uuid.uuid4().hex[:10],
            kind=kind,
            label=label,
            log_path=log_path,
            runtime=runtime,
            case_dir=case_dir,
        )
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job, worker), daemon=True, name=f"job-{kind}")
        thread.start()
        return job

    def _run(self, job: Job, worker: Callable[[Job], dict[str, Any] | None]) -> None:
        try:
            result = worker(job) or {}
            status = "cancelled" if job.cancelled else "completed"
            job.finish(status, 0, result)
        except Exception as exc:  # pragma: no cover - exercised via API tests
            job.append(f"ERROR: {exc}")
            import traceback

            job.append(traceback.format_exc())
            job.finish("cancelled" if job.cancelled else "failed", 1, {"error": str(exc)})


def run_shell_job(
    job: Job,
    command: list[str],
    *,
    progress_end: float | None = None,
    parse_checkmesh: bool = False,
) -> dict[str, Any]:
    """Run a subprocess and stream its output into the job."""
    if job.runtime is None or job.case_dir is None:
        raise RuntimeError("Job has no runtime/case")
    argv = job.runtime.argv_for(job.case_dir, command)
    job.append("$ " + " ".join(command))
    job.append("  runtime: " + job.runtime.label)
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=NO_WINDOW,
        env=job.runtime.process_env(),
    )
    job.process = process
    assert process.stdout is not None
    for line in process.stdout:
        if job.cancelled:
            break
        job.append(line)
        if parse_checkmesh and any(key in line for key in CHECK_KEYS):
            job.result.setdefault("check", []).append(line.strip())
        match = TIME_RE.match(line.rstrip("\r\n"))
        if match and progress_end and progress_end > 0:
            job.set_progress(float(match.group(1)) / progress_end)
    returncode = process.wait()
    job.returncode = returncode
    if job.cancelled:
        raise RuntimeError("Simulación cancelada por el usuario")
    if returncode != 0:
        detail = job.result.get("fatal") or next((e for e in reversed(job.errors) if e), "el proceso terminó con errores")
        raise RuntimeError(f"OpenFOAM terminó con código {returncode}: {detail}")
    job.set_progress(1.0)
    return {"returncode": returncode}
