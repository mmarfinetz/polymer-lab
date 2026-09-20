#!/bin/bash
# Predeclared four-replicate backend gate; all four must pass.
#SBATCH --job-name=fiber-pe-ref-v2
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=06:00:00
#SBATCH --array=0-3
#SBATCH --ntasks=8
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-pe-ref-v2-%A_%a.out
set -euo pipefail
BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab; ENVIRONMENT=$BASE/envs/radonpy-mpi; REFERENCE=$BASE/vendor/lammps-reference/9e42b6f0f2c68a092d5847d4127a053dc50e126a; ROOT=$BASE/runs/fiber-v1/discovery-v3/reference-validation/crystalline-pe-v2; SEEDS=(104729 130363 155921 177013); SEED=${SEEDS[$SLURM_ARRAY_TASK_ID]}; OUTPUT=$ROOT/seed-$SEED; mkdir -p "$OUTPUT"; export PATH=$ENVIRONMENT/bin:/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH; export OMP_NUM_THREADS=1
$ENVIRONMENT/bin/python $BASE/app/scripts/run_pe_crystal_reference.py --lammps $ENVIRONMENT/bin/lmp --mpiexec $ENVIRONMENT/bin/mpiexec --mpi-ranks $SLURM_NTASKS --potential $REFERENCE/CH.airebo-m --output "$OUTPUT" --seed "$SEED" --protocol-version pe-airebo-m-reference-v2
