#!/usr/bin/env python3
"""Archive an obsolete Betty campaign while preserving all scientific artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from polymer_lab import PolymerLab
from polymer_lab.executors import SlurmConfig
from polymer_lab.predictor import XGBoostEnsemble


def _slurm(base: Path, run_root: Path) -> SlurmConfig:
    environment = base / "envs" / "radonpy-mpi"
    return SlurmConfig(
        workdir=run_root,
        partition="genoa-std-mem",
        account="jcombar1-betty-testing",
        qos="normal",
        time_limit="7-00:00:00",
        ntasks=16,
        cpus_per_task=1,
        memory_per_cpu="5632M",
        python_executable=str(environment / "bin" / "python"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_id")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--extra-slurm-job", action="append", default=[])
    parser.add_argument("--replacement-campaign", default="fiber-v1")
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--result-admission-status", default="not_admitted")
    parser.add_argument("--result-admission-reason", default="campaign objective changed")
    args = parser.parse_args()

    base = args.base.resolve()
    run_root = base / "runs" / args.run_name
    predictor = XGBoostEnsemble.load(run_root / "models" / "current")
    lab = PolymerLab.scientific_slurm(run_root, predictor=predictor, slurm=_slurm(base, run_root))

    extra_cancellations: list[dict[str, object]] = []
    for external_id in dict.fromkeys(args.extra_slurm_job):
        completed = subprocess.run(["scancel", external_id], text=True, capture_output=True)
        extra_cancellations.append(
            {
                "external_id": external_id,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )
        if completed.returncode != 0:
            raise RuntimeError(f"could not cancel dependent Slurm job {external_id}: {completed.stderr.strip()}")

    archived = lab.engine.archive(args.campaign_id, rationale=args.rationale)
    payload = {
        "campaign_id": archived.id,
        "state": archived.state,
        "classification": "platform-validation-polystyrene",
        "replacement_campaign": args.replacement_campaign,
        "eligible_for_replacement_training": False,
        "eligible_for_agent_continuation": False,
        "artifacts_preserved": True,
        "result_admission_status": args.result_admission_status,
        "result_admission_reason": args.result_admission_reason,
        "extra_scheduler_cancellations": extra_cancellations,
        "rationale": args.rationale,
        "archived_at": datetime.now(UTC).isoformat(),
    }
    lab.engine.repository.record_event(args.campaign_id, "campaign.reclassified", payload)
    marker = run_root / "ARCHIVED.json"
    marker.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
