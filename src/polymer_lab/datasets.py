"""Provenance-preserving CSV ingestion for PI1M and experimental property data."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import model_validator

from .errors import ValidationError
from .models import (
    FrozenModel,
    Observation,
    PolymerCandidate,
    PropertyName,
    Provenance,
    stable_hash,
)
from .protocols import CandidateValidator
from .validation import unique_candidates


class RejectedRow(FrozenModel):
    row_number: int
    reason: str
    raw: dict[str, Any]


class IngestReport(FrozenModel):
    source: str
    source_checksum: str
    accepted_candidates: int
    accepted_observations: int = 0
    duplicate_candidates: int = 0
    rejected: tuple[RejectedRow, ...] = ()
    license_note: str


class IngestBatch(FrozenModel):
    candidates: tuple[PolymerCandidate, ...]
    observations: tuple[Observation, ...] = ()
    report: IngestReport


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str:
    normalized = {name.strip().lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    raise ValidationError(f"none of the required columns are present: {candidates}")


def load_pi1m(
    path: str | Path,
    validator: CandidateValidator,
    *,
    limit: int | None = None,
) -> IngestBatch:
    """Load user-supplied PI1M data without downloading or redistributing it."""
    source = Path(path)
    checksum = file_sha256(source)
    accepted: list[PolymerCandidate] = []
    rejected: list[RejectedRow] = []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValidationError("PI1M CSV has no header")
        smiles_column = _find_column(
            reader.fieldnames,
            ("psmiles", "p-smiles", "smiles", "polymer_smiles", "SMILES"),
        )
        for row_number, row in enumerate(reader, start=2):
            if limit is not None and len(accepted) >= limit:
                break
            try:
                accepted.append(
                    validator.validate(
                        row[smiles_column],
                        generation_method="dataset:pi1m",
                        metadata={
                            "dataset": "PI1M",
                            "dataset_checksum": checksum,
                            "source_row": row_number,
                            "synthetic_accessibility": row.get("SA Score") or row.get("sa_score"),
                        },
                    )
                )
            except Exception as exc:
                rejected.append(RejectedRow(row_number=row_number, reason=str(exc), raw=dict(row)))
    unique = unique_candidates(accepted)
    report = IngestReport(
        source=str(source),
        source_checksum=checksum,
        accepted_candidates=len(unique),
        duplicate_candidates=len(accepted) - len(unique),
        rejected=tuple(rejected),
        license_note="PI1M data: academic purpose only; do not redistribute from this project.",
    )
    return IngestBatch(candidates=tuple(unique), report=report)


class PropertyColumn(FrozenModel):
    property: PropertyName
    unit: str
    scale: float = 1.0
    offset: float = 0.0

    @model_validator(mode="after")
    def canonical_unit(self) -> PropertyColumn:
        expected = {
            PropertyName.TG: "degC",
            PropertyName.DENSITY: "g/cm^3",
        }[self.property]
        if self.unit != expected:
            raise ValueError(f"{self.property.value} must be converted into canonical unit {expected!r}")
        return self


def load_experimental_csv(
    path: str | Path,
    validator: CandidateValidator,
    *,
    property_columns: Mapping[str, PropertyColumn],
    smiles_column: str | None = None,
    dataset_name: str = "experimental",
    source_reference: str | None = None,
    license_note: str = "User supplied; verify source terms before use.",
) -> IngestBatch:
    """Load explicit structure/property mappings without guessing units."""
    source = Path(path)
    checksum = file_sha256(source)
    candidates: list[PolymerCandidate] = []
    observations: list[Observation] = []
    rejected: list[RejectedRow] = []
    candidate_by_hash: dict[str, PolymerCandidate] = {}
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValidationError("experimental CSV has no header")
        resolved_smiles = smiles_column or _find_column(
            reader.fieldnames,
            ("psmiles", "p-smiles", "smiles", "polymer_smiles", "PSMILES"),
        )
        missing = set(property_columns) - set(reader.fieldnames)
        if missing:
            raise ValidationError(f"configured property columns are missing: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            try:
                candidate = validator.validate(
                    row[resolved_smiles],
                    generation_method=f"dataset:{dataset_name}",
                    metadata={
                        "dataset": dataset_name,
                        "dataset_checksum": checksum,
                        "source_row": row_number,
                    },
                )
                candidate = candidate_by_hash.get(candidate.structure_hash, candidate)
                row_observations: list[Observation] = []
                for column_name, definition in property_columns.items():
                    raw = row.get(column_name, "").strip()
                    if not raw:
                        continue
                    value = float(raw) * definition.scale + definition.offset
                    row_observations.append(
                        Observation(
                            candidate_id=candidate.id,
                            property=definition.property,
                            value=value,
                            unit=definition.unit,
                            provenance=Provenance.EXPERIMENTAL,
                            protocol_hash=stable_hash(
                                {
                                    "dataset": dataset_name,
                                    "checksum": checksum,
                                    "column": column_name,
                                    "scale": definition.scale,
                                    "offset": definition.offset,
                                }
                            ),
                            source_reference=source_reference,
                            metadata={
                                "dataset": dataset_name,
                                "source_row": row_number,
                                "source_column": column_name,
                            },
                        )
                    )
                if not row_observations:
                    raise ValueError("row has no configured numeric property value")
                candidate_by_hash.setdefault(candidate.structure_hash, candidate)
                candidates.append(candidate)
                observations.extend(row_observations)
            except Exception as exc:
                rejected.append(RejectedRow(row_number=row_number, reason=str(exc), raw=dict(row)))
    unique = list(candidate_by_hash.values())
    report = IngestReport(
        source=str(source),
        source_checksum=checksum,
        accepted_candidates=len(unique),
        accepted_observations=len(observations),
        duplicate_candidates=len(candidates) - len(unique),
        rejected=tuple(rejected),
        license_note=license_note,
    )
    return IngestBatch(candidates=tuple(unique), observations=tuple(observations), report=report)


def load_radonpy_pi1070(
    path: str | Path,
    validator: CandidateValidator,
) -> IngestBatch:
    """Load the published PI1070 density corpus as MD, never experimental, evidence."""
    source = Path(path)
    checksum = file_sha256(source)
    candidate_by_hash: dict[str, PolymerCandidate] = {}
    candidates: list[PolymerCandidate] = []
    observations: list[Observation] = []
    rejected: list[RejectedRow] = []
    protocol_hash = stable_hash(
        {
            "dataset": "RadonPy PI1070",
            "checksum": checksum,
            "property": "density",
            "declared_conditions": "row metadata",
        }
    )
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValidationError("RadonPy PI1070 CSV has no header")
        required = {"smiles", "density", "temp", "press"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValidationError(f"RadonPy PI1070 columns are missing: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            try:
                candidate = validator.validate(
                    row["smiles"],
                    generation_method="dataset:radonpy-pi1070",
                    metadata={
                        "dataset": "RadonPy PI1070",
                        "dataset_checksum": checksum,
                        "source_row": row_number,
                        "monomer_id": row.get("monomer_ID"),
                    },
                )
                candidate = candidate_by_hash.get(candidate.structure_hash, candidate)
                observation = Observation(
                    candidate_id=candidate.id,
                    property=PropertyName.DENSITY,
                    value=float(row["density"]),
                    unit="g/cm^3",
                    uncertainty=(float(row["density_std"]) if row.get("density_std", "").strip() else None),
                    provenance=Provenance.MD,
                    protocol_hash=protocol_hash,
                    source_reference=("https://github.com/RadonPy/RadonPy/blob/develop/data/PI1070.csv"),
                    metadata={
                        "dataset": "RadonPy PI1070",
                        "source_row": row_number,
                        "temperature_k": float(row["temp"]),
                        "pressure_atm": float(row["press"]),
                        "tacticity": row.get("tacticity"),
                        "degree_polymerization": row.get("DP"),
                    },
                )
                candidate_by_hash.setdefault(candidate.structure_hash, candidate)
                candidates.append(candidate)
                observations.append(observation)
            except Exception as exc:
                rejected.append(RejectedRow(row_number=row_number, reason=str(exc), raw=dict(row)))
    unique = list(candidate_by_hash.values())
    report = IngestReport(
        source=str(source),
        source_checksum=checksum,
        accepted_candidates=len(unique),
        accepted_observations=len(observations),
        duplicate_candidates=len(candidates) - len(unique),
        rejected=tuple(rejected),
        license_note="RadonPy PI1070 distributed with the BSD-3-Clause RadonPy project.",
    )
    return IngestBatch(candidates=tuple(unique), observations=tuple(observations), report=report)
