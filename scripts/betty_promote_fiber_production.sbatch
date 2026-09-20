#!/bin/bash
#SBATCH --job-name=fiber-v1-promote
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:10:00
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2048M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-promote-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
export PATH="/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH"
export SLURM_CONF=/cm/shared/apps/slurm/etc/slurm/slurm.conf
export PYTHONPATH="$BASE/app/src${PYTHONPATH:+:$PYTHONPATH}"

"$ENVIRONMENT/bin/python" "$BASE/app/scripts/queue_fiber_v1_aligned.py" \
  --base "$BASE" \
  --candidate uhmwpe-gel-draw-100-doe-001 \
  --profile production \
  --draw-ratio 2 \
  --mpi-ranks 16 \
  --submit
