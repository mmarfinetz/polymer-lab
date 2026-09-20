"""Analysis-only recovery for completed RadonPy equilibration trajectories."""

from __future__ import annotations

import contextlib
import importlib.metadata
import inspect
import io
import json
import math
import os
from pathlib import Path
from typing import Any

from .aligned import AlignedChainJob, file_sha256
from .worker import _require_declared_versions, _require_science_stack


def adaptive_trajectory_window(frame_count: int, requested_width: int = 2000) -> tuple[int, int]:
    """Return a valid (init, width) pair without changing thermo/Rg analysis windows."""

    if requested_width < 2:
        raise ValueError("requested trajectory width must be at least two frames")
    if frame_count < 3:
        raise ValueError("trajectory analysis requires at least three frames")
    width = min(requested_width, frame_count - 1)
    return width, width


def _json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "tolist"):
        value = value.tolist()
    elif hasattr(value, "item"):
        value = value.item()
    if isinstance(value, complex):
        return {
            "real": _json_value(value.real),
            "imaginary": _json_value(value.imag),
        }
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _compact_diagnostics(values: dict[str, Any]) -> dict[str, Any]:
    """Keep auditable scalar statistics out of potentially huge per-frame arrays."""

    scalar_fields = ("init", "last", "mean", "sd", "se", "sma_sd", "sma_se", "width")
    return {field: values[field] for field in scalar_fields if field in values}


def _manifest_job(manifest_path: Path) -> AlignedChainJob:
    payload = json.loads(manifest_path.read_text())
    job = AlignedChainJob.model_validate(payload["job"])
    if payload.get("manifest_hash") != job.manifest_hash:
        raise RuntimeError("aligned-chain manifest hash mismatch")
    if job.protocol.profile != "production":
        raise RuntimeError("equilibration recovery requires a production aligned-chain job")
    return job


