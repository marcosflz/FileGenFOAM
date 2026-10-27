"""Detection and command wrapping for OpenFOAM runtimes.

BlueCFD-Core is the primary Windows runtime.  WSL is supported as a
development/CI fallback so the application can be tested on machines where
BlueCFD is not installed yet.
"""

from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import Settings

NO_WINDOW = 0
if os.name == "nt":
    NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


@dataclass
class Runtime:
    id: str
    label: str
    kind: str  # bluecfd | wsl | docker | none
    available: bool = True
    detail: str = ""
    version: str = ""
    bash: str | None = None
    distro: str | None = None
    micromamba: str | None = None
    env: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "available": self.available,
            "detail": self.detail,
            "version": self.version,
            "of_major": self.of_major,
            "uses_foam_run": self.uses_foam_run,
        }

    @property
    def of_major(self) -> int:
        """Return a comparable OpenFOAM major version.

        ESI releases use calendar versions (v2412); Foundation/BlueCFD use
        8, 11, 12. Calendar versions keep the legacy solvers, so map them to
        a large number only for display.
        """
        raw = (self.version or "").strip().lower()
        match = re.match(r"v?(\d+)", raw)
        if not match:
            return 0
        try:
            return int(match.group(1))
        except ValueError:
            return 0

    @property
    def uses_foam_run(self) -> bool:
        # OpenFOAM 11/12 (including blueCFD 2024-1) removed simpleFoam.
        return self.kind == "bluecfd" and self.of_major in (11, 12)

    def solver_command(self, solver: str) -> list[str]:
        if solver == "simpleFoam" and self.uses_foam_run:
            return ["foamRun", "-solver", "incompressibleFluid"]
        return [solver]

    def process_env(self) -> dict[str, str] | None:
        if self.kind != "bluecfd":
            return None
        env = os.environ.copy()
        env.update(HOME="/home/ofuser", USER="ofuser", USERNAME="ofuser", MSYSTEM="MINGW64")
        return env

    @property
    def shell(self) -> str:
        if self.kind == "wsl":
            return "WSL · bash"
        if self.kind == "bluecfd":
            return "BlueCFD · bash"
        return "Runtime"

    def wsl_path(self, path: str | Path) -> str:
        p = Path(path).resolve()
        drive = p.drive.rstrip(":").lower()
        tail = "/".join(p.parts[1:])
        return f"/mnt/{drive}/{tail}" if drive else p.as_posix()

    def msys_path(self, path: str | Path) -> str:
        p = Path(path).resolve()
        drive = p.drive.rstrip(":").lower()
        tail = "/".join(p.parts[1:])
        return f"/{drive}/{tail}" if drive else p.as_posix()

    def _case_path(self, case_dir: str | Path) -> str:
        return self.msys_path(case_dir) if self.kind == "bluecfd" else self.wsl_path(case_dir)

    def _wsl_argv(self, script: str) -> list[str]:
        prefix = ["wsl.exe"]
        if self.distro:
            prefix += ["-d", self.distro]
        return prefix + ["-e", "bash", "-lc", script]

    def argv_for(self, case_dir: str | Path, command: list[str]) -> list[str]:
        """Wrap a solver/utility command in the runtime shell."""
        case = self._case_path(case_dir)
        argline = " ".join(shlex.quote(str(a)) for a in command)
        inner = f"cd {shlex.quote(case)} && exec {argline}"
        if self.kind == "bluecfd":
            if not self.bash:
                raise RuntimeError("BlueCFD bash not configured")
            return [self.bash, "-c", _bluecfd_profile_prefix() + inner]
        if self.kind == "wsl":
            if self.micromamba and self.env:
                outer = (
                    f"{_wsl_shell_path(self.micromamba)} run -p {_wsl_shell_path(self.env)} "
                    f"bash -c {shlex.quote(inner)}"
                )
                return self._wsl_argv(outer)
            return self._wsl_argv(inner)
        raise RuntimeError(f"Runtime {self.id} cannot execute commands")

    def kill_argv(self, case_dir: str | Path) -> list[str] | None:
        if self.kind == "wsl":
            case = self.wsl_path(case_dir)
            script = f"pkill -TERM -f {shlex.quote(case)} 2>/dev/null || true"
            return self._wsl_argv(script)
        return None


def _run(
    argv: list[str], timeout: float = 25.0, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=NO_WINDOW,
        env=env,
    )


def _bluecfd_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(HOME="/home/ofuser", USER="ofuser", USERNAME="ofuser", MSYSTEM="MINGW64")
    return env


