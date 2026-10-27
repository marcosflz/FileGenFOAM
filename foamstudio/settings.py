"""Application paths and persistent user settings."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_data_dir() -> Path:
    override = os.environ.get("FOAMSTUDIO_DATA")
    if override:
        return Path(override).expanduser().resolve()
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "FileGenFOAM"
    return Path.home() / ".filegenfoam"


def default_projects_dir() -> Path:
    override = os.environ.get("FOAMSTUDIO_PROJECTS")
    if override:
        return Path(override).expanduser().resolve()
    documents = Path.home() / "Documents"
    if not documents.exists():
        documents = Path.home()
    return documents / "FileGenFOAM"


@dataclass
class Settings:
    projects_dir: str = field(default_factory=lambda: str(default_projects_dir()))
    last_project: str | None = None
    runtime_id: str = "auto"
    bluecfd_path: str | None = None
    wsl_distro: str | None = None
    wsl_env: str = "~/foamenv"
    micromamba: str | None = None
    theme: str = "dark"
    first_run: bool = True

    @property
    def file(self) -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                allowed = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in data.items() if k in allowed})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        path = self.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @property
    def projects_path(self) -> Path:
        path = Path(self.projects_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
