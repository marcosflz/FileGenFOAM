# BlueCFD-Core on Windows — runtime notes

For launching OpenFOAM from an external Windows process. Verified against upstream docs, release
notes, GitHub issues and OpenFOAM 8/12 sources on 2026-10-27. **Not tested on a blueCFD machine**;
**[uncertain]** marks inferences rather than documented facts.
## 1. Releases, paths and layout
Latest release is **blueCFD-Core 2024-1** (2024-08-19, no newer GitHub release), bundling
**OpenFOAM 12**. The previous release, **2020-1**, bundles **OpenFOAM 8**.

| Release | OpenFOAM | Default MPI | MSYS2 | Install root |
|---|---|---|---|---|
| 2024-1 | 12 | MS-MPI 10.1.2 | 2024-07-22 | `C:\Program Files\blueCFD-Core 2024-1` (default, has spaces — broken) |
| 2020-1 | 8 | MS-MPI 7.1 | 2020-08-27 | typically `C:\Program Files\blueCFD-Core-2020` |
| 2017-2 / 2017-1 | 5.x | MS-MPI 7.1 / 8.1 | 2017 | `C:\Program Files\blueCFD-Core-2017` |
| 2016-2 / 2016-1 | 4.x | MS-MPI 7.1 | 2016 | `C:\Program Files\blueCFD-Core-2016` |

Upstream recommends **no spaces**: `C:\blueCFD-Core\2024-1\` (download page uses
`C:\blueCFD-Core\2024\`). The 2024-1 default path cannot source `etc/bashrc` because MSYS2's
`pwd -P` returns the long Windows path (issue #257). Installs are often renamed, e.g.
`C:\blueCFD-Core-2024`, so detect rather than hard-code. A per-user install goes under
`%APPDATA%\blueCFD-Core-*`.

```text
<root>\
  msys64\usr\bin\bash.exe
  msys64\home\ofuser\.blueCFDCore\
  OpenFOAM-12\etc\{bashrc, pre-bashrc-mingw_w64.sh}
  OpenFOAM-12\platforms\mingw_w64Gcc122DPInt32Opt\bin\*.exe
  ThirdParty-12\ ; ofuser-of12\ ; setvars_OF12.bat ; AddOns\ParaView\bin\paraview.exe
```
2020 is analogous with `OpenFOAM-8`, `ofuser-of8`, `mingw_w64GccDPInt32Opt`, `setvars_OF8.bat`.
OpenFOAM binaries are native `.exe`; MSYS2 bash only loads the environment. `FOAM_INST_DIR`,
`WM_PROJECT_DIR`, `WM_PROJECT_VERSION` are **POSIX shell variables**, not Windows system variables.
`setvars_OF*.bat` sets Windows-side values only inside that cmd process. No global `BLUECFD_ROOT`
is documented; do not require one.
## 2. Running solvers and utilities
From `cmd.exe` (set `HOME`/`USER` explicitly — see below):

```bat
set "BC=C:\blueCFD-Core\2024-1" & set "HOME=/home/ofuser" & set "USER=ofuser" & set "USERNAME=ofuser" & set "MSYSTEM=MINGW64"
"%BC%\msys64\usr\bin\bash.exe" --login -c "cd '/c/Users/name/Documents/My Project/case' && foamRun -solver incompressibleFluid"
```

From Python (argv list avoids cmd.exe quoting):

```python
import os, shlex, subprocess
from pathlib import Path
root = Path(r"C:\blueCFD-Core\2024-1"); case = Path(r"C:\Users\name\Documents\My Project\case")
msys_case = "/" + case.drive[0].lower() + str(case)[2:].replace("\\", "/")
env = os.environ.copy(); env.update(HOME="/home/ofuser", USER="ofuser", USERNAME="ofuser", MSYSTEM="MINGW64")
cmd = [str(root / "msys64/usr/bin/bash.exe"), "--login", "-c",
       f"cd {shlex.quote(msys_case)} && foamRun -solver incompressibleFluid"]
