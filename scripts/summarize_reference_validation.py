#!/usr/bin/env python3
"""Summarize completed PE/aPS/PMMA results against declared acceptance bands."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean, pstdev

from polymer_lab.models import PhysicsJob, PhysicsResult, PropertyName
from polymer_lab.physics import RadonPyEvaluator

REFERENCE_BANDS = {
    "polyethylene": {"density": (0.86, 0.97), "tg": (-150.0, -100.0)},
    "atactic_polystyrene": {"density": (1.04, 1.08), "tg": (95.0, 105.0)},
    "pmma": {"density": (1.17, 1.20), "tg": (100.0, 125.0)},
}


def _distance_to_range(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower - value
    if value > upper:
        return value - upper
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    grouped: dict[str, list[PhysicsResult]] = defaultdict(list)
    evaluator = RadonPyEvaluator()
    for name in REFERENCE_BANDS:
        for result_path in sorted((args.root / name).glob("seed-*/result.json")):
            manifest_path = result_path.parent / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            job = PhysicsJob.model_validate(manifest["job"])
            if manifest.get("manifest_hash") != job.manifest_hash:
                raise ValueError(f"manifest hash mismatch: {manifest_path}")
            grouped[name].append(evaluator.read_result(job, result_path))
    polymers = {}
    overall_pass = True
    for name, bands in REFERENCE_BANDS.items():
        results = grouped[name]
        values: dict[str, list[float]] = defaultdict(list)
        for result in results:
            if not result.converged:
                continue
            for observation in result.observations:
                values[observation.property.value].append(observation.value)
        density_values = values[PropertyName.DENSITY.value]
        tg_values = values[PropertyName.TG.value]
        density_midpoint = fmean(bands["density"])
        density_pass = len(density_values) == 3 and all(
            abs(value - density_midpoint) / density_midpoint <= 0.05 for value in density_values
        )
        tg_pass = len(tg_values) == 3 and all(_distance_to_range(value, *bands["tg"]) <= 50.0 for value in tg_values)
        passed = density_pass and tg_pass
        overall_pass &= passed
        polymers[name] = {
            "replicates": len(results),
            "density": {
                "values_g_cm3": density_values,
                "mean_g_cm3": fmean(density_values) if density_values else None,
                "stdev_g_cm3": pstdev(density_values) if len(density_values) > 1 else None,
                "reference_range_g_cm3": bands["density"],
                "pass": density_pass,
            },
            "tg": {
                "values_degC": tg_values,
                "mean_degC": fmean(tg_values) if tg_values else None,
                "stdev_degC": pstdev(tg_values) if len(tg_values) > 1 else None,
                "reference_range_degC": bands["tg"],
                "pass": tg_pass,
            },
            "pass": passed,
        }
    report = {
        "pass": overall_pass,
        "criteria": {
            "replicates_per_polymer": 3,
            "density": "every replicate within 5% of reference-range midpoint",
            "tg": "every replicate within 50 degC of the reference range",
        },
        "reference_warning": "Review and cite the experimental reference ranges before publication.",
        "polymers": polymers,
    }
    destination = args.output or (args.root / "validation_report.json")
    destination.write_text(json.dumps(report, indent=2))
    print(destination)
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
