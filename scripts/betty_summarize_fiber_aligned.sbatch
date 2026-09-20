#!/bin/bash
#SBATCH --job-name=fiber-v1-gate
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:10:00
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2048M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/fiber-gate-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENVIRONMENT="$BASE/envs/radonpy-mpi"
export PYTHONPATH="$BASE/app/src${PYTHONPATH:+:$PYTHONPATH}"

"$ENVIRONMENT/bin/python" "$BASE/app/scripts/summarize_fiber_aligned.py" --manifest "$1"
