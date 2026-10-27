#!/usr/bin/env python3
"""Read-only probe for a blueCFD-Core installation on Windows.

It looks in the Inno Setup uninstall registry keys, common install folders and
environment variables, validates the result (msys64 + OpenFOAM-*/etc/bashrc),
then optionally asks the bundled bash for the activated OpenFOAM environment.

Usage:
    python scripts/probe_bluecfd.py [--json] [--no-bash]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - this probe targets Windows
    winreg = None

TOOLS = (
    "blockMesh", "checkMesh", "snappyHexMesh", "gmshToFoam", "foamToVTK",
    "icoFoam", "simpleFoam", "foamRun", "decomposePar", "reconstructPar",
)


def from_registry() -> list[Path]:
    if winreg is None:
        return []
    found: list[Path] = []
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
                                    found.append(Path(os.path.expandvars(str(raw))))
                            except OSError:
                                pass
                        try:
                            raw = str(winreg.QueryValueEx(sub, "UninstallString")[0])
                            exe = raw.strip().strip('"').split('"')[0]
                            found.append(Path(exe).parent)
                        except OSError:
                            pass
    return found


def from_env() -> list[Path]:
    found = []
    for name in ("BLUECFD_ROOT", "BLUECFD_HOME", "FOAM_INST_DIR", "WM_PROJECT_DIR"):
        raw = os.environ.get(name)
        if not raw:
            continue
        # POSIX paths inherited from a blueCFD shell: /c/foo -> C:\foo
        m = re.match(r"^/([A-Za-z])/(.*)$", raw)
        if m:
            raw = f"{m.group(1).upper()}:\\" + m.group(2).replace("/", "\\")
        found.append(Path(raw))
    return found


def from_common_paths() -> list[Path]:
    patterns = [
        r"C:\blueCFD-Core*",
        r"C:\blueCFD-Core\*",
        r"C:\Program Files\blueCFD-Core*",
        r"C:\Program Files\blueCFD-Core*\OpenFOAM-*",
        r"C:\Program Files (x86)\blueCFD-Core*",
    ]
    for var in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            patterns.append(os.path.join(base, "blueCFD-Core*"))
            patterns.append(os.path.join(base, "Programs", "blueCFD-Core*"))
    found = []
    for pattern in patterns:
        found.extend(Path(p) for p in glob.glob(os.path.expandvars(pattern)))
    return found


def normalise_root(candidate: Path) -> Path | None:
    """Accept either the blueCFD root or .../OpenFOAM-12 and return the root."""
    try:
        p = Path(os.path.normpath(str(candidate)))
    except (TypeError, ValueError):
        return None
    if not p.exists():
        return None
    if p.name.lower().startswith("openfoam-") and (p / "etc" / "bashrc").is_file():
        p = p.parent
    if (p / "msys64" / "usr" / "bin" / "bash.exe").is_file() and any(
        p.glob("OpenFOAM-*/etc/bashrc")
    ):
        return p
    return None


def inspect(root: Path) -> dict:
    of_dirs = sorted(
        (d for d in root.iterdir() if d.is_dir() and d.name.lower().startswith("openfoam-")),
        key=lambda d: d.name.lower(),
    )
    openfoam = []
    for of in of_dirs:
        bashrc = of / "etc" / "bashrc"
        version = of.name.split("-", 1)[1] if "-" in of.name else ""
        if bashrc.is_file():
            text = bashrc.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^\s*export\s+WM_PROJECT_VERSION=(\S+)", text, re.M)
            if m:
                version = m.group(1)
        bin_dirs = sorted((of / "platforms").glob("*/bin"))
        bindir = bin_dirs[-1] if bin_dirs else None
        tools = {
            t: bool(bindir and (bindir / f"{t}.exe").is_file()) for t in TOOLS
        }
        openfoam.append({
            "dir": str(of),
            "version": version,
            "platform_bin": str(bindir) if bindir else None,
            "tools": tools,
        })
    release = None
    m = re.search(r"blueCFD-Core[- ]?(\d{4}(?:-\d+)?)", root.name, re.I)
    if m:
        release = m.group(1)
    return {
        "root": str(root),
        "release_from_folder": release,
        "bash": str(root / "msys64" / "usr" / "bin" / "bash.exe"),
        "msys64": str(root / "msys64"),
        "setvars": sorted(p.name for p in root.glob("setvars_OF*.bat")),
        "openfoam": openfoam,
    }


def probe_bash(root: Path, timeout: int = 60) -> dict:
    bash = root / "msys64" / "usr" / "bin" / "bash.exe"
    env = os.environ.copy()
    env.update(HOME="/home/ofuser", USER="ofuser", USERNAME="ofuser", MSYSTEM="MINGW64")
    script = (
        'echo __BC_BEGIN__; '
        'printf "%s\\n" "$WM_PROJECT_DIR" "$WM_PROJECT_VERSION" "$FOAM_INST_DIR"; '
        'echo __BC_END__'
    )
    try:
        p = subprocess.run(
            [str(bash), "--login", "-c", script],
            cwd=str(root), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    lines = p.stdout.splitlines()
    try:
        start = lines.index("__BC_BEGIN__") + 1
        end = lines.index("__BC_END__", start)
        values = [line.strip() for line in lines[start:end]]
    except ValueError:
        values = []
    values += [""] * (3 - len(values))
    version = values[1]
    return {
        "ok": p.returncode == 0 and bool(version),
        "returncode": p.returncode,
        "wm_project_dir": values[0] or None,
        "wm_project_version": version or None,
        "foam_inst_dir": values[2] or None,
        "stderr_tail": p.stderr[-800:] if p.stderr else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-bash", action="store_true", help="skip the bash environment probe")
    args = ap.parse_args()

    candidates: list[Path] = []
    for fn in (from_registry, from_env, from_common_paths):
        candidates.extend(fn())

    seen, roots = set(), []
    for candidate in candidates:
        root = normalise_root(candidate)
        if root is None:
            continue
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            roots.append(root)

    report = {"found": bool(roots), "installations": []}
    for root in roots:
        item = inspect(root)
        if not args.no_bash:
            item["bash_probe"] = probe_bash(root)
        report["installations"].append(item)

    if args.json:
        print(json.dumps(report, indent=2))
    elif not roots:
        print("blueCFD-Core: not found")
        print("Checked registry, BLUECFD_ROOT/FOAM_INST_DIR/WM_PROJECT_DIR, "
              "and common paths under C:\\ and %APPDATA%.")
        print("If it is installed elsewhere, pass its root via BLUECFD_ROOT.")
    else:
        for item in report["installations"]:
            print(f"root: {item['root']}")
            for of in item["openfoam"]:
                print(f"  OpenFOAM {of['version']}: {of['dir']}")
                missing = [name for name, ok in of["tools"].items() if not ok]
                print(f"  tools missing: {', '.join(missing) if missing else 'none'}")
            if item.get("bash_probe"):
                b = item["bash_probe"]
                print(f"  bash activated: {b.get('ok')}  WM_PROJECT_VERSION={b.get('wm_project_version')}")
                if b.get("stderr_tail"):
                    print(f"  bash stderr: {b['stderr_tail']}")
    return 0 if roots else 1


if __name__ == "__main__":
    sys.exit(main())
