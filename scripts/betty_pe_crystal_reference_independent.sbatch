#!/bin/bash
#SBATCH --job-name=fiber-pe-ref-independent
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=06:00:00
#SBATCH --ntasks=8
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-pe-reference-independent-%j.out

set -euo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
REFERENCE="$BASE/vendor/lammps-reference/9e42b6f0f2c68a092d5847d4127a053dc50e126a"
ROOT="$BASE/runs/fiber-v1/discovery-v2/reference-validation/crystalline-pe-v1-independent-seed-177013"

export PATH="$ENVIRONMENT/bin:/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH"
export OMP_NUM_THREADS=1

"$ENVIRONMENT/bin/python" "$BASE/app/scripts/run_pe_crystal_reference.py" \
  --lammps "$ENVIRONMENT/bin/lmp" \
  --mpiexec "$ENVIRONMENT/bin/mpiexec" \
  --mpi-ranks "$SLURM_NTASKS" \
  --potential "$REFERENCE/CH.airebo-m" \
  --output "$ROOT" \
  --seed 177013
