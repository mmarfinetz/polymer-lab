from __future__ import annotations

import hashlib
import json

import pytest

from polymer_lab.errors import ScientificResultError
from polymer_lab.models import (
    Observation,
    PhysicsJob,
    PhysicsResult,
    PropertyName,
    Provenance,
    SimulationSpec,
)
from polymer_lab.physics import RadonPyEvaluator
from polymer_lab.validation import BasicPSmilesValidator


def _job(tmp_path) -> PhysicsJob:
    return PhysicsJob(
        campaign_id="campaign",
        candidate=BasicPSmilesValidator().validate("[*]CC[*]"),
        spec=SimulationSpec(),
        artifact_uri=tmp_path.as_uri(),
        estimated_core_hours=20,
    )


def _result(job: PhysicsJob, *, converged: bool = True) -> PhysicsResult:
    return PhysicsResult(
        job_id=job.id,
        candidate_id=job.candidate.id,
        protocol_hash=job.spec.protocol_hash,
        converged=converged,
        software_versions={
            "radonpy": "1.0b2",
            "rdkit": "test",
            "psi4": "1.10",
            "lammps": "test",
        },
        observations=(
            Observation(
                candidate_id=job.candidate.id,
                property=PropertyName.DENSITY,
                value=0.91,
                unit="g/cm^3",
                provenance=Provenance.MD,
                protocol_hash=job.spec.protocol_hash,
                converged=converged,
            ),
            Observation(
                candidate_id=job.candidate.id,
                property=PropertyName.TG,
                value=-110,
                unit="degC",
                provenance=Provenance.MD,
                protocol_hash=job.spec.protocol_hash,
                converged=converged,
            ),
        ),
    )


def test_result_admission_requires_matching_converged_physics(tmp_path) -> None:
    evaluator = RadonPyEvaluator()
    job = _job(tmp_path)
    source = tmp_path / "result.json"
    source.write_text(_result(job).model_dump_json())
    assert evaluator.read_result(job, source).converged
    source.write_text(_result(job, converged=False).model_dump_json())
    with pytest.raises(ScientificResultError, match="unconverged"):
        evaluator.read_result(job, source)


def test_manifest_tampering_is_detectable(tmp_path) -> None:
    evaluator = RadonPyEvaluator()
    job = _job(tmp_path)
    manifest = evaluator.write_manifest(job, tmp_path / "manifest.json")
    payload = json.loads(manifest.read_text())
    assert payload["manifest_hash"] == job.manifest_hash
    assert payload["job"]["candidate"]["canonical_psmiles"] == "[*]CC[*]"


def test_result_admission_verifies_artifact_checksums(tmp_path) -> None:
    evaluator = RadonPyEvaluator()
    job = _job(tmp_path)
    artifact = tmp_path / "trajectory.log"
    artifact.write_bytes(b"scientific output")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = _result(job).model_copy(update={"artifact_checksums": {artifact.name: digest}})
    source = tmp_path / "result.json"
    source.write_text(result.model_dump_json())
    assert evaluator.read_result(job, source).converged
    artifact.write_bytes(b"tampered")
    with pytest.raises(ScientificResultError, match="checksum mismatch"):
        evaluator.read_result(job, source)
