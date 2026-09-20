#!/bin/bash
#SBATCH --job-name=polymer-env
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/setup-%j.out

set -uo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
APP="$BASE/app"
ENV_PREFIX="$BASE/envs/radonpy"
RADONPY_SOURCE_DIR="$BASE/RadonPy"
CONDA_BASE=/vast/parcc/spack/sw/apps/linux-sapphirerapids/anaconda3-2023.09-0-ieilyrkph5mewqcum3ajc4odlt2vakri

set -euxo pipefail
source "$CONDA_BASE/etc/profile.d/conda.sh"

export CONDA_PKGS_DIRS="$BASE/conda-pkgs"
mkdir -p "$CONDA_PKGS_DIRS" "$BASE/envs"

if [[ -x "$ENV_PREFIX/bin/python" ]]; then
    conda env update --yes --prefix "$ENV_PREFIX" --file "$APP/environments/radonpy-worker.yml" --prune
else
    conda env create --yes --prefix "$ENV_PREFIX" --file "$APP/environments/radonpy-worker.yml"
fi

"$ENV_PREFIX/bin/python" -m pip install --no-index --find-links="$RADONPY_SOURCE_DIR/dist" radonpy-pypi
"$ENV_PREFIX/bin/python" -m pip install --no-deps --editable "$APP"

export LAMMPS_EXEC="$ENV_PREFIX/bin/lmp"
export RADONPY_AUTOMD_DIR="$RADONPY_SOURCE_DIR/AutoMD_scripts"
"$ENV_PREFIX/bin/python" -c 'import json, psi4, rdkit, xgboost; import radonpy; print(json.dumps({"psi4": psi4.__version__, "rdkit": rdkit.__version__, "xgboost": xgboost.__version__}, sort_keys=True))'
"$LAMMPS_EXEC" -h | head -1
"$ENV_PREFIX/bin/python" -m polymer_lab.worker --help
date -u +%FT%TZ > "$BASE/envs/radonpy.ready"
