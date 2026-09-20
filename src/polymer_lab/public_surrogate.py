"""Train a provenance-scoped public Tg/density surrogate with held-out metrics."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from .datasets import (
    PropertyColumn,
    load_experimental_csv,
    load_radonpy_pi1070,
)
from .models import (
    PropertyName,
    Provenance,
    TrainingExample,
    stable_hash,
)
from .predictor import XGBoostEnsemble
from .validation import RDKitPSmilesValidator

OPENPOLY_SOURCE = (
    "https://github.com/WangGroupFDU/Openpoly_benchmark/blob/main/data/final_polymer_properties_fromliterature.csv"
)
RADONPY_SOURCE = "https://github.com/RadonPy/RadonPy/blob/develop/data/PI1070.csv"


def _is_holdout(example: TrainingExample, fraction: float, seed: int) -> bool:
    digest = stable_hash(
        {
            "structure_hash": example.candidate.structure_hash,
            "property": example.observation.property.value,
            "seed": seed,
        }
    )
    return int(digest[:8], 16) / 0xFFFFFFFF < fraction


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float | int]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("held-out metric vectors are empty or inconsistent")
    errors = [estimate - target for target, estimate in zip(actual, predicted, strict=True)]
    mean_actual = sum(actual) / len(actual)
    ss_res = sum(error**2 for error in errors)
    ss_total = sum((value - mean_actual) ** 2 for value in actual)
    return {
        "count": len(actual),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(ss_res / len(errors)),
        "r2": 1.0 - ss_res / ss_total if ss_total else 0.0,
    }


def train_public_surrogate(
    *,
    openpoly_csv: str | Path,
    radonpy_csv: str | Path,
    model_dir: str | Path,
    ensemble_size: int = 5,
    random_seed: int = 42,
    holdout_fraction: float = 0.2,
) -> dict[str, object]:
    if not 0.05 <= holdout_fraction <= 0.4:
        raise ValueError("holdout_fraction must be between 0.05 and 0.4")
    validator = RDKitPSmilesValidator()
    openpoly = load_experimental_csv(
        openpoly_csv,
        validator,
        property_columns={
            "Tg (K)": PropertyColumn(
                property=PropertyName.TG,
                unit="degC",
                offset=-273.15,
            )
        },
        dataset_name="OpenPoly",
        source_reference=OPENPOLY_SOURCE,
        license_note="OpenPoly repository: MIT License.",
    )
    radonpy = load_radonpy_pi1070(radonpy_csv, validator)
    candidate_by_id = {candidate.id: candidate for candidate in (*openpoly.candidates, *radonpy.candidates)}
    examples = [
        TrainingExample(
            candidate=candidate_by_id[observation.candidate_id],
            observation=observation,
        )
        for observation in (*openpoly.observations, *radonpy.observations)
    ]
    training = [example for example in examples if not _is_holdout(example, holdout_fraction, random_seed)]
    holdout = [example for example in examples if _is_holdout(example, holdout_fraction, random_seed)]
    train_counts = Counter(example.observation.property.value for example in training)
    holdout_counts = Counter(example.observation.property.value for example in holdout)
    required = {PropertyName.TG.value, PropertyName.DENSITY.value}
    if any(train_counts[name] < 8 or holdout_counts[name] < 2 for name in required):
        raise ValueError(f"public data split is too small: train={dict(train_counts)}, holdout={dict(holdout_counts)}")

    predictor = XGBoostEnsemble(
        training_domains={
            PropertyName.TG: {Provenance.EXPERIMENTAL},
            PropertyName.DENSITY: {Provenance.MD},
        },
        ensemble_size=ensemble_size,
        random_seed=random_seed,
    )
    predictor.fit(training)
    holdout_candidates = {example.candidate.id: example.candidate for example in holdout}
    predicted = predictor.predict(list(holdout_candidates.values()))
    prediction_map = {(prediction.candidate_id, prediction.property): prediction.mean for prediction in predicted}
    metrics: dict[str, dict[str, float | int]] = {}
    for property_name in (PropertyName.TG, PropertyName.DENSITY):
        rows = [example for example in holdout if example.observation.property == property_name]
        metrics[property_name.value] = _metrics(
            [example.observation.value for example in rows],
            [prediction_map[(example.candidate.id, property_name)] for example in rows],
        )

    model_card: dict[str, object] = {
        "schema_version": 1,
        "model_version": predictor.version,
        "status": "model-derived surrogate estimates; not direct measurements",
        "training_domains": {
            "tg": "OpenPoly experimental literature values",
            "density": "RadonPy PI1070 molecular-dynamics values",
        },
        "sources": {
            "openpoly": {
                "url": OPENPOLY_SOURCE,
                "sha256": openpoly.report.source_checksum,
                "license": openpoly.report.license_note,
            },
            "radonpy_pi1070": {
                "url": RADONPY_SOURCE,
                "sha256": radonpy.report.source_checksum,
                "license": radonpy.report.license_note,
            },
        },
        "rows": {
            "training": dict(train_counts),
            "holdout": dict(holdout_counts),
            "rejected": {
                "openpoly": len(openpoly.report.rejected),
                "radonpy_pi1070": len(radonpy.report.rejected),
            },
        },
        "split": {
            "method": "structure-hash holdout by property",
            "fraction": holdout_fraction,
            "seed": random_seed,
        },
        "held_out_metrics": metrics,
    }
    predictor.model_metadata = model_card
    destination = Path(model_dir).resolve()
    predictor.save(destination)
    (destination / "model_card.json").write_text(json.dumps(model_card, indent=2, sort_keys=True))
    return model_card
