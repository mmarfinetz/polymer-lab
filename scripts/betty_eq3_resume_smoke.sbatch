#!/bin/bash
#SBATCH --job-name=polymer-eq3-resume-smoke
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:15:00
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/eq3-resume-smoke-%j.out

set -euo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENV_PREFIX="$BASE/envs/radonpy-mpi"
SOURCE_JOB=${1:?Pass the RadonPy simulation directory as argument 1}
SMOKE_ROOT="$BASE/benchmarks/eq3-resume-$SLURM_JOB_ID"

test -f "$BASE/envs/radonpy-mpi.ready"
test -f "$SOURCE_JOB/eq3.in"
mkdir -p "$SMOKE_ROOT"

copied=false
for attempt in 1 2 3 4 5; do
    source_restart=$(ls -t "$SOURCE_JOB"/radon_md_*.rst | head -1)
    cp "$source_restart" "$SMOKE_ROOT/restart.rst.tmp"
    if cmp -s "$source_restart" "$SMOKE_ROOT/restart.rst.tmp"; then
        mv "$SMOKE_ROOT/restart.rst.tmp" "$SMOKE_ROOT/restart.rst"
        copied=true
        break
    fi
done
test "$copied" = true
cp "$SOURCE_JOB/eq3.in" "$SMOKE_ROOT/eq3.in"
sha256sum "$SMOKE_ROOT/restart.rst" > "$SMOKE_ROOT/restart.sha256"

export PATH="$ENV_PREFIX/bin:$PATH"
export LAMMPS_EXEC="$ENV_PREFIX/bin/lmp"

"$ENV_PREFIX/bin/python" - "$SMOKE_ROOT" <<'PY'
import json
import pathlib
import sys

from polymer_lab.radonpy_resume import _restart_step, build_lammps_resume_input

root = pathlib.Path(sys.argv[1])
restart_step = _restart_step(str(root.parent.parent / "envs" / "radonpy-mpi" / "bin" / "lmp"), root / "restart.rst", root)
resumed, total_steps = build_lammps_resume_input(
    (root / "eq3.in").read_text(),
    restart_file="restart.rst",
    restart_step=restart_step,
    log_file="eq3-smoke.log",
    max_resume_steps=2000,
)
remaining = total_steps - restart_step
(root / "eq3_resume_smoke.in").write_text(resumed)
(root / "plan.json").write_text(
    json.dumps(
        {
            "restart_step": restart_step,
            "total_steps": total_steps,
            "production_remaining_steps": remaining,
            "smoke_steps": 2000,
            "requested_mpi": 16,
        },
        indent=2,
    )
    + "\n"
)
PY

cd "$SMOKE_ROOT"
"$ENV_PREFIX/bin/mpirun" -n 16 "$ENV_PREFIX/bin/lmp" \
    -in eq3_resume_smoke.in -log log.lammps > screen.out 2>&1
grep -q "16 MPI tasks" screen.out
test -s eq3_last.dump
test -s eq3_last.data
date -u +%FT%TZ > completed
