from pathlib import Path

from foamstudio.runtimes import Runtime


def test_bluecfd_2024_uses_foam_run() -> None:
    runtime = Runtime(id="bluecfd", label="BlueCFD", kind="bluecfd", version="12", bash="C:/fake/bash.exe")
    assert runtime.uses_foam_run is True
    assert runtime.solver_command("simpleFoam") == ["foamRun", "-solver", "incompressibleFluid"]
    assert runtime.solver_command("icoFoam") == ["icoFoam"]
    argv = runtime.argv_for(Path("C:/Users/a/My Case"), ["checkMesh"])
    assert argv[0] == "C:/fake/bash.exe"
    assert argv[1] == "-c"
    assert "source $HOME/.bashrc" in argv[2]
    assert "cd '/c/Users/a/My Case'" in argv[2]
    assert "checkMesh" in argv[2]


def test_bluecfd_2020_uses_legacy_solver() -> None:
    runtime = Runtime(id="bluecfd", label="BlueCFD", kind="bluecfd", version="8", bash="C:/fake/bash.exe")
    assert runtime.uses_foam_run is False
    assert runtime.solver_command("simpleFoam") == ["simpleFoam"]


def test_wsl_paths_and_case_argument() -> None:
    runtime = Runtime(id="wsl", label="WSL", kind="wsl", version="v2412")
    assert runtime.wsl_path("C:/Users/a/My Case") == "/mnt/c/Users/a/My Case"
    argv = runtime.argv_for(Path("C:/Users/a/My Case"), ["icoFoam", "-case", "/mnt/c/Users/a/My Case"])
    assert argv[:4] == ["wsl.exe", "-e", "bash", "-lc"]
    assert "cd '/mnt/c/Users/a/My Case'" in argv[-1]