def recover_equilibration_analysis(
    *,
    manifest_path: Path,
    auto_md_dir: Path,
    output_dir: Path | None = None,
) -> Path:
    """Run RadonPy's strict convergence check without rerunning completed MD."""

    job = _manifest_job(manifest_path)
    root = manifest_path.parent
    run_dir = root / "preparation" / job.preparation_job.id
    checkpoint = run_dir / "analyze" / ".polymer_lab_checkpoints" / "eq3.json"
    if not checkpoint.is_file():
        raise RuntimeError("completed eq3 checkpoint is required for analysis-only recovery")
    checkpoint_payload = json.loads(checkpoint.read_text())
    if checkpoint_payload.get("stage") != "eq3":
        raise RuntimeError("invalid eq3 checkpoint identity")

    sources = {
        "eq3_log": run_dir / "eq3.log",
        "eq3_rg": run_dir / "rg3.profile",
        "eq3_trajectory": run_dir / "eq3.xtc",
        "eq3_data": run_dir / "eq3.data",
        "eq3_final_data": run_dir / "eq3_last.data",
        "topology": run_dir / "eq1.pdb",
        "checkpoint": checkpoint,
    }
    missing = [str(path) for path in sources.values() if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"completed equilibration artifacts are missing: {missing}")

    output_dir = output_dir or root / "preparation" / "convergence-recovery-v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "convergence-report.json"
    if report_path.exists():
        existing = json.loads(report_path.read_text())
        current_checksums = {name: file_sha256(path) for name, path in sources.items()}
        if (
            existing.get("aligned_manifest_hash") == job.manifest_hash
            and existing.get("source_checksums") == current_checksums
        ):
            return report_path
        raise RuntimeError("existing convergence report does not match immutable source artifacts")

    versions = _require_science_stack(auto_md_dir)
    _require_declared_versions(job.preparation_job, versions)
    try:
        versions["mdtraj"] = importlib.metadata.version("mdtraj")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("analysis-only recovery requires MDTraj") from exc

    from radonpy.sim.preset import eq

    versions["radonpy_eq_analyzer_sha256"] = file_sha256(Path(inspect.getfile(eq)))
    versions["polymer_lab_radonpy_analysis_sha256"] = file_sha256(Path(__file__))
    analyzer = eq.Equilibration_analyze(
        log_file=str(sources["eq3_log"]),
        traj_file=str(sources["eq3_trajectory"]),
        pdb_file=str(sources["topology"]),
        dat_file=str(sources["eq3_data"]),
        rg_file=str(sources["eq3_rg"]),
    )

    strict_dir = output_dir / "strict-thermo-rg"
    strict_properties = analyzer.get_all_prop(
        temp=job.protocol.temperature_k,
        press=job.protocol.transverse_pressure_atm,
        width=2000,
        init=2000,
        f_width=2000,
        save=True,
        save_name=str(strict_dir),
        do_traj=False,
    )
    strict_log = io.StringIO()
    with contextlib.redirect_stdout(strict_log), contextlib.redirect_stderr(strict_log):
        radonpy_converged = bool(analyzer.check_eq())
    (output_dir / "radonpy-check.log").write_text(strict_log.getvalue())

    trajectory = analyzer.read_traj()
    if trajectory is None:
        raise RuntimeError("RadonPy could not load the completed equilibration trajectory")
    trajectory_init, trajectory_width = adaptive_trajectory_window(trajectory.n_frames)
    charges = analyzer.get_partial_charges()
    trajectory_dir = output_dir / "adaptive-trajectory"
    r2, r2_data = analyzer.analyze_traj(
        trajectory,
        "r2",
        ylabel="<R2> [nm^2]",
        init=trajectory_init,
        width=trajectory_width,
        printout=False,
        save=str(trajectory_dir),
        temp=job.protocol.temperature_k,
        charges=charges,
    )
    dielectric, dielectric_data = analyzer.analyze_traj(
        trajectory,
        "dielectric",
        ylabel="Static dielectric constant",
        init=trajectory_init,
        width=trajectory_width,
        printout=False,
        save=str(trajectory_dir),
        temp=job.protocol.temperature_k,
        charges=charges,
    )
    nematic, nematic_data = analyzer.analyze_traj(
        trajectory,
        "order_param",
        ylabel="Nematic order parameter",
        init=trajectory_init,
        width=trajectory_width,
        printout=False,
        save=str(trajectory_dir),
    )
    trajectory_properties = {
        "r2": _compact_diagnostics(r2_data),
        "static_dielectric_constant": _compact_diagnostics(dielectric_data),
        "nematic_order_parameter": _compact_diagnostics(nematic_data),
    }
    source_checksums = {name: file_sha256(path) for name, path in sources.items()}
    generated_checksums = {
        str(path.relative_to(output_dir)): file_sha256(path)
        for path in output_dir.rglob("*")
        if path.is_file() and path != report_path
    }
    report = {
        "schema_version": 2,
        "job_id": job.id,
        "campaign_id": job.campaign_id,
        "candidate_id": job.candidate.id,
        "design_hash": job.candidate.design_hash,
        "aligned_manifest_hash": job.manifest_hash,
        "preparation_manifest_hash": job.preparation_job.manifest_hash,
        "protocol_hash": job.protocol.protocol_hash,
        "analysis_mode": "completed-md-analysis-only",
        "scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "md_rerun": False,
        "convergence_authority": (
            "radonpy.sim.preset.eq.Equilibration_analyze.check_eq defaults"
        ),
        "strict_thermo_rg_window_samples": 2000,
        "thermo_sample_count": len(analyzer.dfs[-1]),
        "trajectory_frame_count": trajectory.n_frames,
        "trajectory_init_frame": trajectory_init,
        "trajectory_window_frames": trajectory_width,
        "radonpy_full_convergence": radonpy_converged,
        "strict_properties": strict_properties,
        "strict_convergence_metrics": analyzer.conv_df.iloc[0].to_dict(),
        "trajectory_properties": trajectory_properties,
        "trajectory_fields_omitted_from_report": {
            "nematic_order_parameter": ["director"],
        },
        "trajectory_series_lengths": {
            "r2": len(r2),
            "dielectric": len(dielectric),
            "nematic_order_parameter": len(nematic),
        },
        "software_versions": versions,
        "source_checksums": source_checksums,
        "generated_artifact_checksums": generated_checksums,
        "admissible_as_scientific_evidence": False,
        "scientific_observations_emitted": False,
        "next_action": (
            "prepare the converged cell for aligned-chain production"
            if radonpy_converged
            else "review strict convergence failures before approving additional equilibration"
        ),
    }
    report_path.write_text(json.dumps(_json_value(report), indent=2, sort_keys=True) + "\n")
    return report_path
