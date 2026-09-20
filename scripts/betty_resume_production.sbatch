#!/bin/bash
#SBATCH --job-name=polymer-resume
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=7-00:00:00
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/resume-production-%j.out

set -euo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENV_PREFIX="$BASE/envs/radonpy-mpi"
MANIFEST=${1:?Pass the immutable physics manifest as argument 1}

test -f "$BASE/envs/radonpy-mpi.ready"
test -f "$MANIFEST"
export PATH="/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$ENV_PREFIX/bin:$PATH"
export SLURM_CONF=/cm/shared/apps/slurm/etc/slurm/slurm.conf
export LAMMPS_EXEC="$ENV_PREFIX/bin/lmp"
export RADONPY_AUTOMD_DIR="$BASE/RadonPy/AutoMD_scripts"

"$ENV_PREFIX/bin/python" -m polymer_lab.worker --manifest "$MANIFEST"
