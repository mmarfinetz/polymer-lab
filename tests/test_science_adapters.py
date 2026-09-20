from __future__ import annotations

import math

import pytest

pytest.importorskip("rdkit")
pytest.importorskip("xgboost")

from polymer_lab.models import Observation, PropertyName, Provenance, TrainingExample
from polymer_lab.predictor import XGBoostEnsemble
from polymer_lab.validation import RDKitPSmilesValidator


def test_rdkit_xgboost_ensemble_fits_and_emits_uncertainty(tmp_path) -> None:
    structures = (
        "[*]CC[*]",
        "[*]CO[*]",
        "[*]CN[*]",
        "[*]CS[*]",
        "[*]CC(F)[*]",
        "[*]CC(C)[*]",
        "[*]CC(c1ccccc1)[*]",
        "[*]COc1ccccc1[*]",
        "[*]CC(=O)O[*]",
        "[*]Oc1ccc(cc1)O[*]",
    )
    validator = RDKitPSmilesValidator()
    candidates = [validator.validate(structure) for structure in structures]
    examples = []
    for index, candidate in enumerate(candidates):
        examples.extend(
            (
                TrainingExample(
                    candidate=candidate,
                    observation=Observation(
                        candidate_id=candidate.id,
                        property=PropertyName.TG,
                        value=-100 + index * 30,
                        unit="degC",
                        provenance=Provenance.EXPERIMENTAL,
                        protocol_hash="fixture",
                    ),
                ),
                TrainingExample(
                    candidate=candidate,
                    observation=Observation(
                        candidate_id=candidate.id,
                        property=PropertyName.DENSITY,
                        value=0.85 + index * 0.04,
                        unit="g/cm^3",
                        provenance=Provenance.EXPERIMENTAL,
                        protocol_hash="fixture",
                    ),
                ),
            )
        )
    predictor = XGBoostEnsemble(
        ensemble_size=2,
        random_seed=7,
        training_domains={
            PropertyName.TG: {Provenance.EXPERIMENTAL},
            PropertyName.DENSITY: {Provenance.EXPERIMENTAL},
        },
    )
    version = predictor.fit(examples)
    predictions = predictor.predict(candidates[:2])
    assert version.startswith("xgboost-")
    assert len(predictions) == 4
    assert all(math.isfinite(item.mean) for item in predictions)
    assert all(item.uncertainty >= 0 for item in predictions)
    predictor.save(tmp_path / "model")
    restored = XGBoostEnsemble.load(tmp_path / "model")
    restored_predictions = restored.predict(candidates[:2])
    assert restored.version == predictor.version
    assert [item.mean for item in restored_predictions] == pytest.approx([item.mean for item in predictions])


def test_xgboost_training_domain_is_explicit() -> None:
    with pytest.raises(ValueError, match="provenance"):
        XGBoostEnsemble(training_domains={})
