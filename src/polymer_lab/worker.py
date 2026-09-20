"""Isolated scientific worker that invokes RadonPy's supported AutoMD pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from .models import JobState, Observation, PhysicsJob, PhysicsResult, PropertyName, Provenance


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _detect_lammps_version(lammps_executable: str) -> str:
    resolved = shutil.which(lammps_executable)
    if not resolved:
        return "missing"
    try:
        completed = subprocess.run([resolved, "-h"], capture_output=True, text=True, timeout=30)
    except Exception:
        return "missing"
    if completed.returncode != 0:
        return "missing"
    lines = [line.strip() for line in f"{completed.stdout}\n{completed.stderr}".splitlines() if line.strip()]
    if not lines:
        return "unknown"
    return next(
        (line for line in lines if "Large-scale Atomic/Molecular Massively Parallel Simulator" in line),
        lines[0],
    )


def _versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for name, distribution in (
        ("radonpy", "radonpy-pypi"),
        ("rdkit", "rdkit"),
        ("psi4", "psi4"),
    ):
        try:
            versions[name] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            # Conda's Psi4 package may not ship Python distribution metadata.
            # Importing it is the authoritative availability check in that case.
            if name == "psi4":
                try:
                    import psi4

                    versions[name] = str(psi4.__version__)
                except Exception:
                    versions[name] = "missing"
            else:
                versions[name] = "missing"
    lammps_executable = os.environ.get("LAMMPS_EXEC", "lmp")
    versions["lammps"] = _detect_lammps_version(lammps_executable)
    return versions


def _require_science_stack(auto_md_dir: Path) -> dict[str, str]:
    versions = _versions()
    missing = [
        name
        for name in ("radonpy", "rdkit", "psi4", "lammps")
        if versions[name] in {"", "missing", "unknown"}
    ]
    required_scripts = [auto_md_dir / name for name in ("0_qm.py", "1_eq.py", "4_tg.py")]
    missing_scripts = [str(path) for path in required_scripts if not path.is_file()]
    if missing or missing_scripts:
        raise RuntimeError(f"scientific worker is incomplete; missing packages={missing}, scripts={missing_scripts}")
    for script in required_scripts:
        versions[f"automd_{script.stem}_sha256"] = _file_sha256(script)
    from . import radonpy_resume

    versions["polymer_lab_radonpy_resume_sha256"] = _file_sha256(Path(radonpy_resume.__file__))
    return versions


def _require_declared_versions(job: PhysicsJob, versions: dict[str, str]) -> None:
    declared_versions = {
        "radonpy": job.spec.radonpy_version,
        "rdkit": job.spec.rdkit_version,
        "psi4": job.spec.psi4_version,
        "lammps": job.spec.lammps_version,
    }
    mismatches = {
        name: {"declared": declared, "observed": versions[name]}
        for name, declared in declared_versions.items()
        if declared not in {"environment", "stable"} and versions[name] != declared
    }
    if mismatches:
        raise RuntimeError(f"scientific worker version mismatch: {mismatches}")


def _radonpy_environment(job: PhysicsJob, work_dir: Path) -> dict[str, str]:
    spec = job.spec
    omp = str(int(spec.extra.get("omp", 1)))
    mpi = str(int(spec.extra.get("mpi", os.cpu_count() or 1)))
    lammps_executable = Path(os.environ.get("LAMMPS_EXEC", "lmp"))
    # Psi4 uses a process-global scratch area by default. Concurrent local jobs
    # can otherwise collide on PSIO mirror files and fail nondeterministically.
    psi_scratch = work_dir / "psi4_scratch"
    psi_scratch.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        # RadonPy invokes `mpirun` by name. Directly launching this worker with
        # an environment-specific Python does not otherwise put the matching
        # MPI runtime on PATH.
        "PATH": f"{lammps_executable.parent}:{os.environ.get('PATH', '')}",
        "RadonPy_DBID": job.id,
        "RadonPy_SMILES": job.candidate.canonical_psmiles,
        "RadonPy_Monomer_ID": job.candidate.structure_hash[:16],
        "RadonPy_NAtom": str(spec.target_atoms_per_chain),
        "RadonPy_NChain": str(spec.chain_count),
        "RadonPy_Ini_Density": str(spec.initial_density_g_cm3),
        "RadonPy_Tacticity": spec.tacticity,
        "RadonPy_FF": spec.force_field,
        "RadonPy_Charge": spec.charge_method,
        "RadonPy_Temp": str(spec.temperature_k),
        "RadonPy_Press": str(spec.pressure_atm),
        "RadonPy_OMP": omp,
        "RadonPy_MPI": mpi,
        "RadonPy_OMP_Psi4": str(int(spec.extra.get("psi4_omp", 4))),
        "RadonPy_MEM_Psi4": str(int(spec.extra.get("psi4_memory_mb", 8000))),
        "RadonPy_RetryEQ": str(int(spec.extra.get("retry_equilibration", 2))),
        "RadonPy_TMP_Dir": str(work_dir / "tmp"),
        "PSI_SCRATCH": str(psi_scratch),
        "PSI4_SCRATCH": str(psi_scratch),
        "RadonPy_No_Traj": str(bool(spec.extra.get("no_trajectory", False))),
        "RadonPy_Del_Traj": "False",
        "PolymerLab_EQ_Dump_Frequency": str(
            int(spec.extra.get("sampling_dump_frequency_steps", 1000))
        ),
        "PYTHONHASHSEED": str(spec.random_seed),
    }


def _validate_lammps_parallelism(env: dict[str, str], work_dir: Path, requested_mpi: int) -> None:
    """Fail before production MD if MPI silently collapses to one process."""

    if requested_mpi <= 1:
        return
    mpirun = shutil.which("mpirun", path=env.get("PATH"))
    lammps_executable = shutil.which(env.get("LAMMPS_EXEC", "lmp"), path=env.get("PATH"))
    if not mpirun or not lammps_executable:
        raise RuntimeError(
            "parallel RadonPy execution requested but an MPI launcher or LAMMPS executable is missing"
        )
    probe = work_dir / "polymer_lab_mpi_probe.in"
    probe.write_text(
        "\n".join(
            (
                "units real",
                "atom_style atomic",
                "lattice sc 2.0",
                "region box block 0 2 0 2 0 2",
                "create_box 1 box",
                "create_atoms 1 box",
                "mass 1 1.0",
                "pair_style zero 3.0",
                "pair_coeff * *",
                "run 0",
                "quit",
                "",
            )
        )
    )
    probe_ranks = min(2, requested_mpi)
    completed = subprocess.run(
        [mpirun, "-n", str(probe_ranks), lammps_executable, "-in", str(probe), "-log", "none"],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    evidence = f"{probe_ranks} MPI tasks"
    if completed.returncode != 0 or evidence not in combined:
        raise RuntimeError(
            "LAMMPS MPI validation failed before production MD: "
            f"requested={probe_ranks}, returncode={completed.returncode}, output={combined[-2000:]}"
        )


def _run_stage(script: Path, env: dict[str, str], cwd: Path, log_dir: Path, seed: int) -> None:
    stage = script.stem
    marker = log_dir / f"{stage}.completed"
    if marker.exists():
        return
    log_path = log_dir / f"{stage}.log"
    with log_path.open("wb") as log:
        bootstrap = (
            "import random,runpy,sys; "
            "seed=int(sys.argv[2]); random.seed(seed); "
            "import numpy; numpy.random.seed(seed); "
            "from rdkit import rdBase; rdBase.SeedRandomNumberGenerator(seed); "
            "from polymer_lab.radonpy_resume import install_equilibration_resume; "
            "install_equilibration_resume(); "
            "runpy.run_path(sys.argv[1], run_name='__main__')"
        )
        completed = subprocess.run(
            [sys.executable, "-c", bootstrap, str(script), str(seed)],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"RadonPy stage {stage} failed; see {log_path}")
    marker.write_text("completed\n")


def _read_radonpy_results(run_root: Path, job: PhysicsJob) -> dict[str, str]:
    candidates = [
        run_root / job.id / "analyze" / "input_data.csv",
        run_root / job.id / "analyze" / "results.csv",
    ]
    combined: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            row = next(reader, None)
            if row:
                combined.update({key: value for key, value in row.items() if value not in (None, "")})
    return combined


def run(manifest_path: Path, *, check_only: bool = False) -> Path:
    payload = json.loads(manifest_path.read_text())
    job = PhysicsJob.model_validate(payload["job"])
    if payload.get("manifest_hash") != job.manifest_hash:
        raise RuntimeError("manifest hash mismatch")
    if job.state not in {JobState.APPROVED, JobState.SUBMITTED, JobState.RUNNING}:
        raise RuntimeError(f"physics job is not approved for execution: {job.state}")
    auto_md_value = os.environ.get("RADONPY_AUTOMD_DIR")
    if not auto_md_value:
        raise RuntimeError("RADONPY_AUTOMD_DIR must point to RadonPy/AutoMD_scripts")
    auto_md = Path(auto_md_value)
    versions = _require_science_stack(auto_md)
    _require_declared_versions(job, versions)
    if check_only:
        destination = manifest_path.parent / "dependency-check.json"
        destination.write_text(json.dumps(versions, indent=2, sort_keys=True))
        return destination
    if job.spec.profile != "production":
        raise RuntimeError("smoke profiles may check dependencies but may not emit scientific observations")

    run_root = manifest_path.parent / "radonpy"
    log_dir = manifest_path.parent / "logs"
    run_root.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    (run_root / "tmp").mkdir(parents=True, exist_ok=True)
    env = _radonpy_environment(job, run_root)
    _validate_lammps_parallelism(env, run_root, int(job.spec.extra.get("mpi", 1)))
    for script_name in ("0_qm.py", "1_eq.py", "4_tg.py"):
        _run_stage(auto_md / script_name, env, run_root, log_dir, job.spec.random_seed)

    data = _read_radonpy_results(run_root, job)
    if not data:
        raise RuntimeError("RadonPy produced no results.csv/input_data.csv")
    converged = _truthy(data.get("check_eq", False))
    if not converged:
        raise RuntimeError("RadonPy equilibration did not converge")
    try:
        density = float(data["density"])
        tg_kelvin = float(data["tg"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("RadonPy result is missing numeric density or tg") from exc

    observations = (
        Observation(
            candidate_id=job.candidate.id,
            property=PropertyName.DENSITY,
            value=density,
            unit="g/cm^3",
            provenance=Provenance.MD,
            protocol_hash=job.spec.protocol_hash,
            converged=True,
            metadata={"radonpy_field": "density", "raw_results": data},
        ),
        Observation(
            candidate_id=job.candidate.id,
            property=PropertyName.TG,
            value=tg_kelvin - 273.15,
            unit="degC",
            provenance=Provenance.MD,
            protocol_hash=job.spec.protocol_hash,
            converged=True,
            metadata={"radonpy_field": "tg", "raw_unit": "K", "raw_value": tg_kelvin},
        ),
    )
    checksums: dict[str, str] = {}
    for path in manifest_path.parent.rglob("*"):
        if path.is_file() and path.name != "result.json":
            checksums[str(path.relative_to(manifest_path.parent))] = _file_sha256(path)
    result = PhysicsResult(
        job_id=job.id,
        candidate_id=job.candidate.id,
        protocol_hash=job.spec.protocol_hash,
        observations=observations,
        converged=True,
        software_versions=versions,
        artifact_checksums=checksums,
    )
    destination = manifest_path.parent / "result.json"
    destination.write_text(result.model_dump_json(indent=2))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        destination = run(args.manifest, check_only=args.check_only)
        print(destination)
        return 0
    except Exception as exc:
        failure = {
            "error": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        (args.manifest.parent / "failure.json").write_text(json.dumps(failure, indent=2))
        print(f"worker failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
