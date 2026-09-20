#!/usr/bin/env python3
"""Approve a prepared reference suite after an explicit compute-budget review."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from polymer_lab.models import Approval, JobState, PhysicsJob
from polymer_lab.physics import RadonPyEvaluator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--max-core-hours", type=float, required=True)
    args = parser.parse_args()
    if args.max_core_hours <= 0:
        parser.error("--max-core-hours must be positive")

    with args.index.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        parser.error("validation index contains no jobs")

    evaluator = RadonPyEvaluator()
    manifests: list[tuple[Path, PhysicsJob]] = []
    for row in rows:
        manifest_path = Path(row["manifest"]).resolve()
        payload = json.loads(manifest_path.read_text())
        job = PhysicsJob.model_validate(payload["job"])
        if payload.get("manifest_hash") != job.manifest_hash:
            raise ValueError(f"manifest hash mismatch: {manifest_path}")
        if job.state != JobState.PENDING_APPROVAL:
            raise ValueError(f"job is not pending approval: {job.id}")
        manifests.append((manifest_path, job))

    campaign_ids = {job.campaign_id for _, job in manifests}
    if len(campaign_ids) != 1:
        raise ValueError("validation jobs do not belong to one campaign")
    requested_core_hours = sum(job.estimated_core_hours for _, job in manifests)
    if requested_core_hours > args.max_core_hours:
        raise ValueError(f"suite requests {requested_core_hours} core-hours, above approval cap {args.max_core_hours}")

    approval = Approval(
        campaign_id=next(iter(campaign_ids)),
        job_ids=tuple(job.id for _, job in manifests),
        approved_core_hours=args.max_core_hours,
        approved_by=args.approved_by,
        rationale=args.rationale,
    )
    for manifest_path, job in manifests:
        evaluator.write_manifest(
            job.model_copy(update={"state": JobState.APPROVED}),
            manifest_path,
        )
    destination = args.index.parent / "validation_approval.json"
    destination.write_text(approval.model_dump_json(indent=2))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