def _bluecfd_registry_roots() -> list[str]:
    try:
        import winreg
    except ImportError:
        return []
    found: list[str] = []
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                key = winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    except OSError:
                        continue
                    with sub:
                        try:
                            name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        except OSError:
                            continue
                        if "bluecfd" not in name.lower():
                            continue
                        for value in ("InstallLocation", "Inno Setup: App Path"):
                            try:
                                raw = winreg.QueryValueEx(sub, value)[0]
                                if raw:
                                    found.append(os.path.expandvars(str(raw)))
                            except OSError:
                                pass
    return found


def _bluecfd_profile_prefix() -> str:
    """Initialise a blueCFD shell without relying on interactive alias expansion."""
    return (
        "export PATH=/usr/local/bin:/usr/bin:/bin:/mingw64/bin:$PATH; "
        "shopt -s expand_aliases; "
        "source $HOME/.bashrc >/dev/null 2>&1; "
    )


def _ensure_bluecfd_origin(bash: str) -> None:
    """blueCFD single-user installs may miss the .blueCFDOrigin pointer."""
    install = Path(bash).parent.parent.parent.parent
    origin = install / "msys64" / "home" / "ofuser" / ".blueCFDOrigin"
    try:
        if not origin.exists():
            origin.parent.mkdir(parents=True, exist_ok=True)
            origin.write_text(str(install), encoding="ascii")
    except OSError:
        pass


def _bluecfd_candidates(settings: Settings) -> list[str]:
    candidates: list[str] = []
    if settings.bluecfd_path:
        raw = Path(settings.bluecfd_path).expanduser()
        if raw.is_file():
            candidates.append(str(raw))
        elif raw.is_dir():
            candidates.append(str(raw / "msys64" / "usr" / "bin" / "bash.exe"))
            candidates.append(str(raw / "usr" / "bin" / "bash.exe"))
            candidates.append(str(raw / "bin" / "bash.exe"))
    for env_name in ("BLUECFD_ROOT", "BLUECFD_HOME", "FOAM_INST_DIR", "WM_PROJECT_DIR"):
        raw = os.environ.get(env_name)
        if raw:
            match = re.match(r"^/([A-Za-z])/(.*)$", raw)
            if match:
                raw = f"{match.group(1).upper()}:\\" + match.group(2).replace("/", "\\")
            root = Path(raw)
            if root.name.lower().startswith("openfoam-"):
                root = root.parent
            candidates.append(str(root / "msys64" / "usr" / "bin" / "bash.exe"))
    for registry_root in _bluecfd_registry_roots():
        root = Path(registry_root)
        if root.name.lower().startswith("openfoam-"):
            root = root.parent
        candidates.append(str(root / "msys64" / "usr" / "bin" / "bash.exe"))
    patterns = [
        r"C:\blueCFD-Core*\msys64\usr\bin\bash.exe",
        r"C:\blueCFD-Core\*\msys64\usr\bin\bash.exe",
        r"C:\Program Files\blueCFD-Core*\msys64\usr\bin\bash.exe",
        r"C:\Program Files (x86)\blueCFD-Core*\msys64\usr\bin\bash.exe",
        r"C:\Program Files\blueCFD-*\msys64\usr\bin\bash.exe",
    ]
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        patterns.append(os.path.join(appdata, "blueCFD-Core*", "msys64", "usr", "bin", "bash.exe"))
    if localappdata:
        patterns.append(os.path.join(localappdata, "Programs", "blueCFD-Core*", "msys64", "usr", "bin", "bash.exe"))
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def _detect_bluecfd(settings: Settings) -> Runtime | None:
    env = _bluecfd_env()
    for bash in _bluecfd_candidates(settings):
        if not Path(bash).exists():
            continue
        _ensure_bluecfd_origin(bash)
        try:
            proc = _run(
                [bash, "-c", _bluecfd_profile_prefix() + 'echo "VERSION:$WM_PROJECT_VERSION"; command -v icoFoam || true; command -v simpleFoam || true; command -v foamRun || true'],
                timeout=60,
                env=env,
            )
        except Exception:
            continue
        output = (proc.stdout or "").strip()
        if proc.returncode == 0 and ("icoFoam" in output or "foamRun" in output):
            version = ""
            for line in output.splitlines():
                if line.startswith("VERSION:"):
                    version = line.split(":", 1)[1].strip()
            install = Path(bash).parent.parent.parent.parent
            return Runtime(
                id="bluecfd",
                label="BlueCFD-Core",
                kind="bluecfd",
                detail=f"OpenFOAM {version or 'instalado'} · {install}",
                version=version,
                bash=str(Path(bash)),
                extra={
                    "has_icoFoam": "icoFoam" in output,
                    "has_simpleFoam": "simpleFoam" in output,
                    "has_foamRun": "foamRun" in output,
                },
            )
    return None


