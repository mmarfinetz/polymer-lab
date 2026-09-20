#!/usr/bin/env python3
"""Admit one Betty physics batch and continue the approved closed loop."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from polymer_lab import PolymerLab, SimulationSpec
from polymer_lab.executors import SlurmConfig
from polymer_lab.models import CampaignState, JobState
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
        environment_setup=(
            "export PATH=/cm/local/apps/slurm/current/bin:/vast/parcc/sw/bin:$PATH; "
            "export SLURM_CONF=/cm/shared/apps/slurm/etc/slurm/slurm.conf; "
            f"export LAMMPS_EXEC={environment / 'bin' / 'lmp'}; "
            f"export RADONPY_AUTOMD_DIR={base / 'RadonPy' / 'AutoMD_scripts'}"
        ),
    )


def _spec(generation: int) -> SimulationSpec:
    return SimulationSpec(
        profile="production",
        target_atoms_per_chain=1000,
        chain_count=10,
        initial_density_g_cm3=0.05,
        tacticity="atactic",
        force_field="GAFF2_mod",
        charge_method="RESP",
        temperature_k=300,
        pressure_atm=1,
        random_seed=generation + 1,
        radonpy_version="1.0b2",
        rdkit_version="environment",
        psi4_version="environment",
        lammps_version="stable",
        extra={
            "omp": 1,
            "mpi": 16,
            "psi4_omp": 4,
            "psi4_memory_mb": 8000,
            "retry_equilibration": 2,
            "no_trajectory": False,
        },
    )


def _schedule(base: Path, physics_job_id: str, campaign_id: str, run_name: str) -> str:
    completed = subprocess.run(
        [
            "sbatch",
            f"--dependency=afterany:{physics_job_id}",
            str(base / "app" / "scripts" / "betty_continue_campaign.sbatch"),
            campaign_id,
            "--run-name",
            run_name,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip().split()[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_id")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--run-name", default="high-tg-low-density-v1")
    args = parser.parse_args()

    base = args.base.resolve()
    run_root = base / "runs" / args.run_name
    predictor = XGBoostEnsemble.load(run_root / "models" / "current")
    lab = PolymerLab.scientific_slurm(run_root, predictor=predictor, slurm=_slurm(base, run_root))
    lab.engine.poll(args.campaign_id)
    jobs = lab.engine.repository.jobs_for_campaign(args.campaign_id)
    failed = [
        job
        for job in jobs
        if job.state in {JobState.FAILED, JobState.CANCELLED}
        and not any(
            event["kind"] == "physics.admitted" and event["payload"].get("job_id") == job.id
            for event in lab.engine.repository.events_for_campaign(args.campaign_id)
        )
    ]
    if failed:
        payload = {
            "campaign_id": args.campaign_id,
            "status": "stopped_on_failed_physics",
            "failed_jobs": [
                {"job_id": job.id, "slurm_job_id": job.external_id, "state": job.state} for job in failed
            ],
        }
        destination = run_root / "loop_failure.json"
        destination.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        print(json.dumps(payload, indent=2, default=str))
        return 2

    admitted = lab.engine.ingest_completed(args.campaign_id)
    if not admitted:
        raise RuntimeError("physics dependency finished without an admissible converged result")
    campaign = lab.engine.retrain_and_advance(args.campaign_id)
    predictor.save(run_root / "models" / "current")
    if campaign.state == CampaignState.COMPLETED:
        payload = {
            "campaign_id": campaign.id,
            "status": "completed",
            "generation": campaign.generation,
            "model_version": predictor.version,
            "admitted_job_ids": admitted,
        }
        destination = run_root / "loop_complete.json"
        destination.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        print(json.dumps(payload, indent=2, default=str))
        return 0

    requested = lab.engine.request_physics(
        campaign.id,
        spec=_spec(campaign.generation),
        estimated_core_hours_per_job=2688,
        count=1,
    )
    approval = lab.engine.approve(
        campaign.id,
        [job.id for job in requested],
        approved_by="mitchmar",
        rationale="Continuation within the user-approved Betty campaign budget from 2026-08-20.",
        approved_core_hours=2688,
    )
    submitted = lab.engine.submit_approved(campaign.id)
    continuation_id = _schedule(
        base,
        str(submitted[0].external_id),
        campaign.id,
        args.run_name,
    )
    payload = {
        "campaign_id": campaign.id,
        "status": "next_generation_submitted",
        "generation": campaign.generation,
        "model_version": predictor.version,
        "admitted_job_ids": admitted,
        "approval_id": approval.id,
        "physics_job_id": submitted[0].id,
        "physics_slurm_job_id": submitted[0].external_id,
        "continuation_slurm_job_id": continuation_id,
    }
    destination = run_root / f"generation-{campaign.generation}-submission.json"
    destination.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