p = subprocess.Popen(cmd, cwd=case, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
```
`MSYSTEM=MINGW64` adds `<root>\msys64\mingw64\bin` (GCC runtime DLLs) to `PATH`. `HOME=/home/ofuser`
and `USER=ofuser` are essential: blueCFD's files live there, and OpenFOAM derives
`$FOAM_RUN`/`$WM_PROJECT_USER_DIR` from them. Otherwise bash inherits `USERPROFILE` and gets it wrong.

### `-lc` vs `-c`; is `/etc/profile` required?
`bash -lc 'cmd'` is `bash -l -c 'cmd'`. `--login` makes bash read `/etc/profile`, then the first of
`~/.bash_profile`, `~/.bash_login`, `~/.profile`; blueCFD's login profile activates OpenFOAM. Bare
`bash -c` reads no startup files, so `foamRun` is not on `PATH`. `-i` is unnecessary and pollutes
captured output with prompts/ANSI. So `/etc/profile` is required for the `--login` shortcut, but
never source it yourself. For `-c`, source blueCFD explicitly — **not** bare `etc/bashrc`, whose
defaults give the wrong `platforms/` directory:

```bash
# 2024-1
source "/c/blueCFD-Core/2024-1/OpenFOAM-12/etc/pre-bashrc-mingw_w64.sh" WM_MPLIB=MSMPI101
# 2020-1 (no pre-bashrc wrapper)
source "/c/blueCFD-Core-2020/OpenFOAM-8/etc/bashrc" WM_OSTYPE=MSwindows WM_COMPILER_TYPE=ThirdParty WM_COMPILER=Gcc WM_TARGET_ARCH=mingw_w64 WM_MPLIB=MSMPI71
```

### Wrapper no interactivo validado con blueCFD-Core 2020-1 (instalación por usuario)

En una instalación por usuario (`/SINGLEUSER=1`) el instalador puede no crear
`msys64/home/ofuser/.blueCFDOrigin`; sin ese archivo `mountBlueCFD` no monta la instalación y
`sourceOF` no activa nada. FileGenFOAM lo crea automáticamente con la raíz de instalación.

Además, `sourceOF` implementa la activación mediante **aliases** (`of8-64`); los aliases no se
expanden en un shell no interactivo. El wrapper que usa FileGenFOAM y que se validó con
`blockMesh`, `icoFoam` y `simpleFoam` es:

```bash
export PATH=/usr/local/bin:/usr/bin:/bin:/mingw64/bin:$PATH
shopt -s expand_aliases
source "$HOME/.bashrc" >/dev/null 2>&1
# a partir de aquí: simpleFoam, icoFoam, gmshToFoam, checkMesh...
```

`bash.exe -c "<wrapper>; cd '/c/.../case' && exec simpleFoam"` funciona con el entorno MSYS2 de
blueCFD y no imprime los avisos del perfil de login.


Do not use `--noprofile`. Verify the profile with
`bash.exe --login -c 'echo "$WM_PROJECT_VERSION $WM_PROJECT_DIR"'` before launching.

### Paths and quoting
`C:\Users\name\Documents\My Project\case` → `/c/Users/name/Documents/My Project/case`;
`D:\CFD\My Case` → `/d/CFD/My Case`; `\\nas\cases\a` → `//nas/cases/a`.
Use `cd "/c/.../My Project/case"` or `cd "$(cygpath -u 'C:\...')"`. Never pass `C:\...` unquoted:
backslashes are shell escapes. Prefer `shlex.quote`; for complex cmd/PowerShell nesting, write a
small LF-terminated `.sh` file instead of building a triply-quoted `-c` string.

```bash
cd "/c/.../case" && blockMesh && checkMesh -allGeometry -allTopology
gmshToFoam mesh.msh                 # gmsh itself is not bundled
snappyHexMesh -overwrite            # destructive; omit to keep the background mesh
simpleFoam                          # OF 8 only
foamRun -solver incompressibleFluid # OF 12
icoFoam                             # both (legacy in 12)
foamToVTK -latestTime               # writes VTK/ next to the case
```
## 3. Detecting an installation from Python
Full read-only implementation: `scripts/probe_bluecfd.py` (stdlib only; exit 1 if not found).

1. **Registry:** scan `HKLM|HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`, 64/32-bit
   views, for `DisplayName` containing `blueCFD`. Inno Setup uses `<AppId>_is1` keys and normally
   writes `InstallLocation`, `Inno Setup: App Path`, `UninstallString`; fall back to the
   uninstaller's parent folder.
2. **Paths/env:** `C:\blueCFD-Core*`, `C:\blueCFD-Core\*`, `C:\Program Files\blueCFD-Core*`
   (+ `\OpenFOAM-*`), `%APPDATA%\blueCFD-Core*`, `%LOCALAPPDATA%\Programs\blueCFD-Core*`; also
   `BLUECFD_ROOT`, and `FOAM_INST_DIR`/`WM_PROJECT_DIR` if started from a blueCFD shell
   (`/c/...` → `C:\...`).
3. **Validate:** root needs `msys64\usr\bin\bash.exe`; an OpenFOAM dir needs `etc\bashrc`. Read
   `WM_PROJECT_VERSION` from `OpenFOAM-*/etc/bashrc`, not the folder name. Accept `<root>` or
   `<root>\OpenFOAM-12`. Markers: `setvars_OF*.bat`, `msys64\home\ofuser\.blueCFDCore`. Optionally
   probe `bash.exe --login -c 'echo "$WM_PROJECT_VERSION"'` with the §2 environment to catch a
   broken profile early.

```python
import winreg
from pathlib import Path

def candidates():
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                0, winreg.KEY_READ | view) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                        try:
                            if "bluecfd" in str(winreg.QueryValueEx(sk, "DisplayName")[0]).lower():
                                yield Path(winreg.QueryValueEx(sk, "InstallLocation")[0])
                        except OSError:
                            pass
```
## 4. Gotchas
- **Install-path spaces** break 2024-1 (`pwd -P`, issue #257), including its own default. Install to
  `C:\blueCFD-Core\...`. Spaces in *case* paths work when quoted, but some third-party scripts fail.
- **CRLF vs LF:** `.sh`, `Allrun` and dictionaries should be LF; CRLF scripts fail with
  `$'\r': command not found`. Write with `open(..., newline="\n")`; `dos2unix` imported scripts
  (keep `.bat` CRLF).
- **stdout buffering:** native `.exe` output through a pipe can stall when the pipe fills. Redirect
  to a log and tail it, or drain `p.stdout` in a thread; don't assume line-by-line delivery.
  `stdbuf` generally does not affect native Windows executables **[uncertain]**.
- **Killing bash ≠ killing the solver:** the solver is a separate Windows process. Use a Job Object
  with kill-on-close, or `taskkill /PID <bash_pid> /T /F`; `Popen.terminate()` leaves the solver.
- **`HOME`/`USERPROFILE`:** inheriting the Windows profile sends OpenFOAM user dirs to
  `C:\Users\<you>`; set `HOME=/home/ofuser`, `USER=ofuser`, `USERNAME=ofuser` (CfdOF does this).
- **MPI:** MS-MPI must match the build (10.1.2 for 2024-1, 7.1 for 2020-1); versions are generally
  not interchangeable. `decomposePar` → `mpiexec -n N foamRun -parallel` (12) or
  `mpiexec -n N simpleFoam -parallel` (8) → `reconstructPar`. MS-MPI provides `mpiexec`; don't
  assume `mpirun` exists. Installing MS-MPI needs admin.
- **No admin:** per-user install (`/SINGLEUSER=1` or automatic for a non-admin account) under
  `%APPDATA%` works for serial. `Program Files`, write-permission changes and MS-MPI need admin.
- **Long paths / destructive flags:** keep root/case short; >260 characters hits Windows limits
  (2024-1's 8.3 short-name workaround is unavailable on some volumes/Server editions).
  `snappyHexMesh -overwrite` replaces the mesh; `checkMesh` returns non-zero on failure, so check
  the exit code, not just the log.
## 5. OpenFOAM 8 / 9 / 10 / 12 compatibility
There is **no blueCFD build of OpenFOAM 9 or 10**: 2020-1 = 8, 2024-1 = 12. A `Version: 10` header
in a `FoamFile` block is informational and is not rejected; dictionary vocabulary and the solver
binary are what matter.

| Item | 2020-1 (OF 8) | 2024-1 (OF 12) |
|---|---|---|
| `icoFoam` | yes | yes (`applications/legacy`) |
| `simpleFoam` | yes | **no** — use `foamRun -solver incompressibleFluid` |
| `foamRun` | no | yes (needs `solver` in `controlDict` or `-solver`) |
| `blockMesh`, `checkMesh`, `snappyHexMesh` | yes | yes |
| `gmshToFoam`, `foamToVTK` | yes | yes |

OF 8 uses `constant/transportProperties` (`transportModel Newtonian; nu ...`) and
`constant/turbulenceProperties`; OF 10/12 use `constant/physicalProperties`
(`viscosityModel constant; nu ...`) and `constant/momentumTransport` (`model kEpsilon;`). OF 12 also
needs `solver incompressibleFluid;` in `controlDict`. An OF-10-style `simpleFoam` case therefore
does not run as-is on either release; `icoFoam` runs on both but its constants follow the same split.
`blockMesh`/`snappyHexMesh` dictionaries are usually portable; re-run `checkMesh`.
`gmshToFoam` exists in both trees but expects **ASCII MSH 2.x**:
`gmsh -3 -format msh2 -o mesh.msh model.geo`. MSH 4.x block format is not handled by this reader
**[uncertain for 2024-1; verify with a small mesh]**.
## 6. Stopping a running solver
**Graceful:** add this to `system/controlDict` before launch, then create `<case>\stop`:

```text
functions { stop {
    type stopAtFile; libs ("libutilityFunctionObjects.so");
    file "$FOAM_CASE/stop"; action writeNow; } }
```

`writeNow` is supported by OF 8/12; `nextWrite` waits for the next write time. The file is polled at
time-step boundaries.

**Forceful:** `taskkill /PID <bash_pid> /T /F`, or in Python
`subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], check=False)`. For a GUI, prefer a Job
Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so a GUI crash also kills the solver.
`CTRL_BREAK_EVENT` only works when the child shares a console/process group; windowless GUIs usually
cannot rely on it **[uncertain]**.

## Sources

- <https://bluecfd.github.io/Core/Downloads/> · <https://bluecfd.github.io/Core/ReleaseNotes/bluecfd-core-2024-1> · <https://bluecfd.github.io/Core/ReleaseNotes/bluecfd-core-2020-1>
- <https://github.com/blueCFD/Core/issues/257> · <https://github.com/blueCFD/Core/issues/273> · <https://github.com/blueCFD/Core/discussions/217> · <https://github.com/blueCFD/Core/wiki/Command-line-installation-options-for-blueCFD-Core-installers>
- <https://github.com/blueCFD/OpenFOAM-dev/blob/blueCFD-Core-12/etc/pre-bashrc-mingw_w64.sh> · <https://github.com/blueCFD/OpenFOAM-dev/blob/blueCFD-Core-12/etc/bashrc>
- <https://github.com/OpenFOAM/OpenFOAM-12/blob/master/applications/solvers/foamRun/foamRun.C> · <https://github.com/OpenFOAM/OpenFOAM-12/tree/master/applications/legacy/incompressible/icoFoam> · <https://github.com/OpenFOAM/OpenFOAM-12/blob/master/etc/caseDicts/functions/control/stopAtFile>
- <https://www.gnu.org/software/bash/manual/bash.html#Bash-Startup-Files> · <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill>
- <https://jrsoftware.org/ishelp/topic_setup_appid.htm> · <https://github.com/jaheyns/CfdOF/blob/master/CfdOF/CfdTools.py>
