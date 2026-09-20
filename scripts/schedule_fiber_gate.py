#!/usr/bin/env python3
"""Schedule an idempotent post-job diagnostic gate for an aligned-chain pilot."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dependency-job-id", required=True)
    args = parser.parse_args()
    destination = args.manifest.parent / "gate-submission.json"
    if destination.exists():
        print(destination.read_text())
        return 0
    completed = subprocess.run(
        [
            "sbatch",
            f"--dependency=afterany:{args.dependency_job_id}",
            str(args.base / "app" / "scripts" / "betty_summarize_fiber_aligned.sbatch"),
            str(args.manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = {
        "schema_version": 1,
        "worker_slurm_job_id": args.dependency_job_id,
        "gate_slurm_job_id": completed.stdout.strip().split()[-1],
        "dependency": "afterany",
        "manifest": str(args.manifest),
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
