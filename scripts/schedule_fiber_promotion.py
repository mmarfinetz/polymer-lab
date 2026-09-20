#!/usr/bin/env python3
"""Schedule production promotion only after a successful diagnostic gate."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--gate-job-id", required=True)
    args = parser.parse_args()
    destination = args.pilot_root / "promotion-submission.json"
    if destination.exists():
        print(destination.read_text())
        return 0
    completed = subprocess.run(
        [
            "sbatch",
            f"--dependency=afterok:{args.gate_job_id}",
            str(args.base / "app" / "scripts" / "betty_promote_fiber_production.sbatch"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = {
        "schema_version": 1,
        "gate_slurm_job_id": args.gate_job_id,
        "promotion_slurm_job_id": completed.stdout.strip().split()[-1],
        "dependency": "afterok",
        "production_scope": {
            "candidate": "uhmwpe-gel-draw-100-doe-001",
            "profile": "production",
            "draw_ratio": 2,
            "mpi_ranks": 16,
        },
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
