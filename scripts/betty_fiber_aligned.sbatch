#!/bin/bash
#SBATCH --job-name=fiber-v1-align
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=2-00:00:00
#SBATCH --ntasks=4
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-aligned-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
export PATH="$ENVIRONMENT/bin:/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH"
export SLURM_CONF=/cm/shared/apps/slurm/etc/slurm/slurm.conf
export LAMMPS_EXEC="$ENVIRONMENT/bin/lmp"
export RADONPY_AUTOMD_DIR="$BASE/RadonPy/AutoMD_scripts"
export PYTHONPATH="$BASE/app/src${PYTHONPATH:+:$PYTHONPATH}"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

"$ENVIRONMENT/bin/python" -m polymer_lab.fiber_worker --manifest "$1"
