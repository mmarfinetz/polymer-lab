#!/usr/bin/env python3
"""Create, approve, and submit the first Betty production campaign batch."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from polymer_lab import CampaignConfig, PolymerLab, SimulationSpec
from polymer_lab.datasets import IngestBatch, PropertyColumn, load_experimental_csv, load_radonpy_pi1070
from polymer_lab.executors import SlurmConfig
from polymer_lab.models import PropertyName, TrainingExample
from polymer_lab.predictor import XGBoostEnsemble
from polymer_lab.public_surrogate import OPENPOLY_SOURCE, _is_holdout

SEEDS = (
    "[*]CC[*]",
    "[*]CC([*])c1ccccc1",
    "[*]COC[*]",
    "[*]CC([*])(C)C(=O)OC",
    "[*]CC(F)([*])",
    "[*]Cc1ccc(cc1)C[*]",
    "[*]COc1ccc(cc1)OC[*]",
)


def _training_split(batch: IngestBatch, *, fraction: float, seed: int) -> IngestBatch:
    candidates = {candidate.id: candidate for candidate in batch.candidates}
    observations = tuple(
        observation
        for observation in batch.observations
        if not _is_holdout(
            TrainingExample(candidate=candidates[observation.candidate_id], observation=observation),
            fraction,
            seed,
        )
    )
    selected_ids = {observation.candidate_id for observation in observations}
    return batch.model_copy(
        update={
            "candidates": tuple(candidate for candidate in batch.candidates if candidate.id in selected_ids),
            "observations": observations,
        }
    )


def _schedule_continuation(
    base: Path,
    physics_job_id: str,
    campaign_id: str,
    run_name: str,
) -> str:
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
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--run-name", default="high-tg-low-density-v1")
    args = parser.parse_args()

    base = args.base.resolve()
    app = base / "app"
    environment = base / "envs" / "radonpy-mpi"
    run_root = base / "runs" / args.run_name
    submission_path = run_root / "submission.json"
    if submission_path.exists():
        print(submission_path.read_text())
        return 0

    predictor = XGBoostEnsemble.load(app / "models" / "public-v1")
    slurm = SlurmConfig(
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
    lab = PolymerLab.scientific_slurm(run_root, predictor=predictor, slurm=slurm)
    model_metadata = predictor.model_metadata
    holdout = model_metadata.get("split", {})
    holdout_fraction = float(holdout.get("fraction", 0.2))
    split_seed = int(holdout.get("seed", 42))
    validator = lab.engine.generator.validator
    openpoly = load_experimental_csv(
        app / "data" / "raw" / "openpoly_properties.csv",
        validator,
        property_columns={
            "Tg (K)": PropertyColumn(property=PropertyName.TG, unit="degC", offset=-273.15),
        },
        dataset_name="OpenPoly",
        source_reference=OPENPOLY_SOURCE,
        license_note="OpenPoly repository: MIT License.",
    )
    radonpy = load_radonpy_pi1070(app / "data" / "raw" / "radonpy_pi1070.csv", validator)
    lab.ingest(_training_split(openpoly, fraction=holdout_fraction, seed=split_seed))
    lab.ingest(_training_split(radonpy, fraction=holdout_fraction, seed=split_seed))
    seeds = [lab.candidate(psmiles) for psmiles in SEEDS]
    config = CampaignConfig(
        name="high-tg-low-density-betty",
        population_size=len(seeds),
        offspring_size=4,
        physics_batch_size=1,
        max_generations=3,
        max_candidates=50,
        max_core_hours=8064,
        max_physics_jobs=3,
        require_physics_approval=True,
    )
    campaign = lab.create_campaign(config, seeds)
    campaign = lab.engine.start(campaign.id)
    ranked = lab.engine.ranked_population(campaign.id)
    spec = SimulationSpec(
        profile="production",
        target_atoms_per_chain=1000,
        chain_count=10,
        initial_density_g_cm3=0.05,
        tacticity="atactic",
        force_field="GAFF2_mod",
        charge_method="RESP",
        temperature_k=300,
        pressure_atm=1,
        random_seed=1,
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
    jobs = lab.engine.request_physics(
        campaign.id,
        spec=spec,
        estimated_core_hours_per_job=2688,
        count=1,
    )
    approval = lab.engine.approve(
        campaign.id,
        [job.id for job in jobs],
        approved_by="mitchmar",
        rationale="User explicitly approved the Betty production campaign on 2026-08-20.",
        approved_core_hours=2688,
    )
    submitted = lab.engine.submit_approved(campaign.id)
    predictor.save(run_root / "models" / "current")
    continuation_id = _schedule_continuation(
        base,
        str(submitted[0].external_id),
        campaign.id,
        args.run_name,
    )
    selected = ranked[0]
    payload = {
        "campaign_id": campaign.id,
        "campaign_state": lab.engine.repository.get_campaign(campaign.id).state,
        "approval_id": approval.id,
        "approved_core_hours": approval.approved_core_hours,
        "model_version": predictor.version,
        "prediction_status": predictor.model_metadata.get("status"),
        "held_out_metrics": predictor.model_metadata.get("held_out_metrics", {}),
        "selected_candidate": {
            "candidate_id": selected.candidate.id,
            "canonical_psmiles": selected.candidate.canonical_psmiles,
            "feasible": selected.feasible,
            "constraint_violation": selected.constraint_violation,
            "pareto_rank": selected.pareto_rank,
            "acquisition_score": selected.acquisition_score,
            "selection_status": (
                "surrogate-feasible for every threshold"
                if selected.feasible
                else "closest normalized threshold violation; not yet surrogate-feasible"
            ),
            "predictions": {
                item.property.value: {
                    "mean": item.mean,
                    "uncertainty": item.uncertainty,
                    "unit": item.unit,
                    "provenance": "model-derived surrogate estimate; not a measurement",
                }
                for item in selected.predictions
            },
        },
        "physics_jobs": [
            {
                "job_id": job.id,
                "slurm_job_id": job.external_id,
                "state": job.state,
                "manifest": str(Path(job.artifact_uri.removeprefix("file://")) / "manifest.json"),
            }
            for job in submitted
        ],
        "continuation_slurm_job_id": continuation_id,
    }
    run_root.mkdir(parents=True, exist_ok=True)
    submission_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
