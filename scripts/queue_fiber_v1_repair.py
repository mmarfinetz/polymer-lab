#!/usr/bin/env python3
"""Audit an eq5 pilot preparation and submit a diagnostic-only aligned-chain repair."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from polymer_lab.aligned import (
    AlignedChainJob,
    AlignedChainProtocol,
    AlignedPreparationCriteria,
    analyze_aligned_preparation,
    file_sha256,
    final_equilibration_files,
    write_aligned_manifest,
)
from polymer_lab.models import JobState, PhysicsJob


def _submit(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip().split()[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--source-pilot-root", type=Path, required=True)
    parser.add_argument("--repair-name", default="protocol-validation-stationarity-repair-v2-draw-2")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    base = args.base.resolve()
    source_root = args.source_pilot_root.resolve()
    source_manifest = source_root / "manifest.json"
    source_payload = json.loads(source_manifest.read_text())
    source_job = AlignedChainJob.model_validate(source_payload["job"])
    if source_payload.get("manifest_hash") != source_job.manifest_hash:
        raise RuntimeError("source aligned-chain manifest hash mismatch")
    if source_job.protocol.profile != "protocol_validation":
        raise RuntimeError("repair source must be a protocol-validation job")

    source_run = source_root / "preparation" / source_job.preparation_job.id
    stage, data, source_input, log, rg = final_equilibration_files(source_run)
    criteria = AlignedPreparationCriteria()
    report = analyze_aligned_preparation(
        stage=stage,
        log_path=log,
        rg_path=rg,
        temperature_k=source_job.protocol.temperature_k,
        pressure_atm=source_job.protocol.transverse_pressure_atm,
        criteria=criteria,
    )
    if not report.passed:
        raise RuntimeError(f"source preparation failed stationarity audit: {report.failed_checks}")

    checksums = {
        "data": file_sha256(data),
        "source_input": file_sha256(source_input),
        "log": file_sha256(log),
        "rg": file_sha256(rg),
    }
    immutable_source = {
        "source_manifest_path": str(source_manifest),
        "source_aligned_manifest_hash": source_job.manifest_hash,
        "source_run_dir": str(source_run),
        "equilibration_stage": stage,
        "checksums": checksums,
        "criteria": criteria.model_dump(mode="json"),
        "criteria_hash": criteria.criteria_hash,
        "stationarity_report": report.model_dump(mode="json"),
        "scientific_status": (
            "diagnostic starting-cell audit only; not RadonPy full convergence and not a measurement"
        ),
    }
    repaired_protocol = AlignedChainProtocol.model_validate(
        {
            **source_job.protocol.model_dump(mode="json"),
            "version": "aligned-chain-v2",
            "sample_every_steps": 100,
            "minimum_modulus_fit_r2": 0.0,
            "maximum_mean_transverse_pressure_deviation_atm": 1000.0,
            "minimum_tensile_samples": 100,
        }
    )

    job_root = (
        base
        / "runs"
        / "fiber-v1"
        / "aligned"
        / source_job.candidate.name
        / args.repair_name
    )
    manifest_path = job_root / "manifest.json"
    submission_path = job_root / "submission.json"
    if submission_path.exists():
        print(submission_path.read_text())
        return 0

    if manifest_path.exists():
        repaired_payload = json.loads(manifest_path.read_text())
        repaired_job = AlignedChainJob.model_validate(repaired_payload["job"])
        if repaired_payload.get("manifest_hash") != repaired_job.manifest_hash:
            raise RuntimeError("existing repaired manifest hash mismatch")
        reused_source = repaired_job.preparation_job.spec.extra.get("aligned_preparation_source")
        if (
            repaired_job.campaign_id != source_job.campaign_id
            or repaired_job.candidate.design_hash != source_job.candidate.design_hash
            or repaired_job.protocol.protocol_hash != repaired_protocol.protocol_hash
            or repaired_job.artifact_uri != f"file://{job_root}"
            or not isinstance(reused_source, dict)
            or reused_source.get("source_aligned_manifest_hash") != source_job.manifest_hash
            or reused_source.get("checksums") != checksums
            or reused_source.get("criteria_hash") != criteria.criteria_hash
        ):
            raise RuntimeError("existing repaired manifest does not match the requested immutable repair")
    else:
        preparation = PhysicsJob(
            campaign_id=source_job.campaign_id,
            candidate=source_job.preparation_job.candidate,
            spec=source_job.preparation_job.spec.model_copy(
                update={
                    "extra": {
                        **source_job.preparation_job.spec.extra,
                        "aligned_preparation_source": immutable_source,
                    }
                }
            ),
            requested_properties=(),
            artifact_uri=f"file://{job_root / 'preparation'}",
            estimated_core_hours=16,
            state=JobState.APPROVED,
        )
        repaired_job = AlignedChainJob(
            campaign_id=source_job.campaign_id,
            candidate=source_job.candidate,
            preparation_job=preparation,
            protocol=repaired_protocol,
            artifact_uri=f"file://{job_root}",
            estimated_core_hours=16,
            approved_by="mitchmar",
            approval_rationale=(
                "User requested repair of the equilibration strategy before rerunning on 2026-08-26. "
                "This diagnostic rerun reuses checksummed eq5 artifacts and cannot emit scientific measurements."
            ),
        )
        write_aligned_manifest(repaired_job, manifest_path)

    output: dict[str, object] = {
        "schema_version": 1,
        "campaign_id": repaired_job.campaign_id,
        "candidate_id": repaired_job.candidate.id,
        "job_id": repaired_job.id,
        "manifest": str(manifest_path),
        "manifest_hash": repaired_job.manifest_hash,
        "protocol_hash": repaired_job.protocol.protocol_hash,
        "protocol_version": repaired_job.protocol.version,
        "source_manifest_hash": source_job.manifest_hash,
        "source_equilibration_stage": stage,
        "source_checksums": checksums,
        "stationarity_report": report.model_dump(mode="json"),
        "admissible_as_scientific_evidence": False,
        "measurements_admitted": 0,
    }
    if args.submit:
        worker_id = _submit(
            [
                "sbatch",
                f"--ntasks={repaired_job.protocol.mpi_ranks}",
                "--time=02:00:00",
                str(base / "app" / "scripts" / "betty_fiber_aligned.sbatch"),
                str(manifest_path),
            ]
        )
        gate_id = _submit(
            [
                "sbatch",
                f"--dependency=afterany:{worker_id}",
                str(base / "app" / "scripts" / "betty_summarize_fiber_aligned.sbatch"),
                str(manifest_path),
            ]
        )
        promotion_id = _submit(
            [
                "sbatch",
                f"--dependency=afterok:{gate_id}",
                str(base / "app" / "scripts" / "betty_promote_fiber_production.sbatch"),
            ]
        )
        output.update(
            {
                "submitted": True,
                "worker_slurm_job_id": worker_id,
                "gate_slurm_job_id": gate_id,
                "promotion_slurm_job_id": promotion_id,
            }
        )
        job_root.mkdir(parents=True, exist_ok=True)
        (job_root / "gate-submission.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "worker_slurm_job_id": worker_id,
                    "gate_slurm_job_id": gate_id,
                    "dependency": "afterany",
                    "manifest": str(manifest_path),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        (job_root / "promotion-submission.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gate_slurm_job_id": gate_id,
                    "promotion_slurm_job_id": promotion_id,
                    "dependency": "afterok",
                    "production_scope": {
                        "candidate": repaired_job.candidate.name,
                        "profile": "production",
                        "draw_ratio": repaired_job.protocol.draw_ratio,
                        "mpi_ranks": 16,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        submission_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
