#!/bin/bash
#SBATCH --job-name=fiber-pe-smoke
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-pe-smoke-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
REFERENCE="$BASE/vendor/lammps-reference/9e42b6f0f2c68a092d5847d4127a053dc50e126a"
OUTPUT="$BASE/runs/fiber-v1/discovery-v2/backend-validation/airebo-m-smoke-$SLURM_JOB_ID"

export PATH="$ENVIRONMENT/bin:/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH"
export OMP_NUM_THREADS=1

"$ENVIRONMENT/bin/python" "$BASE/app/scripts/run_pe_airebo_m_smoke.py" \
  --lammps "$ENVIRONMENT/bin/lmp" \
  --input "$BASE/app/scripts/lammps_pe_airebo_m_smoke.in" \
  --data "$REFERENCE/data.airebo" \
  --potential "$REFERENCE/CH.airebo-m" \
  --output "$OUTPUT"
