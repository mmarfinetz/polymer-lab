"""Betty/local worker for restartable fiber-v1 aligned-chain jobs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import traceback
from pathlib import Path

from .aligned import (
    AlignedChainJob,
    AlignedPreparationCriteria,
    analyze_aligned_preparation,
    extract_forcefield_preamble,
    file_sha256,
    final_equilibration_files,
    lammps_box_lengths,
    latest_restart,
    make_result,
    render_lammps_phase,
)
from .worker import (
    _radonpy_environment,
    _read_radonpy_results,
    _require_declared_versions,
    _require_science_stack,
    _run_stage,
    _truthy,
    _validate_lammps_parallelism,
)


def _artifact_path(uri: str) -> Path:
    if not uri.startswith("file://"):
        raise RuntimeError("aligned-chain v1 requires a shared file:// artifact directory")
    return Path(uri.removeprefix("file://")).resolve()


def _reuse_preparation(
    job: AlignedChainJob,
    prep_root: Path,
    prepared_path: Path,
    versions: dict[str, str],
) -> tuple[Path, Path] | None:
    source = job.preparation_job.spec.extra.get("aligned_preparation_source")
    if source is None:
        return None
    if job.protocol.profile != "protocol_validation":
        raise RuntimeError("a non-RadonPy-converged preparation may only be reused by protocol validation")
    if not isinstance(source, dict):
        raise RuntimeError("aligned_preparation_source must be an immutable mapping")
    source_manifest = Path(str(source.get("source_manifest_path", ""))).resolve()
    source_run = Path(str(source.get("source_run_dir", ""))).resolve()
    if not source_manifest.is_file() or not source_run.is_dir():
        raise RuntimeError("aligned preparation source manifest/run directory is missing")
    manifest_payload = json.loads(source_manifest.read_text())
    if manifest_payload.get("manifest_hash") != source.get("source_aligned_manifest_hash"):
        raise RuntimeError("aligned preparation source manifest identity mismatch")
    stage, data, source_input, log, rg = final_equilibration_files(source_run)
    if stage != int(source.get("equilibration_stage", -1)):
        raise RuntimeError("aligned preparation source stage mismatch")
    expected_checksums = source.get("checksums")
    if not isinstance(expected_checksums, dict):
        raise RuntimeError("aligned preparation source lacks checksums")
    artifacts = {"data": data, "source_input": source_input, "log": log, "rg": rg}
    for name, path in artifacts.items():
        if file_sha256(path) != expected_checksums.get(name):
            raise RuntimeError(f"aligned preparation source checksum mismatch: {name}")
    criteria = AlignedPreparationCriteria.model_validate(source.get("criteria", {}))
    report = analyze_aligned_preparation(
        stage=stage,
        log_path=log,
        rg_path=rg,
        temperature_k=job.protocol.temperature_k,
        pressure_atm=job.protocol.transverse_pressure_atm,
        criteria=criteria,
    )
    if report.criteria_hash != source.get("criteria_hash"):
        raise RuntimeError("aligned preparation criteria hash mismatch")
    if not report.passed:
        raise RuntimeError(f"aligned preparation stationarity failed: {report.failed_checks}")
    prep_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "preparation_manifest_hash": job.preparation_job.manifest_hash,
        "radonpy_full_convergence": False,
        "aligned_stationarity_passed": True,
        "eligible_profile": "protocol_validation",
        "data_path": str(data),
        "source_input_path": str(source_input),
        "checksums": {name: file_sha256(path) for name, path in artifacts.items()},
        "software_versions": versions,
        "stationarity_report": report.model_dump(mode="json"),
        "source_aligned_manifest_hash": source["source_aligned_manifest_hash"],
        "scientific_observations_emitted": False,
    }
    prepared_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return data, source_input


def _prepare(job: AlignedChainJob, artifact_dir: Path, auto_md: Path, versions: dict[str, str]) -> tuple[Path, Path]:
    prep_root = artifact_dir / "preparation"
    prep_log = prep_root / "logs"
    prepared_path = prep_root / "prepared.json"
    if prepared_path.exists():
        payload = json.loads(prepared_path.read_text())
        if payload.get("preparation_manifest_hash") != job.preparation_job.manifest_hash:
            raise RuntimeError("prepared structure belongs to a different immutable preparation job")
        data = Path(payload["data_path"])
        source_input = Path(payload["source_input_path"])
        if file_sha256(data) != payload["checksums"]["data"]:
            raise RuntimeError("prepared LAMMPS data checksum mismatch")
        if file_sha256(source_input) != payload["checksums"]["source_input"]:
            raise RuntimeError("prepared LAMMPS input checksum mismatch")
        return data, source_input

    reused = _reuse_preparation(job, prep_root, prepared_path, versions)
    if reused is not None:
        return reused

    prep_root.mkdir(parents=True, exist_ok=True)
    prep_log.mkdir(parents=True, exist_ok=True)
    (prep_root / "tmp").mkdir(parents=True, exist_ok=True)
    env = _radonpy_environment(job.preparation_job, prep_root)
    _validate_lammps_parallelism(env, prep_root, job.protocol.mpi_ranks)
    for script_name in ("0_qm.py", "1_eq.py"):
        _run_stage(
            auto_md / script_name,
            env,
            prep_root,
            prep_log,
            job.preparation_job.spec.random_seed,
        )
    run_dir = prep_root / job.preparation_job.id
    stage, data, source_input, log, rg = final_equilibration_files(run_dir)
    results = _read_radonpy_results(prep_root, job.preparation_job)
    radonpy_converged = _truthy(results.get("check_eq", False))
    stationarity_report = None
    if not radonpy_converged:
        fallback = job.preparation_job.spec.extra.get("aligned_preparation_gate")
        if job.protocol.profile != "protocol_validation" or fallback != "stationarity-v1":
            review = {
                "schema_version": 1,
                "preparation_manifest_hash": job.preparation_job.manifest_hash,
                "equilibration_strategy": job.preparation_job.spec.extra.get(
                    "equilibration_strategy", "radonpy-default"
                ),
                "radonpy_full_convergence": False,
                "equilibration_stage": stage,
                "data_path": str(data),
                "source_input_path": str(source_input),
                "checksums": {
                    "data": file_sha256(data),
                    "source_input": file_sha256(source_input),
                    "log": file_sha256(log),
                    "rg": file_sha256(rg),
                },
                "software_versions": versions,
                "raw_equilibration_results": results,
                "admissible_as_scientific_evidence": False,
                "scientific_observations_emitted": False,
                "next_action": (
                    "review RadonPy convergence diagnostics before approving one additional "
                    "equilibration block"
                ),
            }
            (prep_root / "equilibration-review.json").write_text(
                json.dumps(review, indent=2, sort_keys=True) + "\n"
            )
            raise RuntimeError("RadonPy preparation did not report converged equilibration")
        criteria = AlignedPreparationCriteria.model_validate(
            job.preparation_job.spec.extra.get("aligned_preparation_criteria", {})
        )
        stationarity_report = analyze_aligned_preparation(
            stage=stage,
            log_path=log,
            rg_path=rg,
            temperature_k=job.protocol.temperature_k,
            pressure_atm=job.protocol.transverse_pressure_atm,
            criteria=criteria,
        )
        if not stationarity_report.passed:
            raise RuntimeError(
                f"aligned preparation stationarity failed: {stationarity_report.failed_checks}"
            )
    payload = {
        "schema_version": 1,
        "preparation_manifest_hash": job.preparation_job.manifest_hash,
        "radonpy_full_convergence": radonpy_converged,
        "aligned_stationarity_passed": bool(stationarity_report and stationarity_report.passed),
        "eligible_profile": "production" if radonpy_converged else "protocol_validation",
        "equilibration_stage": stage,
        "data_path": str(data),
        "source_input_path": str(source_input),
        "checksums": {
            "data": file_sha256(data),
            "source_input": file_sha256(source_input),
            "log": file_sha256(log),
            "rg": file_sha256(rg),
        },
        "software_versions": versions,
        "raw_equilibration_results": results,
        "stationarity_report": (
            stationarity_report.model_dump(mode="json") if stationarity_report else None
        ),
        "scientific_observations_emitted": False,
    }
    prepared_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return data, source_input


def _run_lammps(input_path: Path, output_dir: Path, mpi_ranks: int, environment: dict[str, str]) -> None:
    mpirun = shutil.which("mpirun", path=environment.get("PATH"))
    lammps = shutil.which(environment.get("LAMMPS_EXEC", "lmp"), path=environment.get("PATH"))
    if not mpirun or not lammps:
        raise RuntimeError("aligned-chain worker requires matching mpirun and LAMMPS executables")
    attempt = len(list(output_dir.glob(f"{input_path.stem}.attempt-*.out"))) + 1
    log_path = output_dir / f"{input_path.stem}.attempt-{attempt}.out"
    with log_path.open("wb") as log:
        completed = subprocess.run(
            [mpirun, "-n", str(mpi_ranks), lammps, "-in", str(input_path)],
            cwd=output_dir,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"LAMMPS phase {input_path.stem} failed; see {log_path}")


def _execute_phases(
    job: AlignedChainJob,
    artifact_dir: Path,
    prepared_data: Path,
    source_input: Path,
) -> Path:
    output_dir = artifact_dir / "aligned"
    checkpoints = output_dir / "checkpoints"
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoints.mkdir(parents=True, exist_ok=True)
    preamble = extract_forcefield_preamble(source_input.read_text())
    environment = {**os.environ, "LAMMPS_EXEC": os.environ.get("LAMMPS_EXEC", "lmp")}
    source_by_phase = {
        "draw": prepared_data,
        "relax": output_dir / "draw.data",
        "tensile": output_dir / "relax.data",
    }
    for phase in ("draw", "relax", "tensile"):
        marker = output_dir / f"{phase}.completed"
        if marker.exists():
            continue
        source = source_by_phase[phase]
        restart = latest_restart(checkpoints, phase)
        if restart is None and not source.is_file():
            raise RuntimeError(f"aligned phase {phase} lacks source data: {source}")
        phase_metadata = output_dir / f"{phase}.metadata.json"
        if phase_metadata.exists():
            metadata = json.loads(phase_metadata.read_text())
            initial_lz = float(metadata["initial_lz"])
        else:
            initial_lz = lammps_box_lengths(source)[2]
            phase_metadata.write_text(
                json.dumps(
                    {
                        "phase": phase,
                        "initial_lz": initial_lz,
                        "protocol_hash": job.protocol.protocol_hash,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        input_path = output_dir / f"{phase}.in"
        input_path.write_text(
            render_lammps_phase(
                phase=phase,  # type: ignore[arg-type]
                source=restart or source,
                source_is_restart=restart is not None,
                preamble=preamble,
                destination=output_dir,
                protocol=job.protocol,
                initial_lz=initial_lz,
            )
        )
        _run_lammps(input_path, output_dir, job.protocol.mpi_ranks, environment)
        marker.write_text("completed\n")
    return output_dir


def run(manifest_path: Path) -> Path:
    payload = json.loads(manifest_path.read_text())
    job = AlignedChainJob.model_validate(payload["job"])
    if payload.get("manifest_hash") != job.manifest_hash:
        raise RuntimeError("aligned-chain manifest hash mismatch")
    artifact_dir = _artifact_path(job.artifact_uri)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    auto_md_value = os.environ.get("RADONPY_AUTOMD_DIR")
    if not auto_md_value:
        raise RuntimeError("RADONPY_AUTOMD_DIR must point to reviewed RadonPy AutoMD scripts")
    versions = _require_science_stack(Path(auto_md_value))
    from . import aligned as aligned_module

    versions["polymer_lab_fiber_worker_sha256"] = file_sha256(Path(__file__))
    versions["polymer_lab_aligned_sha256"] = file_sha256(Path(aligned_module.__file__))
    _require_declared_versions(job.preparation_job, versions)
    prepared_data, source_input = _prepare(job, artifact_dir, Path(auto_md_value), versions)
    output_dir = _execute_phases(job, artifact_dir, prepared_data, source_input)
    result = make_result(job, output_dir=output_dir, software_versions=versions)
    destination = artifact_dir / "result.json"
    destination.write_text(result.model_dump_json(indent=2) + "\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        destination = run(args.manifest)
        print(destination)
        return 0
    except Exception as exc:
        failure = {
            "error": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        (args.manifest.parent / "failure.json").write_text(json.dumps(failure, indent=2) + "\n")
        print(f"fiber aligned-chain worker failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
