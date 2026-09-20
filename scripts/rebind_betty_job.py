#!/usr/bin/env python3
"""Rebind one checkpointed physics job to a replacement Slurm job ID."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from polymer_lab.models import JobState
from polymer_lab.repository import SQLiteRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--external-id", required=True)
    parser.add_argument("--previous-external-id", required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()

    repository = SQLiteRepository(args.database)
    try:
        job = repository.get_job(args.job_id)
        if job.campaign_id != args.campaign_id:
            raise RuntimeError("physics job does not belong to the declared campaign")
        if job.external_id != args.previous_external_id:
            raise RuntimeError(
                f"refusing stale rebind: expected {args.previous_external_id}, found {job.external_id}"
            )
        if job.state not in {JobState.SUBMITTED, JobState.RUNNING, JobState.PREEMPTED}:
            raise RuntimeError(f"physics job is not recoverable from state {job.state}")
        updated = job.model_copy(
            update={"state": JobState.SUBMITTED, "external_id": args.external_id}
        )
        repository.save_job(updated)
        repository.record_event(
            args.campaign_id,
            "physics.scheduler_rebound",
            {
                "job_id": job.id,
                "previous_external_id": args.previous_external_id,
                "external_id": args.external_id,
                "reason": "checkpoint-preserving MPI recovery",
            },
        )
        verified = repository.get_job(job.id)
    finally:
        repository.close()

    payload = {
        "campaign_id": args.campaign_id,
        "job_id": verified.id,
        "previous_external_id": args.previous_external_id,
        "external_id": verified.external_id,
        "state": verified.state,
        "rebound_at": datetime.now(UTC).isoformat(),
    }
    args.record.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
