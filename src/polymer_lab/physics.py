"""Physics job manifests and strict RadonPy result admission."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .errors import ScientificResultError
from .models import PhysicsJob, PhysicsResult, PropertyName, Provenance


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RadonPyEvaluator:
    RESULT_FILENAME = "result.json"

    def write_manifest(self, job: PhysicsJob, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "manifest_hash": job.manifest_hash,
            "job": job.model_dump(mode="json"),
        }
        destination.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return destination

    def read_result(self, job: PhysicsJob, source: Path) -> PhysicsResult:
        if not source.exists():
            raise ScientificResultError(f"result file does not exist: {source}")
        try:
            result = PhysicsResult.model_validate_json(source.read_text())
        except Exception as exc:
            raise ScientificResultError(f"malformed physics result: {exc}") from exc
        if result.job_id != job.id or result.candidate_id != job.candidate.id:
            raise ScientificResultError("result identity does not match job manifest")
        if result.protocol_hash != job.spec.protocol_hash:
            raise ScientificResultError("result protocol hash does not match job manifest")
        property_counts = {
            property_name: sum(observation.property == property_name for observation in result.observations)
            for property_name in job.requested_properties
        }
        properties = {observation.property for observation in result.observations}
        missing = set(job.requested_properties) - properties
        if missing:
            raise ScientificResultError(f"result is missing requested properties: {sorted(missing)}")
        duplicates = [property_name.value for property_name, count in property_counts.items() if count != 1]
        if duplicates:
            raise ScientificResultError(f"result must contain exactly one value for: {sorted(duplicates)}")
        if not result.converged or not all(observation.converged for observation in result.observations):
            raise ScientificResultError("unconverged physics may not be admitted as scientific evidence")
        expected_units = {PropertyName.TG: "degC", PropertyName.DENSITY: "g/cm^3"}
        for observation in result.observations:
            if observation.candidate_id != job.candidate.id:
                raise ScientificResultError("observation candidate does not match job manifest")
            if observation.protocol_hash != job.spec.protocol_hash:
                raise ScientificResultError("observation protocol does not match job manifest")
            if observation.provenance != Provenance.MD:
                raise ScientificResultError("RadonPy observations must have MD provenance")
            if not math.isfinite(observation.value) or (
                observation.uncertainty is not None and not math.isfinite(observation.uncertainty)
            ):
                raise ScientificResultError("observation contains a non-finite number")
            if observation.unit != expected_units[observation.property]:
                raise ScientificResultError(f"unexpected unit for {observation.property}: {observation.unit}")
            if observation.property == PropertyName.DENSITY and not 0 < observation.value < 5:
                raise ScientificResultError("density is outside the admissible polymer range")
            if observation.property == PropertyName.TG and not -273.15 < observation.value < 1000:
                raise ScientificResultError("Tg is outside the admissible range")

        required_software = {"radonpy", "rdkit", "psi4", "lammps"}
        unavailable = [
            name for name in required_software if result.software_versions.get(name) in {None, "", "missing", "unknown"}
        ]
        if unavailable:
            raise ScientificResultError(f"result lacks required software version metadata: {sorted(unavailable)}")
        declared_versions = {
            "radonpy": job.spec.radonpy_version,
            "rdkit": job.spec.rdkit_version,
            "psi4": job.spec.psi4_version,
            "lammps": job.spec.lammps_version,
        }
        for name, declared in declared_versions.items():
            if declared not in {"environment", "stable"} and result.software_versions[name] != declared:
                raise ScientificResultError(
                    f"{name} version mismatch: declared {declared}, observed {result.software_versions[name]}"
                )

        artifact_root = source.parent.resolve()
        for relative_path, expected_digest in result.artifact_checksums.items():
            artifact = (artifact_root / relative_path).resolve()
            if artifact_root not in artifact.parents:
                raise ScientificResultError("artifact checksum path escapes the job directory")
            if not artifact.is_file():
                raise ScientificResultError(f"checksummed artifact is missing: {relative_path}")
            observed_digest = _file_sha256(artifact)
            if observed_digest != expected_digest:
                raise ScientificResultError(f"artifact checksum mismatch: {relative_path}")
        return result