def _wsl_shell_path(value: str) -> str:
    """Quote a WSL path for bash, expanding a leading tilde."""
    if value.startswith("~/"):
        return '"$HOME/' + value[2:].replace('"', '\\"') + '"'
    if value == "~":
        return '"$HOME"'
    return shlex.quote(value)


def _detect_wsl(settings: Settings) -> Runtime | None:
    if not shutil.which("wsl.exe"):
        return None
    distro_args = ["-d", settings.wsl_distro] if settings.wsl_distro else []

    def wsl(script: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
        return _run(["wsl.exe", *distro_args, "-e", "bash", "-lc", script], timeout=timeout)

    try:
        if wsl("echo FOAMSTUDIO_WSL_OK", timeout=15).returncode != 0:
            return None
    except Exception:
        return None

    # 1) OpenFOAM already on PATH in the user's WSL shell.
    try:
        proc = wsl('echo "VERSION:$WM_PROJECT_VERSION"; command -v simpleFoam || true')
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and "simpleFoam" in out:
            version = ""
            for line in out.splitlines():
                if line.startswith("VERSION:"):
                    version = line.split(":", 1)[1].strip()
            return Runtime(
                id="wsl",
                label="OpenFOAM en WSL",
                kind="wsl",
                detail="OpenFOAM disponible en el PATH de WSL",
                version=version,
                distro=settings.wsl_distro,
            )
    except Exception:
        pass

    # 2) Self-contained micromamba environment (used for development).
    env = settings.wsl_env or "~/foamenv"
    mm_candidates = []
    if settings.micromamba:
        mm_candidates.append(settings.micromamba)
    mm_candidates += [
        "~/bin/bin/micromamba",
        "~/bin/micromamba",
        "~/.local/bin/micromamba",
        "micromamba",
    ]
    for mm in mm_candidates:
        mm_q = _wsl_shell_path(mm)
        env_q = _wsl_shell_path(env)
        if mm.startswith("~") or mm.startswith("/") or (len(mm) > 1 and mm[1] == ":"):
            mm_setup = f"MM={mm_q}"
        else:
            mm_setup = f"MM=$(command -v {shlex.quote(mm)} 2>/dev/null || true)"
        script = (
            f"{mm_setup}; "
            f'if [ -n "$MM" ] && [ -x "$MM" ] && [ -d {env_q} ]; then '
            f"\"$MM\" run -p {env_q} bash -c "
            f"'echo VERSION:$WM_PROJECT_VERSION; command -v simpleFoam'; fi"
        )
        try:
            proc = wsl(script, timeout=40)
        except Exception:
            continue
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and "simpleFoam" in out:
            version = ""
            for line in out.splitlines():
                if line.startswith("VERSION:"):
                    version = line.split(":", 1)[1].strip()
            return Runtime(
                id="wsl",
                label="OpenFOAM en WSL",
                kind="wsl",
                detail=f"Entorno micromamba · {env}",
                version=version,
                distro=settings.wsl_distro,
                micromamba=mm,
                env=env,
            )
    return None


def _none_runtime() -> Runtime:
    return Runtime(
        id="none",
        label="Sin motor CFD",
        kind="none",
        available=False,
        detail="Instala BlueCFD-Core o configura un runtime en Ajustes.",
    )


class RuntimeService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: list[Runtime] = []
        self._cache_at = 0.0
        self._ttl = 60.0

    def discover(self, force: bool = False) -> list[Runtime]:
        if not force and self._cache and (time.time() - self._cache_at) < self._ttl:
            return self._cache
        runtimes: list[Runtime] = []
        blue = _detect_bluecfd(self.settings)
        if blue:
            runtimes.append(blue)
        wsl = _detect_wsl(self.settings)
        if wsl:
            runtimes.append(wsl)
        self._cache = runtimes
        self._cache_at = time.time()
        return runtimes

    def select(self, runtime_id: str | None = None, force: bool = False) -> Runtime:
        """Return the preferred runtime, falling back to the first available."""
        runtimes = self.discover(force=force)
        wanted = runtime_id or self.settings.runtime_id
        if wanted and wanted != "auto":
            for runtime in runtimes:
                if runtime.id == wanted:
                    return runtime
        if self.settings.runtime_id == "bluecfd":
            for runtime in runtimes:
                if runtime.kind == "bluecfd":
                    return runtime
        if runtimes:
            # BlueCFD first: it is the supported Windows backend.
            runtimes.sort(key=lambda r: 0 if r.kind == "bluecfd" else 1)
            return runtimes[0]
        return _none_runtime()

    def public(self, force: bool = False) -> dict[str, Any]:
        runtimes = self.discover(force=force)
        selected = self.select(force=False)
        return {
            "selected": selected.to_dict(),
            "available": [r.to_dict() for r in runtimes],
            "missing": not runtimes,
            "preference": self.settings.runtime_id,
        }
