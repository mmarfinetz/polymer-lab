"""Surrogate predictors with explicit uncertainty and versioning."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

from .errors import DependencyUnavailable
from .models import (
    PolymerCandidate,
    Prediction,
    PropertyName,
    Provenance,
    TrainingExample,
    stable_hash,
)

PROPERTY_UNITS = {
    PropertyName.TG: "degC",
    PropertyName.DENSITY: "g/cm^3",
}


class DeterministicSurrogate:
    """Test/demo-only predictor; outputs are always labeled non-scientific."""

    def __init__(self, version: str = "deterministic-test-v1") -> None:
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def fit(self, observations: Iterable[Any]) -> str:
        count = sum(1 for _ in observations)
        self._version = f"deterministic-test-v1-n{count}"
        return self._version

    def predict(self, candidates: Sequence[PolymerCandidate]) -> list[Prediction]:
        result: list[Prediction] = []
        for candidate in candidates:
            digest = int(candidate.structure_hash[:12], 16)
            aromatic = candidate.canonical_psmiles.count("c")
            hetero = sum(candidate.canonical_psmiles.count(symbol) for symbol in ("N", "O", "S", "F"))
            tg = 40.0 + aromatic * 18.0 + hetero * 7.0 + (digest % 8000) / 100.0
            density = 0.82 + hetero * 0.035 + ((digest // 97) % 240) / 1000.0
            uncertainty = 8.0 + (digest % 1200) / 100.0
            result.extend(
                (
                    Prediction(
                        candidate_id=candidate.id,
                        property=PropertyName.TG,
                        mean=tg,
                        uncertainty=uncertainty,
                        unit="degC",
                        model_version=self.version,
                    ),
                    Prediction(
                        candidate_id=candidate.id,
                        property=PropertyName.DENSITY,
                        mean=density,
                        uncertainty=0.02 + uncertainty / 1000.0,
                        unit="g/cm^3",
                        model_version=self.version,
                    ),
                )
            )
        return result


class XGBoostEnsemble:
    """Bootstrapped per-property XGBoost ensemble over RDKit descriptors/fingerprints."""

    def __init__(
        self,
        *,
        training_domains: Mapping[PropertyName, set[Provenance] | frozenset[Provenance]],
        ensemble_size: int = 8,
        random_seed: int = 42,
        model_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not training_domains or any(not domains for domains in training_domains.values()):
            raise ValueError("each trained property requires an explicit provenance domain")
        if ensemble_size < 2:
            raise ValueError("uncertainty estimation requires at least two ensemble members")
        try:
            import numpy as np
            import xgboost as xgb
            from rdkit import Chem, DataStructs
            from rdkit.Chem import Descriptors, rdFingerprintGenerator
        except ImportError as exc:
            raise DependencyUnavailable("XGBoostEnsemble requires polymer-lab[science]") from exc
        self.np = np
        self.xgb = xgb
        self.Chem = Chem
        self.DataStructs = DataStructs
        self.Descriptors = Descriptors
        self.fingerprint_generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
        self.ensemble_size = ensemble_size
        self.random_seed = random_seed
        self.training_domains = {
            property_name: frozenset(domains) for property_name, domains in training_domains.items()
        }
        self.model_metadata = dict(model_metadata or {})
        self.models: dict[PropertyName, list[Any]] = defaultdict(list)
        self._version = "xgboost-untrained"

    @property
    def version(self) -> str:
        return self._version

    def _features(self, candidate: PolymerCandidate) -> Any:
        mol = self.Chem.MolFromSmiles(candidate.canonical_psmiles)
        if mol is None:
            raise ValueError(f"invalid candidate {candidate.id}")
        fingerprint = self.fingerprint_generator.GetFingerprint(mol)
        fp_array = self.np.zeros((2048,), dtype=float)
        self.DataStructs.ConvertToNumpyArray(fingerprint, fp_array)
        descriptors = self.np.array(
            [
                self.Descriptors.MolWt(mol),
                self.Descriptors.MolLogP(mol),
                self.Descriptors.TPSA(mol),
                self.Descriptors.NumRotatableBonds(mol),
                self.Descriptors.RingCount(mol),
                self.Descriptors.FractionCSP3(mol),
            ],
            dtype=float,
        )
        return self.np.concatenate((descriptors, fp_array))

    def fit(self, examples: Iterable[TrainingExample]) -> str:
        grouped: dict[PropertyName, list[TrainingExample]] = defaultdict(list)
        all_examples = list(examples)
        for example in all_examples:
            if example.observation.converged and example.observation.provenance in self.training_domains.get(
                example.observation.property, frozenset()
            ):
                grouped[example.observation.property].append(example)
        self.models.clear()
        rng = random.Random(self.random_seed)
        for property_name, rows in grouped.items():
            if len(rows) < 8:
                continue
            features = self.np.vstack([self._features(row.candidate) for row in rows])
            labels = self.np.array([row.observation.value for row in rows], dtype=float)
            for member in range(self.ensemble_size):
                indices = self.np.array([rng.randrange(len(rows)) for _ in rows])
                model = self.xgb.XGBRegressor(
                    n_estimators=300,
                    max_depth=6,
                    learning_rate=0.04,
                    subsample=0.85,
                    colsample_bytree=0.8,
                    objective="reg:squarederror",
                    n_jobs=1,
                    random_state=self.random_seed + member,
                )
                model.fit(features[indices], labels[indices])
                self.models[property_name].append(model)
        if not self.models:
            domains = {
                property_name.value: sorted(item.value for item in provenance)
                for property_name, provenance in self.training_domains.items()
            }
            raise ValueError(f"no property has eight converged training rows in the selected domains: {domains}")
        self._version = (
            "xgboost-"
            + stable_hash(
                {
                    "examples": sorted(
                        stable_hash(
                            {
                                "structure_hash": example.candidate.structure_hash,
                                "property": example.observation.property.value,
                                "value": example.observation.value,
                                "unit": example.observation.unit,
                                "provenance": example.observation.provenance.value,
                                "protocol_hash": example.observation.protocol_hash,
                            }
                        )
                        for example in all_examples
                        if example.observation.provenance
                        in self.training_domains.get(example.observation.property, frozenset())
                    ),
                    "ensemble_size": self.ensemble_size,
                    "training_domains": {
                        property_name.value: sorted(item.value for item in provenance)
                        for property_name, provenance in sorted(
                            self.training_domains.items(), key=lambda item: item[0].value
                        )
                    },
                    "seed": self.random_seed,
                }
            )[:16]
        )
        return self._version

    def predict(self, candidates: Sequence[PolymerCandidate]) -> list[Prediction]:
        if not self.models:
            raise RuntimeError("XGBoostEnsemble must be fitted before prediction")
        features = self.np.vstack([self._features(candidate) for candidate in candidates])
        predictions: list[Prediction] = []
        for property_name in sorted(self.models, key=lambda item: item.value):
            models = self.models[property_name]
            values_by_model = [model.predict(features) for model in models]
            for index, candidate in enumerate(candidates):
                values = [float(values[index]) for values in values_by_model]
                predictions.append(
                    Prediction(
                        candidate_id=candidate.id,
                        property=property_name,
                        mean=fmean(values),
                        uncertainty=pstdev(values),
                        unit=PROPERTY_UNITS[property_name],
                        model_version=self.version,
                    )
                )
        return predictions

    def save(self, directory: str | Path) -> Path:
        if not self.models:
            raise RuntimeError("cannot persist an untrained ensemble")
        destination = Path(directory).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        model_files: dict[str, list[str]] = {}
        for property_name in sorted(self.models, key=lambda item: item.value):
            models = self.models[property_name]
            names: list[str] = []
            for index, model in enumerate(models):
                name = f"{property_name.value}-{index}.ubj"
                model.save_model(destination / name)
                names.append(name)
            model_files[property_name.value] = names
        manifest = {
            "schema_version": 1,
            "version": self.version,
            "ensemble_size": self.ensemble_size,
            "random_seed": self.random_seed,
            "training_domains": {
                property_name.value: sorted(item.value for item in provenance)
                for property_name, provenance in sorted(self.training_domains.items(), key=lambda item: item[0].value)
            },
            "model_metadata": self.model_metadata,
            "model_files": model_files,
        }
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        return manifest_path

    @classmethod
    def load(cls, directory: str | Path) -> XGBoostEnsemble:
        source = Path(directory).resolve()
        manifest = json.loads((source / "manifest.json").read_text())
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported XGBoost ensemble manifest schema")
        predictor = cls(
            training_domains={
                PropertyName(property_name): {Provenance(item) for item in provenance}
                for property_name, provenance in manifest["training_domains"].items()
            },
            ensemble_size=int(manifest["ensemble_size"]),
            random_seed=int(manifest["random_seed"]),
            model_metadata=manifest.get("model_metadata", {}),
        )
        for property_value, names in manifest["model_files"].items():
            property_name = PropertyName(property_value)
            for name in names:
                model_path = (source / name).resolve()
                if source not in model_path.parents or not model_path.is_file():
                    raise ValueError(f"invalid ensemble model path: {name}")
                model = predictor.xgb.XGBRegressor()
                model.load_model(model_path)
                predictor.models[property_name].append(model)
        if not predictor.models:
            raise ValueError("ensemble manifest contains no models")
        predictor._version = str(manifest["version"])
        return predictor
