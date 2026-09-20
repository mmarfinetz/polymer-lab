#!/bin/bash
#SBATCH --job-name=polymer-continue
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/continue-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
export PATH=/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH
export SLURM_CONF=/cm/shared/apps/slurm/etc/slurm/slurm.conf
CAMPAIGN_ID=$1
shift
"$BASE/envs/radonpy/bin/python" "$BASE/app/scripts/continue_betty_campaign.py" "$CAMPAIGN_ID" --base "$BASE" "$@"
