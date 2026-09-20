#!/usr/bin/env python3
"""Prepare three-reference, three-seed RadonPy manifests for scientific validation."""

from __future__ import annotations

import argparse
import csv
import uuid
from pathlib import Path

from polymer_lab.models import PhysicsJob, SimulationSpec
from polymer_lab.physics import RadonPyEvaluator
from polymer_lab.validation import RDKitPSmilesValidator

REFERENCES = {
    "polyethylene": {
        "psmiles": "[*]CC[*]",
        "density_range": "0.86-0.97 g/cm^3",
        "tg_range": "-150--100 degC",
    },
    "atactic_polystyrene": {
        "psmiles": "[*]CC([*])c1ccccc1",
        "density_range": "1.04-1.08 g/cm^3",
        "tg_range": "95-105 degC",
    },
    "pmma": {
        "psmiles": "[*]CC([*])(C)C(=O)OC",
        "density_range": "1.17-1.20 g/cm^3",
        "tg_range": "100-125 degC",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--estimated-core-hours", type=float, default=250.0)
    args = parser.parse_args()
    validator = RDKitPSmilesValidator()
    evaluator = RadonPyEvaluator()
    campaign_id = str(uuid.uuid4())
    index_rows = []
    for name, reference in REFERENCES.items():
        candidate = validator.validate(
            reference["psmiles"],
            generation_method="validation-reference",
            metadata={"reference_name": name},
        )
        for seed in (1, 2, 3):
            spec = SimulationSpec(random_seed=seed)
            job_dir = (args.output / name / f"seed-{seed}").resolve()
            job = PhysicsJob(
                campaign_id=campaign_id,
                candidate=candidate,
                spec=spec,
                artifact_uri=job_dir.as_uri(),
                estimated_core_hours=args.estimated_core_hours,
            )
            manifest = evaluator.write_manifest(job, job_dir / "manifest.json")
            index_rows.append(
                {
                    "polymer": name,
                    "seed": seed,
                    "job_id": job.id,
                    "manifest": str(manifest),
                    "density_reference": reference["density_range"],
                    "tg_reference": reference["tg_range"],
                }
            )
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "validation_jobs.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=index_rows[0].keys())
        writer.writeheader()
        writer.writerows(index_rows)
    print(args.output / "validation_jobs.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
