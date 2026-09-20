#!/usr/bin/env python3
"""Create and optionally submit one immutable fiber-v1 aligned-chain job."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from polymer_lab.aligned import AlignedChainJob, AlignedChainProtocol, write_aligned_manifest
from polymer_lab.fiber import FiberV1Manifest
from polymer_lab.models import JobState, PhysicsJob, SimulationSpec
from polymer_lab.validation import RDKitPSmilesValidator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", default="uhmwpe-gel-draw-100-doe-001")
    parser.add_argument("--profile", choices=("protocol_validation", "production"), default="protocol_validation")
    parser.add_argument("--draw-ratio", type=float, default=2.0)
    parser.add_argument("--mpi-ranks", type=int, default=4)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    base = args.base.resolve()
    run_root = base / "runs" / "fiber-v1"
    campaign_path = run_root / "manifest.json"
    campaign = FiberV1Manifest.model_validate_json(campaign_path.read_text())
    matches = [candidate for candidate in campaign.candidates if candidate.name == args.candidate]
    if len(matches) != 1:
        raise RuntimeError(f"expected one fiber candidate named {args.candidate!r}; found {len(matches)}")
    candidate = matches[0]
    representations = [
        constituent.representation
        for constituent in candidate.chemistry.constituents
        if constituent.representation_type == "psmiles" and constituent.representation
    ]
    if len(representations) != 1:
        raise RuntimeError("aligned-chain v1 requires exactly one explicit PSMILES constituent")
    polymer = RDKitPSmilesValidator().validate(
        representations[0],
        generation_method="fiber-v1-reviewed-doe",
        metadata={
            "fiber_candidate_id": candidate.id,
            "fiber_design_hash": candidate.design_hash,
            "scientific_status": "candidate definition only; not a property measurement",
        },
    )

    profile_slug = (
        "production-staged-v1"
        if args.profile == "production"
        else args.profile.replace("_", "-")
    )
    job_root = run_root / "aligned" / candidate.name / f"{profile_slug}-draw-{args.draw_ratio:g}"
    manifest_path = job_root / "manifest.json"
    submission_path = job_root / "submission.json"
    if submission_path.exists():
        print(submission_path.read_text())
        return 0
    job = None
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text())
        existing = AlignedChainJob.model_validate(payload["job"])
        if payload.get("manifest_hash") != existing.manifest_hash:
            raise RuntimeError("existing aligned-chain manifest hash mismatch")
        requested_identity_matches = (
            existing.campaign_id == campaign.campaign_id
            and existing.candidate.id == candidate.id
            and existing.candidate.design_hash == candidate.design_hash
            and existing.protocol.profile == args.profile
            and existing.protocol.draw_ratio == args.draw_ratio
            and existing.protocol.mpi_ranks == args.mpi_ranks
            and existing.artifact_uri == f"file://{job_root}"
        )
        if requested_identity_matches:
            job = existing
    if job is None:
        production = args.profile == "production"
        protocol = AlignedChainProtocol(
            profile=args.profile,
            draw_ratio=args.draw_ratio,
            draw_true_strain_rate_s=1.0e9 if production else 5.0e9,
            relaxation_steps=250_000 if production else 50_000,
            tensile_true_strain_rate_s=1.0e9 if production else 5.0e9,
            tensile_max_true_strain=0.10 if production else 0.05,
            sample_every_steps=500,
            restart_every_steps=25_000,
            random_seed=11,
            mpi_ranks=args.mpi_ranks,
        )
        preparation = PhysicsJob(
            campaign_id=campaign.campaign_id,
            candidate=polymer,
            spec=SimulationSpec(
                profile="production",
                target_atoms_per_chain=1000 if production else 200,
                chain_count=10 if production else 4,
                initial_density_g_cm3=0.05,
                force_field="GAFF2_mod",
                charge_method="RESP",
                temperature_k=300,
                pressure_atm=1,
                random_seed=11,
                radonpy_version="1.0b2",
                rdkit_version="environment",
                psi4_version="environment",
                lammps_version="stable",
                extra={
                    "omp": 1,
                    "mpi": args.mpi_ranks,
                    "psi4_omp": 1,
                    "psi4_memory_mb": 5000,
                    "retry_equilibration": 0 if production else 2,
                    "no_trajectory": production,
                    "sampling_dump_frequency_steps": 10_000 if production else 1000,
                    "equilibration_strategy": (
                        "staged-radonpy-v1-single-sampling-block"
                        if production
                        else "diagnostic-radonpy-default"
                    ),
                },
            ),
            requested_properties=(),
            artifact_uri=f"file://{job_root / 'preparation'}",
            estimated_core_hours=2688 if production else 192,
            state=JobState.APPROVED,
        )
        job = AlignedChainJob(
            campaign_id=campaign.campaign_id,
            candidate=candidate,
            preparation_job=preparation,
            protocol=protocol,
            artifact_uri=f"file://{job_root}",
            estimated_core_hours=2688 if production else 192,
            approved_by="mitchmar",
            approval_rationale=(
                "User explicitly requested and approved running fiber-v1 aligned-chain compute on Betty "
                "on 2026-08-25."
            ),
        )
        write_aligned_manifest(job, manifest_path)

    output = {
        "campaign_id": campaign.campaign_id,
        "candidate_id": candidate.id,
        "candidate_name": candidate.name,
        "design_hash": candidate.design_hash,
        "job_id": job.id,
        "manifest_hash": job.manifest_hash,
        "protocol_hash": job.protocol.protocol_hash,
        "profile": job.protocol.profile,
        "draw_ratio": job.protocol.draw_ratio,
        "manifest": str(manifest_path),
        "estimated_core_hours_ceiling": job.estimated_core_hours,
        "equilibration_strategy": job.preparation_job.spec.extra.get("equilibration_strategy"),
        "scientific_status": (
            "diagnostic protocol validation; output cannot be admitted as scientific evidence"
            if job.protocol.profile == "protocol_validation"
            else "production computation pending convergence and artifact admission"
        ),
    }
    if args.submit:
        completed = subprocess.run(
            [
                "sbatch",
                f"--ntasks={job.protocol.mpi_ranks}",
                "--time=7-00:00:00" if job.protocol.profile == "production" else "--time=2-00:00:00",
                str(base / "app" / "scripts" / "betty_fiber_aligned.sbatch"),
                str(manifest_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        output["slurm_job_id"] = completed.stdout.strip().split()[-1]
        output["submitted"] = True
        campaign = campaign.model_copy(
            update={
                "state": "screening",
                "scientific_status": (
                    f"Aligned-chain {job.protocol.profile} job {job.id} submitted for {candidate.name}; "
                    "no candidate is qualified."
                ),
            }
        )
        campaign_path.write_text(campaign.model_dump_json(indent=2) + "\n")
        submission_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
