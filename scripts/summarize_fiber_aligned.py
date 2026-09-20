#!/usr/bin/env python3
"""Verify one aligned-chain result and write a non-scientific diagnostic gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymer_lab.aligned import AlignedChainJob, read_aligned_diagnostic_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest_payload = json.loads(args.manifest.read_text())
    job = AlignedChainJob.model_validate(manifest_payload["job"])
    if manifest_payload.get("manifest_hash") != job.manifest_hash:
        raise RuntimeError("aligned-chain manifest hash mismatch")
    job_root = args.manifest.parent
    gate_path = job_root / "diagnostic-gate.json"
    failure_path = job_root / "failure.json"
    payload: dict[str, object] = {
        "schema_version": 1,
        "job_id": job.id,
        "campaign_id": job.campaign_id,
        "candidate_id": job.candidate.id,
        "design_hash": job.candidate.design_hash,
        "protocol_hash": job.protocol.protocol_hash,
        "profile": job.protocol.profile,
        "admissible_as_scientific_evidence": False,
        "measurements_admitted": 0,
    }
    try:
        if failure_path.exists():
            failure = json.loads(failure_path.read_text())
            raise RuntimeError(f"worker failure: {failure.get('message', 'unknown error')}")
        result = read_aligned_diagnostic_result(job, job_root / "result.json")
        payload.update(
            {
                "passed": result.converged,
                "converged": result.converged,
                "metrics": result.metrics.model_dump(mode="json"),
                "warnings": list(result.warnings),
                "verified_artifact_count": len(result.artifact_checksums),
                "software_versions": result.software_versions,
                "next_action": (
                    "review and authorize a production protocol matrix"
                    if result.converged
                    else "repair the failed convergence gate before production"
                ),
            }
        )
    except Exception as exc:
        payload.update(
            {
                "passed": False,
                "converged": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "next_action": "repair the worker/protocol before production",
            }
        )
    gate_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
