"""Aligned-chain LAMMPS protocol, analysis, and immutable job contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .fiber import FiberCandidate, FiberMeasurement, FiberProperty, FiberStage
from .models import FrozenModel, PhysicsJob, Provenance, stable_hash, utc_now

ATM_TO_GPA = 0.000101325


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AlignedChainProtocol(FrozenModel):
    version: Literal["aligned-chain-v1", "aligned-chain-v2"] = "aligned-chain-v2"
    profile: Literal["protocol_validation", "production"] = "protocol_validation"
    draw_axis: Literal["z"] = "z"
    draw_ratio: float = Field(default=2.0, gt=1, le=10)
    draw_true_strain_rate_s: float = Field(default=5.0e9, gt=0)
    temperature_k: float = Field(default=300.0, gt=0)
    transverse_pressure_atm: float = Field(default=1.0, gt=0)
    timestep_fs: float = Field(default=1.0, gt=0, le=2.0)
    thermostat_damping_fs: float = Field(default=100.0, gt=0)
    barostat_damping_fs: float = Field(default=1000.0, gt=0)
    constrain_hydrogen_bonds: bool = True
    constraint_tolerance: float = Field(default=1.0e-4, gt=0)
    constraint_iterations: int = Field(default=1000, ge=1)
    relaxation_steps: int = Field(default=50_000, ge=1)
    tensile_true_strain_rate_s: float = Field(default=5.0e9, gt=0)
    tensile_max_true_strain: float = Field(default=0.05, gt=0, le=0.30)
    sample_every_steps: int = Field(default=500, ge=1)
    restart_every_steps: int = Field(default=25_000, ge=1)
    random_seed: int = Field(default=1, ge=1)
    mpi_ranks: int = Field(default=16, ge=1)
    minimum_modulus_fit_r2: float = Field(default=0.90, ge=0, le=1)
    maximum_temperature_deviation_fraction: float = Field(default=0.10, gt=0, le=0.5)
    maximum_mean_transverse_pressure_deviation_atm: float = Field(default=250.0, gt=0)
    minimum_orientation_gain: float = Field(default=0.05, ge=0, le=1.5)
    minimum_tensile_samples: int = Field(default=20, ge=10)

    @property
    def draw_steps(self) -> int:
        rate_per_fs = self.draw_true_strain_rate_s / 1.0e15
        return math.ceil(math.log(self.draw_ratio) / (rate_per_fs * self.timestep_fs))

    @property
    def tensile_steps(self) -> int:
        rate_per_fs = self.tensile_true_strain_rate_s / 1.0e15
        return math.ceil(self.tensile_max_true_strain / (rate_per_fs * self.timestep_fs))

    @property
    def protocol_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def coherent_output_intervals(self) -> AlignedChainProtocol:
        shortest = min(self.draw_steps, self.relaxation_steps, self.tensile_steps)
        if self.sample_every_steps > shortest:
            raise ValueError("sampling interval cannot exceed the shortest protocol phase")
        if self.restart_every_steps > max(self.draw_steps, self.relaxation_steps, self.tensile_steps):
            raise ValueError("restart interval exceeds every protocol phase")
        return self


class AlignedChainJob(FrozenModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    candidate: FiberCandidate
    preparation_job: PhysicsJob
    protocol: AlignedChainProtocol
    artifact_uri: str
    estimated_core_hours: float = Field(gt=0)
    approved_by: str = Field(min_length=1)
    approval_rationale: str = Field(min_length=1)
    state: Literal["approved"] = "approved"
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def manifest_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def matching_campaign_and_chemistry(self) -> AlignedChainJob:
        if self.preparation_job.campaign_id != self.campaign_id:
            raise ValueError("preparation job must belong to the fiber campaign")
        representations = {
            item.representation
            for item in self.candidate.chemistry.constituents
            if item.representation_type == "psmiles"
        }
        if self.preparation_job.candidate.psmiles not in representations:
            raise ValueError("preparation PSMILES does not match the fiber candidate chemistry")
        if (
            "aligned_preparation_source" in self.preparation_job.spec.extra
            and self.protocol.profile != "protocol_validation"
        ):
            raise ValueError("a reused diagnostic preparation cannot be attached to a production job")
        return self


class AlignedChainMetrics(FrozenModel):
    axial_modulus_gpa: float
    modulus_fit_r2: float = Field(ge=0, le=1)
    peak_axial_stress_gpa: float
    peak_stress_true_strain: float = Field(ge=0)
    final_true_strain: float = Field(ge=0)
    mean_temperature_k: float = Field(gt=0)
    mean_transverse_pressure_atm: float
    hermans_orientation_before: float = Field(ge=-0.5, le=1)
    hermans_orientation_after_draw: float = Field(ge=-0.5, le=1)
    nonaffine_chain_slip_fraction: float = Field(ge=0)
    sample_count: int = Field(ge=1)


class AlignedChainResult(FrozenModel):
    schema_version: Literal[1] = 1
    job_id: str
    campaign_id: str
    candidate_id: str
    design_hash: str
    protocol_hash: str
    profile: Literal["protocol_validation", "production"]
    converged: bool
    admissible_as_scientific_evidence: bool
    metrics: AlignedChainMetrics
    measurements: tuple[FiberMeasurement, ...] = ()
    software_versions: dict[str, str]
    artifact_checksums: dict[str, str]
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def pilot_cannot_emit_measurements(self) -> AlignedChainResult:
        if self.profile == "protocol_validation" and (
            self.admissible_as_scientific_evidence or self.measurements
        ):
            raise ValueError("protocol-validation output cannot be scientific evidence")
        if self.admissible_as_scientific_evidence and not self.converged:
            raise ValueError("unconverged aligned-chain output cannot be admitted")
        return self


class AlignedPreparationCriteria(FrozenModel):
    """Stationarity requirements for a non-scientific aligned-protocol pilot."""

    version: Literal["aligned-preparation-stationarity-v1"] = "aligned-preparation-stationarity-v1"
    analysis_window_steps: int = Field(default=3_000_000, ge=1000)
    minimum_final_step: int = Field(default=5_000_000, ge=1000)
    minimum_samples: int = Field(default=2500, ge=30)
    maximum_temperature_deviation_fraction: float = Field(default=0.02, gt=0)
    minimum_density_g_cm3: float = Field(default=0.5, gt=0)
    maximum_density_g_cm3: float = Field(default=1.5, gt=0)
    maximum_density_block_drift_fraction: float = Field(default=0.005, gt=0)
    maximum_total_energy_block_drift_fraction: float = Field(default=0.01, gt=0)
    maximum_potential_energy_block_drift_fraction: float = Field(default=0.05, gt=0)
    maximum_mean_pressure_deviation_atm: float = Field(default=500.0, gt=0)
    maximum_ensemble_rg_block_drift_fraction: float = Field(default=0.02, gt=0)
    maximum_chain_rg_block_drift_fraction: float = Field(default=0.05, gt=0)

    @property
    def criteria_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class AlignedPreparationReport(FrozenModel):
    criteria_hash: str
    equilibration_stage: int = Field(ge=3)
    sample_count: int = Field(ge=1)
    rg_sample_count: int = Field(ge=1)
    analysis_start_step: int = Field(ge=0)
    final_step: int = Field(ge=0)
    rg_final_step: int = Field(ge=0)
    mean_temperature_k: float = Field(gt=0)
    temperature_deviation_fraction: float = Field(ge=0)
    mean_pressure_atm: float
    pressure_deviation_atm: float = Field(ge=0)
    mean_density_g_cm3: float = Field(gt=0)
    density_block_drift_fraction: float = Field(ge=0)
    total_energy_block_drift_fraction: float = Field(ge=0)
    potential_energy_block_drift_fraction: float = Field(ge=0)
    ensemble_rg_block_drift_fraction: float = Field(ge=0)
    maximum_chain_rg_block_drift_fraction: float = Field(ge=0)
    passed: bool
    failed_checks: tuple[str, ...] = ()


def final_equilibration_files(run_dir: Path) -> tuple[int, Path, Path, Path, Path]:
    """Return data, input, log, and Rg trace from the actual final RadonPy EQ stage."""

    matches: list[tuple[int, Path]] = []
    pattern = re.compile(r"^eq(\d+)_last\.data$")
    for path in run_dir.glob("eq*_last.data"):
        match = pattern.match(path.name)
        if match:
            matches.append((int(match.group(1)), path))
    if not matches:
        raise ValueError(f"no completed RadonPy sampling data found in {run_dir}")
    stage, data = max(matches, key=lambda item: item[0])
    if stage < 3:
        raise ValueError("RadonPy preparation did not complete a sampling stage")
    required = (run_dir / f"eq{stage}.in", run_dir / f"eq{stage}.log", run_dir / f"rg{stage}.profile")
    missing = [str(path) for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise ValueError(f"final RadonPy equilibration stage is incomplete: {missing}")
    return stage, data, required[0], required[1], required[2]


def _thermo_rows(path: Path) -> list[tuple[float, ...]]:
    rows: dict[int, tuple[float, ...]] = {}
    for raw_line in path.read_text(errors="replace").splitlines():
        fields = raw_line.split()
        if len(fields) != 28:
            continue
        try:
            values = tuple(float(value) for value in fields)
        except ValueError:
            continue
        if all(math.isfinite(value) for value in values):
            rows[int(values[0])] = values
    return [rows[step] for step in sorted(rows)]


def _rg_rows(path: Path) -> list[tuple[int, tuple[float, ...]]]:
    lines = path.read_text(errors="replace").splitlines()
    rows: dict[int, tuple[float, ...]] = {}
    index = 0
    while index < len(lines):
        fields = lines[index].split()
        if len(fields) != 2 or not all(field.isdigit() for field in fields):
            index += 1
            continue
        step, count = (int(field) for field in fields)
        values: list[float] = []
        for line in lines[index + 1 : index + 1 + count]:
            item = line.split()
            if len(item) != 2:
                raise ValueError(f"malformed radius-of-gyration profile: {path}")
            values.append(float(item[1]))
        if len(values) != count or not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError(f"invalid radius-of-gyration values: {path}")
        rows[step] = tuple(values)
        index += count + 1
    return [(step, rows[step]) for step in sorted(rows)]


def _three_blocks(values: list[float]) -> tuple[list[float], list[float], list[float]]:
    if len(values) < 3:
        raise ValueError("stationarity analysis requires at least three samples")
    cut1 = len(values) // 3
    cut2 = 2 * len(values) // 3
    return values[:cut1], values[cut1:cut2], values[cut2:]


def _relative_block_drift(values: list[float]) -> float:
    first, _, last = _three_blocks(values)
    mean_value = statistics.fmean(values)
    denominator = max(abs(mean_value), 1.0e-12)
    return abs(statistics.fmean(last) - statistics.fmean(first)) / denominator


def analyze_aligned_preparation(
    *,
    stage: int,
    log_path: Path,
    rg_path: Path,
    temperature_k: float,
    pressure_atm: float,
    criteria: AlignedPreparationCriteria | None = None,
) -> AlignedPreparationReport:
    """Check block stationarity for a diagnostic draw-protocol starting cell."""

    criteria = criteria or AlignedPreparationCriteria()
    rows = _thermo_rows(log_path)
    if not rows:
        raise ValueError(f"equilibration log contains no finite thermo rows: {log_path}")
    final_step = int(rows[-1][0])
    start_step = max(0, final_step - criteria.analysis_window_steps)
    window = [row for row in rows if row[0] >= start_step]
    rg_window = [item for item in _rg_rows(rg_path) if item[0] >= start_step]
    if not rg_window:
        raise ValueError("equilibration Rg trace has no samples in the analysis window")
    chain_count = len(rg_window[0][1])
    if chain_count < 1 or any(len(values) != chain_count for _, values in rg_window):
        raise ValueError("equilibration Rg trace has inconsistent chain counts")

    temperatures = [row[2] for row in window]
    pressures = [row[3] for row in window]
    total_energies = [row[5] for row in window]
    potential_energies = [row[7] for row in window]
    densities = [row[20] for row in window]
    ensemble_rg = [statistics.fmean(values) for _, values in rg_window]
    chain_rg = [[values[index] for _, values in rg_window] for index in range(chain_count)]
    mean_temperature = statistics.fmean(temperatures)
    mean_pressure = statistics.fmean(pressures)
    mean_density = statistics.fmean(densities)
    metrics = {
        "sample_count": len(window),
        "temperature_deviation_fraction": abs(mean_temperature - temperature_k) / temperature_k,
        "pressure_deviation_atm": abs(mean_pressure - pressure_atm),
        "density_block_drift_fraction": _relative_block_drift(densities),
        "total_energy_block_drift_fraction": _relative_block_drift(total_energies),
        "potential_energy_block_drift_fraction": _relative_block_drift(potential_energies),
        "ensemble_rg_block_drift_fraction": _relative_block_drift(ensemble_rg),
        "maximum_chain_rg_block_drift_fraction": max(_relative_block_drift(values) for values in chain_rg),
    }
    failed: list[str] = []
    if final_step < criteria.minimum_final_step:
        failed.append("minimum_final_step")
    if metrics["sample_count"] < criteria.minimum_samples:
        failed.append("minimum_samples")
    if len(rg_window) < criteria.minimum_samples:
        failed.append("minimum_rg_samples")
    if rg_window[-1][0] != final_step:
        failed.append("thermo_rg_final_step_mismatch")
    if metrics["temperature_deviation_fraction"] > criteria.maximum_temperature_deviation_fraction:
        failed.append("temperature_deviation")
    if not criteria.minimum_density_g_cm3 <= mean_density <= criteria.maximum_density_g_cm3:
        failed.append("density_range")
    for metric_name, maximum in (
        ("density_block_drift_fraction", criteria.maximum_density_block_drift_fraction),
        ("total_energy_block_drift_fraction", criteria.maximum_total_energy_block_drift_fraction),
        ("potential_energy_block_drift_fraction", criteria.maximum_potential_energy_block_drift_fraction),
        ("pressure_deviation_atm", criteria.maximum_mean_pressure_deviation_atm),
        ("ensemble_rg_block_drift_fraction", criteria.maximum_ensemble_rg_block_drift_fraction),
        ("maximum_chain_rg_block_drift_fraction", criteria.maximum_chain_rg_block_drift_fraction),
    ):
        if metrics[metric_name] > maximum:
            failed.append(metric_name)
    return AlignedPreparationReport(
        criteria_hash=criteria.criteria_hash,
        equilibration_stage=stage,
        sample_count=int(metrics["sample_count"]),
        rg_sample_count=len(rg_window),
        analysis_start_step=start_step,
        final_step=final_step,
        rg_final_step=rg_window[-1][0],
        mean_temperature_k=mean_temperature,
        temperature_deviation_fraction=metrics["temperature_deviation_fraction"],
        mean_pressure_atm=mean_pressure,
        pressure_deviation_atm=metrics["pressure_deviation_atm"],
        mean_density_g_cm3=mean_density,
        density_block_drift_fraction=metrics["density_block_drift_fraction"],
        total_energy_block_drift_fraction=metrics["total_energy_block_drift_fraction"],
        potential_energy_block_drift_fraction=metrics["potential_energy_block_drift_fraction"],
        ensemble_rg_block_drift_fraction=metrics["ensemble_rg_block_drift_fraction"],
        maximum_chain_rg_block_drift_fraction=metrics["maximum_chain_rg_block_drift_fraction"],
        passed=not failed,
        failed_checks=tuple(failed),
    )


def _read_verified_result(job: AlignedChainJob, result_path: Path) -> AlignedChainResult:
    result = AlignedChainResult.model_validate_json(result_path.read_text())
    expected_identity = {
        "job_id": job.id,
        "campaign_id": job.campaign_id,
        "candidate_id": job.candidate.id,
        "design_hash": job.candidate.design_hash,
        "protocol_hash": job.protocol.protocol_hash,
        "profile": job.protocol.profile,
    }
    mismatches = {
        field: {"expected": expected, "observed": getattr(result, field)}
        for field, expected in expected_identity.items()
        if getattr(result, field) != expected
    }
    if mismatches:
        raise ValueError(f"aligned-chain result identity mismatch: {mismatches}")
    required_software = {"radonpy", "rdkit", "psi4", "lammps"}
    missing_software = {
        name
        for name in required_software
        if result.software_versions.get(name, "").strip().lower() in {"", "missing", "unknown"}
    }
    if missing_software:
        raise ValueError(f"aligned-chain result lacks software identity: {sorted(missing_software)}")
    output_dir = result_path.parent / "aligned"
    for relative_name, expected_digest in result.artifact_checksums.items():
        artifact = output_dir / relative_name
        if not artifact.is_file() or file_sha256(artifact) != expected_digest:
            raise ValueError(f"aligned-chain artifact checksum mismatch: {relative_name}")
    return result


def read_aligned_diagnostic_result(job: AlignedChainJob, result_path: Path) -> AlignedChainResult:
    """Verify a pilot result without treating its numerical output as evidence."""

    result = _read_verified_result(job, result_path)
    if result.profile != "protocol_validation":
        raise ValueError("diagnostic reader requires a protocol-validation result")
    if result.admissible_as_scientific_evidence or result.measurements:
        raise ValueError("diagnostic result attempted to emit scientific measurements")
    return result


def read_aligned_result(job: AlignedChainJob, result_path: Path) -> AlignedChainResult:
    """Validate identity, scientific profile, software, and raw-artifact integrity."""

    result = _read_verified_result(job, result_path)
    if result.profile != "production":
        raise ValueError("protocol-validation results are diagnostic and cannot be admitted")
    if not result.converged or not result.admissible_as_scientific_evidence:
        raise ValueError("aligned-chain result failed convergence/admission gates")
    required_properties = {
        FiberProperty.AXIAL_MODULUS,
        FiberProperty.YIELD_STRESS_PROXY,
        FiberProperty.CHAIN_ORIENTATION,
        FiberProperty.CHAIN_SLIP,
    }
    observed_properties = [measurement.property for measurement in result.measurements]
    if set(observed_properties) != required_properties or len(observed_properties) != len(required_properties):
        raise ValueError("aligned-chain result lacks one unique required measurement per property")
    return result


def write_aligned_manifest(job: AlignedChainJob, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "manifest_hash": job.manifest_hash,
        "job": job.model_dump(mode="json"),
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return destination


_PREAMBLE_COMMANDS = (
    "units ",
    "atom_style ",
    "boundary ",
    "bond_style ",
    "angle_style ",
    "dihedral_style ",
    "improper_style ",
    "pair_style ",
    "pair_modify ",
    "special_bonds ",
    "kspace_style ",
    "kspace_modify ",
    "dielectric ",
    "neighbor ",
    "neigh_modify ",
    "comm_modify ",
    "newton ",
)


def extract_forcefield_preamble(source_input: str) -> tuple[str, ...]:
    """Extract only declarative force-field setup from a reviewed RadonPy input."""

    commands: list[str] = []
    for raw_line in source_input.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(_PREAMBLE_COMMANDS) and line not in commands:
            commands.append(line)
    required = {"units", "atom_style", "pair_style"}
    found = {line.split()[0] for line in commands}
    missing = required - found
    if missing:
        raise ValueError(f"source LAMMPS input lacks required setup commands: {sorted(missing)}")
    return tuple(commands)


def lammps_box_lengths(data_path: Path) -> tuple[float, float, float]:
    bounds: dict[str, tuple[float, float]] = {}
    pattern = re.compile(
        r"^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([xyz])lo\s+\3hi(?:\s|$)"
    )
    for line in data_path.read_text(errors="replace").splitlines()[:200]:
        match = pattern.match(line)
        if match:
            bounds[match.group(3)] = (float(match.group(1)), float(match.group(2)))
    if set(bounds) != {"x", "y", "z"}:
        raise ValueError(f"could not read orthogonal box bounds from {data_path}")
    return tuple(bounds[axis][1] - bounds[axis][0] for axis in ("x", "y", "z"))  # type: ignore[return-value]


def _read_command(source: Path, preamble: tuple[str, ...], *, restart: bool) -> list[str]:
    if restart:
        return [f"read_restart {source}"]
    return [*preamble, f"read_data {source}", "reset_timestep 0"]


def render_lammps_phase(
    *,
    phase: Literal["draw", "relax", "tensile"],
    source: Path,
    source_is_restart: bool,
    preamble: tuple[str, ...],
    destination: Path,
    protocol: AlignedChainProtocol,
    initial_lz: float,
) -> str:
    """Render one restartable phase of the aligned-chain protocol."""

    phase_steps = {
        "draw": protocol.draw_steps,
        "relax": protocol.relaxation_steps,
        "tensile": protocol.tensile_steps,
    }[phase]
    lines = [
        f"log {destination / f'{phase}.lammps.log'} append",
        *_read_command(source, preamble, restart=source_is_restart),
        f"timestep {protocol.timestep_fs:.12g}",
        f"thermo {protocol.sample_every_steps}",
        "thermo_modify flush yes",
        "thermo_style custom step temp press pxx pyy pzz density lx ly lz pe ke",
        *(
            (
                "fix constraints all shake "
                f"{protocol.constraint_tolerance:.12g} {protocol.constraint_iterations} 0 m 1.0",
            )
            if protocol.constrain_hydrogen_bonds
            else ()
        ),
        (
            "fix integrator all npt "
            f"temp {protocol.temperature_k:.12g} {protocol.temperature_k:.12g} "
            f"{protocol.thermostat_damping_fs:.12g} "
            f"x {protocol.transverse_pressure_atm:.12g} {protocol.transverse_pressure_atm:.12g} "
            f"{protocol.barostat_damping_fs:.12g} "
            f"y {protocol.transverse_pressure_atm:.12g} {protocol.transverse_pressure_atm:.12g} "
            f"{protocol.barostat_damping_fs:.12g} couple xy nreset 1000"
        ),
        f"restart {protocol.restart_every_steps} {destination / 'checkpoints' / f'{phase}.*.restart'}",
    ]
    if phase == "draw":
        lines.extend(
            (
                f"write_dump all custom {destination / 'pre_draw.dump'} id mol type xu yu zu modify sort id",
                (
                    "fix axial all deform 1 z trate "
                    f"{protocol.draw_true_strain_rate_s / 1.0e15:.12g} remap x units box"
                ),
            )
        )
    elif phase == "tensile":
        lines.extend(
            (
                f"variable initial_lz equal {initial_lz:.16g}",
                (
                    "variable true_strain equal ln(lz/v_initial_lz)"
                    if protocol.version == "aligned-chain-v2"
                    else "variable true_strain equal log(lz/v_initial_lz)"
                ),
                f"variable axial_stress equal -pzz*{ATM_TO_GPA:.12g}",
                "variable transverse_pressure equal 0.5*(pxx+pyy)",
                "variable sample_temp equal temp",
                "variable sample_lx equal lx",
                "variable sample_ly equal ly",
                "variable sample_lz equal lz",
                (
                    f"fix trace all ave/time {protocol.sample_every_steps} 1 {protocol.sample_every_steps} "
                    "v_true_strain v_axial_stress v_sample_temp v_transverse_pressure "
                    "v_sample_lx v_sample_ly v_sample_lz "
                    f"append {destination / 'stress_strain.dat'} ave one"
                ),
                (
                    "fix axial all deform 1 z trate "
                    f"{protocol.tensile_true_strain_rate_s / 1.0e15:.12g} remap x units box"
                ),
            )
        )
    lines.extend(
        (
            f"run {phase_steps} upto",
            "restart 0",
            f"write_restart {destination / f'{phase}.final.restart'}",
            f"write_data {destination / f'{phase}.data'}",
            (
                f"write_dump all custom {destination / f'{phase}_final.dump'} "
                "id mol type xu yu zu modify sort id"
            ),
            "quit",
            "",
        )
    )
    return "\n".join(lines)


def latest_restart(directory: Path, phase: str) -> Path | None:
    pattern = re.compile(rf"^{re.escape(phase)}\.(\d+)\.restart$")
    matches = [
        (int(match.group(1)), path)
        for path in directory.glob(f"{phase}.*.restart")
        if (match := pattern.match(path.name))
    ]
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def _linear_fit(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    count = len(points)
    mean_x = sum(item[0] for item in points) / count
    mean_y = sum(item[1] for item in points) / count
    variance = sum((item[0] - mean_x) ** 2 for item in points)
    if variance == 0:
        raise ValueError("stress-strain fit has zero strain variance")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance
    intercept = mean_y - slope * mean_x
    residual = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
    total = sum((y - mean_y) ** 2 for _, y in points)
    r2 = 1.0 if total == 0 and residual == 0 else 1.0 - residual / total if total else 0.0
    return slope, intercept, max(0.0, min(1.0, r2))


def analyze_stress_strain(path: Path) -> dict[str, float | int]:
    rows: dict[int, tuple[float, ...]] = {}
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 8:
                continue
            values = tuple(float(value) for value in fields)
            if all(math.isfinite(value) for value in values):
                rows[int(values[0])] = values[1:]
    ordered = [rows[step] for step in sorted(rows)]
    if len(ordered) < 10:
        raise ValueError("stress-strain trace has fewer than ten finite samples")
    if any(right[0] <= left[0] for left, right in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("true strain is not strictly increasing")
    baseline_rows = [row for row in ordered if row[0] <= 0.002]
    baseline = sum(row[1] for row in baseline_rows) / max(1, len(baseline_rows))
    corrected = [(row[0], row[1] - baseline) for row in ordered]
    fit_points = [(strain, stress) for strain, stress in corrected if 0.002 <= strain <= 0.01]
    if len(fit_points) < 3:
        raise ValueError("stress-strain trace lacks three samples in the 0.2-1% modulus window")
    slope, _, r2 = _linear_fit(fit_points)
    peak_strain, peak_stress = max(corrected, key=lambda item: item[1])
    tail = ordered[len(ordered) // 2 :]
    return {
        "axial_modulus_gpa": slope,
        "modulus_fit_r2": r2,
        "peak_axial_stress_gpa": peak_stress,
        "peak_stress_true_strain": peak_strain,
        "final_true_strain": ordered[-1][0],
        "mean_temperature_k": sum(row[2] for row in tail) / len(tail),
        "mean_transverse_pressure_atm": sum(row[3] for row in tail) / len(tail),
        "sample_count": len(ordered),
    }


def _read_dump(path: Path) -> tuple[tuple[float, float, float], dict[int, list[tuple[float, float, float]]]]:
    lines = path.read_text().splitlines()
    snapshots: list[tuple[tuple[float, float, float], dict[int, list[tuple[float, float, float]]]]] = []
    index = 0
    while index < len(lines):
        if lines[index] != "ITEM: TIMESTEP":
            index += 1
            continue
        atom_count = int(lines[index + 3])
        bounds_header = lines[index + 4]
        if not bounds_header.startswith("ITEM: BOX BOUNDS"):
            raise ValueError(f"unsupported dump box in {path}")
        bounds = [tuple(float(value) for value in lines[index + offset].split()[:2]) for offset in (5, 6, 7)]
        atom_header = lines[index + 8].split()[2:]
        column = {name: position for position, name in enumerate(atom_header)}
        required = {"mol", "xu", "yu", "zu"}
        if not required <= set(column):
            raise ValueError(f"dump lacks molecule/unwrapped coordinates: {path}")
        molecules: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
        for line in lines[index + 9 : index + 9 + atom_count]:
            fields = line.split()
            molecule = int(fields[column["mol"]])
            molecules[molecule].append(
                tuple(float(fields[column[axis]]) for axis in ("xu", "yu", "zu"))  # type: ignore[arg-type]
            )
        lengths = tuple(high - low for low, high in bounds)
        snapshots.append((lengths, dict(molecules)))  # type: ignore[arg-type]
        index += 9 + atom_count
    if not snapshots:
        raise ValueError(f"dump contains no snapshots: {path}")
    return snapshots[-1]


def chain_orientation_and_slip(before: Path, after: Path) -> tuple[float, float, float]:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - worker dependency guard
        raise RuntimeError("aligned-chain analysis requires numpy") from exc
    before_lengths, before_molecules = _read_dump(before)
    after_lengths, after_molecules = _read_dump(after)
    shared = sorted(set(before_molecules) & set(after_molecules))
    if not shared:
        raise ValueError("draw snapshots share no molecule identifiers")

    def orientation(molecules: dict[int, list[tuple[float, float, float]]]) -> float:
        values: list[float] = []
        for molecule in shared:
            coordinates = np.asarray(molecules[molecule], dtype=float)
            centered = coordinates - coordinates.mean(axis=0)
            covariance = centered.T @ centered / max(1, len(centered))
            _, vectors = np.linalg.eigh(covariance)
            cosine = abs(float(vectors[2, -1]))
            values.append(0.5 * (3.0 * cosine**2 - 1.0))
        return sum(values) / len(values)

    slip_values: list[float] = []
    for molecule in shared:
        before_com = np.asarray(before_molecules[molecule], dtype=float).mean(axis=0)
        after_com = np.asarray(after_molecules[molecule], dtype=float).mean(axis=0)
        before_fraction = before_com[2] / before_lengths[2]
        after_fraction = after_com[2] / after_lengths[2]
        delta = after_fraction - before_fraction
        delta -= round(delta)
        slip_values.append(float(delta))
    slip = math.sqrt(sum(value**2 for value in slip_values) / len(slip_values))
    return orientation(before_molecules), orientation(after_molecules), slip


def make_result(
    job: AlignedChainJob,
    *,
    output_dir: Path,
    software_versions: dict[str, str],
) -> AlignedChainResult:
    stress = analyze_stress_strain(output_dir / "stress_strain.dat")
    orientation_before, orientation_after, slip = chain_orientation_and_slip(
        output_dir / "pre_draw.dump",
        output_dir / "draw_final.dump",
    )
    metrics = AlignedChainMetrics(
        **stress,
        hermans_orientation_before=orientation_before,
        hermans_orientation_after_draw=orientation_after,
        nonaffine_chain_slip_fraction=slip,
    )
    checksums = {
        str(path.relative_to(output_dir)): file_sha256(path)
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "result.json"
    }
    warnings: list[str] = [
        "Classical-force-field aligned-cell results are screening evidence and cannot establish ultimate strength."
    ]
    temperature_ok = (
        abs(metrics.mean_temperature_k - job.protocol.temperature_k) / job.protocol.temperature_k
        <= job.protocol.maximum_temperature_deviation_fraction
    )
    strain_ok = metrics.final_true_strain >= job.protocol.tensile_max_true_strain * 0.98
    fit_ok = metrics.modulus_fit_r2 >= job.protocol.minimum_modulus_fit_r2 and metrics.axial_modulus_gpa > 0
    pressure_ok = (
        abs(metrics.mean_transverse_pressure_atm - job.protocol.transverse_pressure_atm)
        <= job.protocol.maximum_mean_transverse_pressure_deviation_atm
    )
    orientation_ok = (
        metrics.hermans_orientation_after_draw - metrics.hermans_orientation_before
        >= job.protocol.minimum_orientation_gain
    )
    sampling_ok = metrics.sample_count >= job.protocol.minimum_tensile_samples
    converged = temperature_ok and strain_ok and fit_ok and pressure_ok and orientation_ok and sampling_ok
    if not temperature_ok:
        warnings.append("mean tensile-stage temperature is outside the configured convergence band")
    if not strain_ok:
        warnings.append("tensile stage did not reach the configured true strain")
    if not fit_ok:
        warnings.append("small-strain modulus fit failed its positivity/R-squared gate")
    if not pressure_ok:
        warnings.append("mean transverse pressure is outside the configured convergence band")
    if not orientation_ok:
        warnings.append("drawing did not produce the configured minimum chain-orientation gain")
    if not sampling_ok:
        warnings.append("tensile trace has fewer than the configured minimum samples")
    scientific = job.protocol.profile == "production" and converged
    measurements: tuple[FiberMeasurement, ...] = ()
    if scientific:
        evidence = {
            "stress_strain.dat": checksums["stress_strain.dat"],
            "draw_final.dump": checksums["draw_final.dump"],
            "tensile_final.dump": checksums["tensile_final.dump"],
        }
        source = f"file://{output_dir / 'result.json'}"
        measurements = (
            FiberMeasurement(
                candidate_id=job.candidate.id,
                design_hash=job.candidate.design_hash,
                property=FiberProperty.AXIAL_MODULUS,
                value=metrics.axial_modulus_gpa,
                unit="GPa",
                provenance=Provenance.MD,
                stage=FiberStage.ALIGNED_CHAIN,
                protocol_hash=job.protocol.protocol_hash,
                source_reference=source,
                artifact_checksums=evidence,
                metadata={"draw_ratio": job.protocol.draw_ratio, "fit_r2": metrics.modulus_fit_r2},
            ),
            FiberMeasurement(
                candidate_id=job.candidate.id,
                design_hash=job.candidate.design_hash,
                property=FiberProperty.YIELD_STRESS_PROXY,
                value=metrics.peak_axial_stress_gpa,
                unit="GPa",
                provenance=Provenance.MD,
                stage=FiberStage.ALIGNED_CHAIN,
                protocol_hash=job.protocol.protocol_hash,
                source_reference=source,
                artifact_checksums=evidence,
                metadata={
                    "draw_ratio": job.protocol.draw_ratio,
                    "peak_stress_true_strain": metrics.peak_stress_true_strain,
                },
            ),
            FiberMeasurement(
                candidate_id=job.candidate.id,
                design_hash=job.candidate.design_hash,
                property=FiberProperty.CHAIN_ORIENTATION,
                value=metrics.hermans_orientation_after_draw,
                unit="ratio",
                provenance=Provenance.MD,
                stage=FiberStage.ALIGNED_CHAIN,
                protocol_hash=job.protocol.protocol_hash,
                source_reference=source,
                artifact_checksums=evidence,
                metadata={"before_draw": metrics.hermans_orientation_before},
            ),
            FiberMeasurement(
                candidate_id=job.candidate.id,
                design_hash=job.candidate.design_hash,
                property=FiberProperty.CHAIN_SLIP,
                value=metrics.nonaffine_chain_slip_fraction,
                unit="fractional_box_length",
                provenance=Provenance.MD,
                stage=FiberStage.ALIGNED_CHAIN,
                protocol_hash=job.protocol.protocol_hash,
                source_reference=source,
                artifact_checksums=evidence,
            ),
        )
    return AlignedChainResult(
        job_id=job.id,
        campaign_id=job.campaign_id,
        candidate_id=job.candidate.id,
        design_hash=job.candidate.design_hash,
        protocol_hash=job.protocol.protocol_hash,
        profile=job.protocol.profile,
        converged=converged,
        admissible_as_scientific_evidence=scientific,
        metrics=metrics,
        measurements=measurements,
        software_versions=software_versions,
        artifact_checksums=checksums,
        warnings=tuple(warnings),
    )
