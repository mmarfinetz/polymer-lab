#!/bin/bash
#SBATCH --job-name=fiber-pe-ref-gate
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-pe-reference-gate-%j.out

set -euo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
ROOT="$BASE/runs/fiber-v1/discovery-v2/reference-validation/crystalline-pe-v1"

export PATH="$ENVIRONMENT/bin:/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH"
"$ENVIRONMENT/bin/python" "$BASE/app/scripts/summarize_pe_crystal_reference.py" --root "$ROOT"
