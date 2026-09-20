#!/bin/bash
#SBATCH --job-name=polymer-queue
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/queue-%j.out

set -uo pipefail
set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
export PATH=/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH
export SLURM_CONF=/cm/shared/apps/slurm/etc/slurm/slurm.conf
"$BASE/envs/radonpy/bin/python" "$BASE/app/scripts/queue_betty_campaign.py" --base "$BASE" "$@"
