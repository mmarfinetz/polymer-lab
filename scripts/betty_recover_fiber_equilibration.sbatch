#!/bin/bash
#SBATCH --job-name=fiber-v1-analyze
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-analysis-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
export PATH="$ENVIRONMENT/bin:/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH"
export PYTHONPATH="$BASE/app/src${PYTHONPATH:+:$PYTHONPATH}"
export LAMMPS_EXEC="$ENVIRONMENT/bin/lmp"
export RADONPY_AUTOMD_DIR="$BASE/RadonPy/AutoMD_scripts"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK"
export MKL_NUM_THREADS="$SLURM_CPUS_PER_TASK"
export OPENBLAS_NUM_THREADS="$SLURM_CPUS_PER_TASK"

"$ENVIRONMENT/bin/python" "$BASE/app/scripts/recover_fiber_equilibration.py" \
  --manifest "$1" \
  --auto-md-dir "$BASE/RadonPy/AutoMD_scripts"
