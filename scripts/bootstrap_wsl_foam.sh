#!/usr/bin/env bash
set -euo pipefail

# Development-only bootstrap: installs a self-contained OpenFOAM 2412
# environment inside WSL without root privileges, using micromamba.
# BlueCFD-Core remains the primary runtime for the Windows app.

cd "$HOME/bin"
if [ ! -f micromamba.tar.bz2 ]; then
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest -o micromamba.tar.bz2
fi
python3 - <<'PY'
import tarfile
tarfile.open("micromamba.tar.bz2", "r:bz2").extractall(".")
PY
MM="$HOME/bin/bin/micromamba"
chmod +x "$MM"
"$MM" --version

if [ ! -x "$HOME/foamenv/bin/simpleFoam" ]; then
  "$MM" create -y -p "$HOME/foamenv" -c conda-forge openfoam=2412
fi

"$MM" run -p "$HOME/foamenv" bash -lc 'command -v simpleFoam; command -v icoFoam; command -v gmshToFoam; command -v checkMesh; echo FOAM_VERSION=$WM_PROJECT_VERSION'
