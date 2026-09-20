#!/bin/bash
#SBATCH --job-name=polymer-mpi-bench
#SBATCH --account=jcombar1-betty-testing
#SBATCH --partition=genoa-std-mem
#SBATCH --qos=normal
#SBATCH --time=00:30:00
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5632M
#SBATCH --output=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab/mpi-benchmark-%j.out

set -euxo pipefail

BASE=/vast/projects/jcombar1/betty-testing/mitchmar/polymer-lab
ENV_PREFIX="$BASE/envs/radonpy-mpi"
SOURCE_JOB="$BASE/runs/high-tg-low-density-v1/jobs/b6231457-8940-4850-965f-2eacf2988eb7/37d26efe-0d7e-4d2c-9fa5-306946b9c67c/477fe6027bb9/radonpy/da6c2d1f-8fa6-4b3b-bd84-bd2cf87f7132"
BENCH_ROOT="$BASE/benchmarks/mpi-$SLURM_JOB_ID"

test -f "$BASE/envs/radonpy-mpi.ready"
mkdir -p "$BENCH_ROOT"

# The production job alternates two restart filenames. Copy a stable newest
# snapshot without interrupting it; retry if a write races the copy.
copied=false
for attempt in 1 2 3 4 5; do
    source_restart=$(ls -t "$SOURCE_JOB"/radon_md_*.rst | head -1)
    cp "$source_restart" "$BENCH_ROOT/restart.rst.tmp"
    if cmp -s "$source_restart" "$BENCH_ROOT/restart.rst.tmp"; then
        mv "$BENCH_ROOT/restart.rst.tmp" "$BENCH_ROOT/restart.rst"
        copied=true
        break
    fi
done
test "$copied" = true
sha256sum "$BENCH_ROOT/restart.rst" > "$BENCH_ROOT/restart.sha256"

for ranks in 1 2 4 8 16; do
    rank_dir="$BENCH_ROOT/ranks-$ranks"
    mkdir -p "$rank_dir"
    cp "$BENCH_ROOT/restart.rst" "$rank_dir/restart.rst"
    cp "$BASE/app/scripts/lammps_mpi_benchmark.in" "$rank_dir/benchmark.in"
    (
        cd "$rank_dir"
        /usr/bin/time -p "$ENV_PREFIX/bin/mpirun" -n "$ranks" \
            "$ENV_PREFIX/bin/lmp" -in benchmark.in -log log.lammps \
            > screen.out 2> time.out
    )
    grep -E 'Performance:|MPI tasks x|Loop time' "$rank_dir/log.lammps" > "$rank_dir/performance.txt"
done

"$ENV_PREFIX/bin/python" -c '
import json
import pathlib
import re
root = pathlib.Path("'"$BENCH_ROOT"'")
rows = []
for path in sorted(root.glob("ranks-*/time.out")):
    ranks = int(path.parent.name.split("-")[-1])
    match = re.search(r"^real ([0-9.]+)$", path.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit(f"missing walltime: {path}")
    seconds = float(match.group(1))
    rows.append({"ranks": ranks, "wall_seconds": seconds, "core_seconds": ranks * seconds})
payload = {
    "restart_sha256": (root / "restart.sha256").read_text().split()[0],
    "runs": rows,
    "fastest_ranks": min(rows, key=lambda row: row["wall_seconds"])["ranks"],
    "most_core_efficient_ranks": min(rows, key=lambda row: row["core_seconds"])["ranks"],
}
(root / "benchmark.json").write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
'
