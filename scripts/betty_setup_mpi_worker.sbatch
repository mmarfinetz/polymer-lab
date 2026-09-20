#!/bin/bash
#SBATCH --job-name=polymer-mpi-env
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/setup-mpi-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
APP="$BASE/app"
SOURCE_ENV="$BASE/envs/radonpy"
TARGET_ENV="$BASE/envs/radonpy-mpi"
RADONPY_SOURCE_DIR="$BASE/RadonPy"
CONDA_BASE=/vast/parcc/spack/sw/apps/linux-sapphirerapids/anaconda3-2023.09-0-ieilyrkph5mewqcum3ajc4odlt2vakri

source "$CONDA_BASE/etc/profile.d/conda.sh"
export CONDA_PKGS_DIRS="$BASE/conda-pkgs"

if [[ ! -x "$TARGET_ENV/bin/python" ]]; then
    conda create --yes --prefix "$TARGET_ENV" --clone "$SOURCE_ENV"
fi
if ! compgen -G "$TARGET_ENV/conda-meta/lammps-*_mpi_openmpi_*.json" > /dev/null; then
    conda env update --prefix "$TARGET_ENV" --file "$APP/environments/radonpy-worker.yml" --prune
fi

"$TARGET_ENV/bin/python" -m pip install --no-index --find-links="$RADONPY_SOURCE_DIR/dist" radonpy-pypi
"$TARGET_ENV/bin/python" -m pip install --no-deps --editable "$APP"

test -x "$TARGET_ENV/bin/mpirun"
test -x "$TARGET_ENV/bin/lmp"
ls "$TARGET_ENV"/conda-meta/lammps-*_mpi_openmpi_*.json
"$TARGET_ENV/bin/mpirun" --version
ldd "$TARGET_ENV/bin/lmp" | grep -E 'libmpi|open-rte|open-pal'
"$TARGET_ENV/bin/lmp" -h > "$BASE/envs/lammps-mpi-help.txt"
head -1 "$BASE/envs/lammps-mpi-help.txt"
"$TARGET_ENV/bin/python" -c 'import psi4, rdkit, radonpy; print(psi4.__version__, rdkit.__version__)'
date -u +%FT%TZ > "$BASE/envs/radonpy-mpi.ready"
