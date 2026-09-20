"""Crystalline-polyethylene AIREBO-M reference construction and analysis.

This module validates a simulation backend against a known component crystal.  Its
outputs are deliberately not candidate measurements and cannot qualify Fiber v1.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .models import FrozenModel, stable_hash

AMU_PER_ANGSTROM3_TO_G_CM3 = 1.66053906660
CARBON_MASS_AMU = 12.011
HYDROGEN_MASS_AMU = 1.008


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PECrystalStructure(FrozenModel):
    """Published 300 K orthorhombic PE structure used as the reference cell."""

    version: Literal["orthorhombic-pe-300k-v1"] = "orthorhombic-pe-300k-v1"
    phase: Literal["orthorhombic"] = "orthorhombic"
    space_group: Literal["Pnam"] = "Pnam"
    source_doi: Literal["10.3390/polym15020465"] = "10.3390/polym15020465"
    coordinate_compilation_doi: Literal["10.1021/acsomega.8b00506"] = (
        "10.1021/acsomega.8b00506"
    )
    temperature_k: float = 300.0
    lattice_a_angstrom: float = 7.417
    lattice_b_angstrom: float = 4.939
    lattice_c_angstrom: float = 2.550
    carbon_xy: tuple[float, float] = (0.040, 0.061)
    hydrogen_1_xy: tuple[float, float] = (0.185, 0.023)
    hydrogen_2_xy: tuple[float, float] = (0.015, 0.278)
    replicate_a: int = Field(default=4, ge=2)
    replicate_b: int = Field(default=6, ge=2)
    replicate_c: int = Field(default=12, ge=2)

    @property
    def unit_cell_density_g_cm3(self) -> float:
        mass_amu = 4 * CARBON_MASS_AMU + 8 * HYDROGEN_MASS_AMU
        volume_angstrom3 = (
            self.lattice_a_angstrom * self.lattice_b_angstrom * self.lattice_c_angstrom
        )
        return mass_amu / volume_angstrom3 * AMU_PER_ANGSTROM3_TO_G_CM3

    @property
    def atom_count(self) -> int:
        return 12 * self.replicate_a * self.replicate_b * self.replicate_c

    @property
    def structure_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def box_must_exceed_twice_airebo_cutoff(self) -> PECrystalStructure:
        # CH.airebo-m uses sigma_CC=3.4 A and the documented 3.0-sigma cutoff.
        minimum_length = 2 * 3.0 * 3.4
        lengths = (
            self.replicate_a * self.lattice_a_angstrom,
            self.replicate_b * self.lattice_b_angstrom,
            self.replicate_c * self.lattice_c_angstrom,
        )
        if min(lengths) <= minimum_length:
            raise ValueError("PE reference box must exceed twice the AIREBO-M cutoff")
        return self


class PEReferenceProtocol(FrozenModel):
    """Predeclared conditions and admission criteria for one reference replicate."""

    version: Literal["pe-airebo-m-reference-v1", "pe-airebo-m-reference-v2"] = "pe-airebo-m-reference-v1"
    temperature_k: float = 300.0
    pressure_bar: float = 0.0
    timestep_fs: float = 0.2
    ramp_start_temperature_k: float = 30.0
    ramp_steps: int = 125_000
    stability_steps: int = 250_000
    tensile_steps: int = 75_000
    tensile_engineering_strain_rate_s: float = 2.0e9
    sample_every_steps: int = 500
    tensile_sample_every_steps: int = 50
    thermostat_damping_ps: float = 0.1
    barostat_damping_ps: float = 0.5
    modulus_fit_min_strain: float = 0.002
    modulus_fit_max_strain: float = 0.010
    minimum_stability_samples: int = 450
    minimum_tensile_samples: int = 1_000
    maximum_temperature_error_fraction: float = 0.02
    maximum_density_error_fraction: float = 0.10
    maximum_lattice_error_fraction: float = 0.08
    maximum_density_block_drift_fraction: float = 0.01
    minimum_axial_modulus_gpa: float = 180.0
    maximum_axial_modulus_gpa: float = 360.0
    minimum_modulus_fit_r2: float = 0.98
    maximum_replicate_modulus_cv: float = 0.10

    @property
    def strain_increment_per_step(self) -> float:
        return self.tensile_engineering_strain_rate_s * self.timestep_fs * 1.0e-15

    @property
    def maximum_engineering_strain(self) -> float:
        return self.tensile_steps * self.strain_increment_per_step

    @property
    def protocol_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def validate_sampling_and_strain(self) -> PEReferenceProtocol:
        if self.maximum_engineering_strain < self.modulus_fit_max_strain * 2:
            raise ValueError("tensile phase is too short for the declared modulus fit")
        if self.stability_steps // self.sample_every_steps < self.minimum_stability_samples:
            raise ValueError("stability phase cannot emit the required sample count")
        if self.tensile_steps // self.tensile_sample_every_steps < self.minimum_tensile_samples:
            raise ValueError("tensile phase cannot emit the required sample count")
        return self


class PEReferenceReplicateResult(FrozenModel):
    schema_version: Literal[1] = 1
    test: Literal["crystalline-pe-airebo-m-reference"] = "crystalline-pe-airebo-m-reference"
    seed: int
    passed: bool
    completed_stages: tuple[str, ...]
    structure_hash: str
    protocol_hash: str
    mean_temperature_k: float
    mean_density_g_cm3: float
    mean_lattice_a_angstrom: float
    mean_lattice_b_angstrom: float
    mean_lattice_c_angstrom: float
    density_error_fraction: float
    maximum_lattice_error_fraction: float
    density_block_drift_fraction: float
    axial_modulus_gpa: float
    modulus_fit_r2: float
    maximum_sampled_stress_gpa: float
    maximum_sampled_engineering_strain: float
    stability_sample_count: int
    tensile_sample_count: int
    failed_checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    artifact_checksums: dict[str, str]
    admissible_as_candidate_measurement: Literal[False] = False
    scientific_observations_emitted: Literal[False] = False


def _wyckoff_positions(x: float, y: float) -> tuple[tuple[float, float, float], ...]:
    """Pnam 4c positions in the axis convention reported for PE."""

    return (
        (x % 1.0, (-y) % 1.0, 0.25),
        ((-x) % 1.0, y % 1.0, 0.75),
        ((-x + 0.5) % 1.0, (-y + 0.5) % 1.0, 0.75),
        ((x + 0.5) % 1.0, (y + 0.5) % 1.0, 0.25),
    )


def generate_pe_crystal_data(path: Path, structure: PECrystalStructure | None = None) -> dict:
    """Write a periodic all-atom Pnam PE supercell as LAMMPS atomic data."""

    structure = structure or PECrystalStructure()
    sites = (
        (1, _wyckoff_positions(*structure.carbon_xy)),
        (2, _wyckoff_positions(*structure.hydrogen_1_xy)),
        (2, _wyckoff_positions(*structure.hydrogen_2_xy)),
    )
    atoms: list[tuple[int, float, float, float]] = []
    for ia in range(structure.replicate_a):
        for ib in range(structure.replicate_b):
            for ic in range(structure.replicate_c):
                for atom_type, positions in sites:
                    for fx, fy, fz in positions:
                        atoms.append(
                            (
                                atom_type,
                                (ia + fx) * structure.lattice_a_angstrom,
                                (ib + fy) * structure.lattice_b_angstrom,
                                (ic + fz) * structure.lattice_c_angstrom,
                            )
                        )
    if len(atoms) != structure.atom_count:
        raise RuntimeError("generated PE atom count does not match the declared supercell")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Orthorhombic polyethylene 300 K reference; not a Fiber v1 candidate measurement",
        "",
        f"{len(atoms)} atoms",
        "2 atom types",
        "",
        f"0.0 {structure.replicate_a * structure.lattice_a_angstrom:.12f} xlo xhi",
        f"0.0 {structure.replicate_b * structure.lattice_b_angstrom:.12f} ylo yhi",
        f"0.0 {structure.replicate_c * structure.lattice_c_angstrom:.12f} zlo zhi",
        "",
        "Masses",
        "",
        f"1 {CARBON_MASS_AMU}",
        f"2 {HYDROGEN_MASS_AMU}",
        "",
        "Atoms # atomic",
        "",
    ]
    lines.extend(
        f"{atom_id} {atom_type} {x:.12f} {y:.12f} {z:.12f}"
        for atom_id, (atom_type, x, y, z) in enumerate(atoms, start=1)
    )
    path.write_text("\n".join(lines) + "\n")
    carbon_count = sum(atom_type == 1 for atom_type, *_ in atoms)
    hydrogen_count = len(atoms) - carbon_count
    return {
        "structure_hash": structure.structure_hash,
        "atom_count": len(atoms),
        "carbon_count": carbon_count,
        "hydrogen_count": hydrogen_count,
        "box_lengths_angstrom": [
            structure.replicate_a * structure.lattice_a_angstrom,
            structure.replicate_b * structure.lattice_b_angstrom,
            structure.replicate_c * structure.lattice_c_angstrom,
        ],
        "reference_density_g_cm3": structure.unit_cell_density_g_cm3,
        "data_sha256": file_sha256(path),
    }


def render_pe_reference_inputs(
    *,
    output: Path,
    data_path: Path,
    potential_path: Path,
    seed: int,
    protocol: PEReferenceProtocol | None = None,
) -> dict[str, Path]:
    """Render four stage-boundary-restartable LAMMPS inputs."""

    protocol = protocol or PEReferenceProtocol()
    output.mkdir(parents=True, exist_ok=True)
    preamble = "\n".join(
        (
            "units metal",
            "atom_style atomic",
            "boundary p p p",
            "newton on",
            "pair_style airebo/morse 3.0",
            f"pair_coeff * * {potential_path.resolve()} C H",
            "neighbor 2.0 bin",
            "neigh_modify delay 0 every 1 check yes",
            f"timestep {protocol.timestep_fs / 1000.0:.10g}",
        )
    )
    stages = {
        "00_minimize.in": "\n".join(
            (
                "clear",
                "units metal",
                "atom_style atomic",
                "boundary p p p",
                f"read_data {data_path.resolve()}",
                preamble.split("boundary p p p\n", 1)[1],
                "thermo 100",
                "thermo_style custom step atoms temp press density lx ly lz pe etotal",
                "min_style fire",
                "minimize 1.0e-8 1.0e-10 20000 200000",
                f"write_restart {(output / '00_minimized.restart').resolve()}",
                f"write_data {(output / '00_minimized.data').resolve()}",
            )
        ),
        "01_ramp.in": "\n".join(
            (
                "clear",
                "units metal",
                "atom_style atomic",
                "boundary p p p",
                f"read_restart {(output / '00_minimized.restart').resolve()}",
                preamble.split("boundary p p p\n", 1)[1],
                f"velocity all create {protocol.ramp_start_temperature_k} {seed} mom yes rot yes dist gaussian",
                f"fix integrator all npt temp {protocol.ramp_start_temperature_k} {protocol.temperature_k} "
                f"{protocol.thermostat_damping_ps} aniso {protocol.pressure_bar} "
                f"{protocol.pressure_bar} {protocol.barostat_damping_ps}",
                "fix drift all momentum 100 linear 1 1 1",
                f"restart 50000 {(output / '01_ramp.*.restart').resolve()}",
                f"thermo {protocol.sample_every_steps}",
                "thermo_style custom step temp press density lx ly lz pe ke etotal pxx pyy pzz",
                f"run {protocol.ramp_steps}",
                f"write_restart {(output / '01_ramped.restart').resolve()}",
            )
        ),
        "02_stability.in": "\n".join(
            (
                "clear",
                "units metal",
                "atom_style atomic",
                "boundary p p p",
                f"read_restart {(output / '01_ramped.restart').resolve()}",
                preamble.split("boundary p p p\n", 1)[1],
                "reset_timestep 0",
                f"fix integrator all npt temp {protocol.temperature_k} {protocol.temperature_k} "
                f"{protocol.thermostat_damping_ps} aniso {protocol.pressure_bar} "
                f"{protocol.pressure_bar} {protocol.barostat_damping_ps}",
                "fix drift all momentum 100 linear 1 1 1",
                f"restart 50000 {(output / '02_stability.*.restart').resolve()}",
                f"thermo {protocol.sample_every_steps}",
                "thermo_style custom step temp press density lx ly lz pe ke etotal pxx pyy pzz",
                f"run {protocol.stability_steps}",
                f"write_restart {(output / '02_equilibrated.restart').resolve()}",
                f"write_data {(output / '02_equilibrated.data').resolve()}",
            )
        ),
        "03_tensile.in": "\n".join(
            (
                "clear",
                "units metal",
                "atom_style atomic",
                "boundary p p p",
                f"read_restart {(output / '02_equilibrated.restart').resolve()}",
                preamble.split("boundary p p p\n", 1)[1],
                "reset_timestep 0",
                "run 0",
                "variable initial_lz equal $(lz)",
                "variable engineering_strain equal (lz-v_initial_lz)/v_initial_lz",
                "variable true_strain equal log(lz/v_initial_lz)",
                "variable axial_gpa equal -pzz*0.0001",
                "variable transverse_bar equal (pxx+pyy)/2.0",
                f"fix integrator all npt temp {protocol.temperature_k} {protocol.temperature_k} "
                f"{protocol.thermostat_damping_ps} x {protocol.pressure_bar} "
                f"{protocol.pressure_bar} {protocol.barostat_damping_ps} y "
                f"{protocol.pressure_bar} {protocol.pressure_bar} "
                f"{protocol.barostat_damping_ps} couple xy",
                f"fix axial all deform 1 z erate {protocol.tensile_engineering_strain_rate_s / 1.0e12:.10g} "
                "remap x units box",
                f"restart 25000 {(output / '03_tensile.*.restart').resolve()}",
                f"thermo {protocol.tensile_sample_every_steps}",
                "thermo_style custom step v_engineering_strain v_true_strain v_axial_gpa "
                "temp density v_transverse_bar lx ly lz pxx pyy pzz pe etotal",
                f"run {protocol.tensile_steps}",
                f"write_restart {(output / '03_tensile_complete.restart').resolve()}",
            )
        ),
    }
    paths: dict[str, Path] = {}
    for filename, body in stages.items():
        path = output / filename
        path.write_text(body + "\n")
        paths[filename] = path
    return paths


def parse_lammps_thermo(path: Path, expected_header: tuple[str, ...]) -> list[dict[str, float]]:
    """Parse all finite thermo tables with an exact declared header."""

    rows: list[dict[str, float]] = []
    active = False
    for line in path.read_text(errors="replace").splitlines():
        fields = tuple(line.split())
        if fields == expected_header:
            active = True
            continue
        if not active:
            continue
        if len(fields) != len(expected_header):
            active = False
            continue
        try:
            values = tuple(float(value) for value in fields)
        except ValueError:
            active = False
            continue
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"non-finite thermo output in {path}")
        rows.append(dict(zip(expected_header, values, strict=True)))
    if not rows:
        raise ValueError(f"no matching thermo output in {path}")
    return rows


def _relative_block_drift(values: list[float]) -> float:
    cut = max(1, len(values) // 3)
    denominator = max(abs(statistics.fmean(values)), 1.0e-12)
    return abs(statistics.fmean(values[-cut:]) - statistics.fmean(values[:cut])) / denominator


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    if len(xs) < 3 or len(xs) != len(ys):
        raise ValueError("linear fit requires at least three paired samples")
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator <= 0:
        raise ValueError("linear fit has zero strain variance")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / denominator
    intercept = y_mean - slope * x_mean
    residual = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
    total = sum((y - y_mean) ** 2 for y in ys)
    r2 = 1.0 - residual / total if total > 0 else 1.0
    return slope, intercept, r2


def analyze_pe_reference_replicate(
    *,
    output: Path,
    seed: int,
    structure: PECrystalStructure | None = None,
    protocol: PEReferenceProtocol | None = None,
) -> PEReferenceReplicateResult:
    structure = structure or PECrystalStructure()
    protocol = protocol or PEReferenceProtocol()
    stage_names = ("00_minimize", "01_ramp", "02_stability", "03_tensile")
    completed = tuple(
        stage for stage in stage_names if (output / f"{stage}.complete").is_file()
    )
    if completed != stage_names:
        raise ValueError(f"reference replicate is incomplete: completed={completed}")
    stability_header = (
        "Step",
        "Temp",
        "Press",
        "Density",
        "Lx",
        "Ly",
        "Lz",
        "PotEng",
        "KinEng",
        "TotEng",
        "Pxx",
        "Pyy",
        "Pzz",
    )
    tensile_header = (
        "Step",
        "v_engineering_strain",
        "v_true_strain",
        "v_axial_gpa",
        "Temp",
        "Density",
        "v_transverse_bar",
        "Lx",
        "Ly",
        "Lz",
        "Pxx",
        "Pyy",
        "Pzz",
        "PotEng",
        "TotEng",
    )
    stability_rows = parse_lammps_thermo(output / "02_stability.log", stability_header)
    tensile_rows = parse_lammps_thermo(output / "03_tensile.log", tensile_header)
    stationary = stability_rows[len(stability_rows) // 2 :]
    temperatures = [row["Temp"] for row in stationary]
    densities = [row["Density"] for row in stationary]
    lattice_a = [row["Lx"] / structure.replicate_a for row in stationary]
    lattice_b = [row["Ly"] / structure.replicate_b for row in stationary]
    lattice_c = [row["Lz"] / structure.replicate_c for row in stationary]
    mean_temperature = statistics.fmean(temperatures)
    mean_density = statistics.fmean(densities)
    mean_lattice = (
        statistics.fmean(lattice_a),
        statistics.fmean(lattice_b),
        statistics.fmean(lattice_c),
    )
    lattice_errors = (
        abs(mean_lattice[0] - structure.lattice_a_angstrom) / structure.lattice_a_angstrom,
        abs(mean_lattice[1] - structure.lattice_b_angstrom) / structure.lattice_b_angstrom,
        abs(mean_lattice[2] - structure.lattice_c_angstrom) / structure.lattice_c_angstrom,
    )
    density_error = abs(mean_density - structure.unit_cell_density_g_cm3) / structure.unit_cell_density_g_cm3
    density_drift = _relative_block_drift(densities)
    fit_rows = [
        row
        for row in tensile_rows
        if protocol.modulus_fit_min_strain
        <= row["v_engineering_strain"]
        <= protocol.modulus_fit_max_strain
    ]
    modulus, _, modulus_r2 = _linear_fit(
        [row["v_engineering_strain"] for row in fit_rows],
        [row["v_axial_gpa"] for row in fit_rows],
    )
    failed: list[str] = []
    if len(stability_rows) < protocol.minimum_stability_samples:
        failed.append("minimum_stability_samples")
    if len(tensile_rows) < protocol.minimum_tensile_samples:
        failed.append("minimum_tensile_samples")
    if (
        abs(mean_temperature - protocol.temperature_k) / protocol.temperature_k
        > protocol.maximum_temperature_error_fraction
    ):
        failed.append("temperature")
    if density_error > protocol.maximum_density_error_fraction:
        failed.append("density")
    if max(lattice_errors) > protocol.maximum_lattice_error_fraction:
        failed.append("lattice")
    if density_drift > protocol.maximum_density_block_drift_fraction:
        failed.append("density_stationarity")
    if not protocol.minimum_axial_modulus_gpa <= modulus <= protocol.maximum_axial_modulus_gpa:
        failed.append("axial_modulus")
    if modulus_r2 < protocol.minimum_modulus_fit_r2:
        failed.append("modulus_fit_r2")
    artifacts = {
        path.name: file_sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name not in {"replicate-result.json"}
    }
    return PEReferenceReplicateResult(
        seed=seed,
        passed=not failed,
        completed_stages=completed,
        structure_hash=structure.structure_hash,
        protocol_hash=protocol.protocol_hash,
        mean_temperature_k=mean_temperature,
        mean_density_g_cm3=mean_density,
        mean_lattice_a_angstrom=mean_lattice[0],
        mean_lattice_b_angstrom=mean_lattice[1],
        mean_lattice_c_angstrom=mean_lattice[2],
        density_error_fraction=density_error,
        maximum_lattice_error_fraction=max(lattice_errors),
        density_block_drift_fraction=density_drift,
        axial_modulus_gpa=modulus,
        modulus_fit_r2=modulus_r2,
        maximum_sampled_stress_gpa=max(row["v_axial_gpa"] for row in tensile_rows),
        maximum_sampled_engineering_strain=max(row["v_engineering_strain"] for row in tensile_rows),
        stability_sample_count=len(stability_rows),
        tensile_sample_count=len(tensile_rows),
        failed_checks=tuple(failed),
        warnings=(
            "The 2e9 s^-1 MD strain rate is not quasi-static; do not report sampled peak stress as fiber strength.",
            "This validates a perfect-crystal component backend, not a semicrystalline Fiber v1 architecture.",
        ),
        artifact_checksums=artifacts,
    )


def summarize_pe_reference(
    root: Path,
    seeds: tuple[int, ...] = (104729, 130363, 155921),
    protocol: PEReferenceProtocol | None = None,
) -> dict:
    protocol = protocol or PEReferenceProtocol()
    if protocol.version == "pe-airebo-m-reference-v2" and seeds != (
        104729,
        130363,
        155921,
        177013,
    ):
        raise ValueError("v2 reference seeds must match the predeclared four-replicate list")
    results = [
        PEReferenceReplicateResult.model_validate_json((root / f"seed-{seed}" / "replicate-result.json").read_text())
        for seed in seeds
    ]
    moduli = [result.axial_modulus_gpa for result in results]
    modulus_mean = statistics.fmean(moduli)
    modulus_cv = statistics.pstdev(moduli) / abs(modulus_mean) if modulus_mean else math.inf
    hashes_match = all(
        result.structure_hash == PECrystalStructure().structure_hash
        and result.protocol_hash == protocol.protocol_hash
        and result.seed == seed
        for result, seed in zip(results, seeds, strict=True)
    )
    passed = (
        len(results) == len(seeds)
        and all(result.passed for result in results)
        and modulus_cv <= protocol.maximum_replicate_modulus_cv
        and hashes_match
    )
    return {
        "schema_version": 1,
        "test": f"{len(seeds)}-replicate-crystalline-pe-airebo-m-reference",
        "passed": passed,
        "replicate_seeds": list(seeds),
        "replicate_results": [result.model_dump(mode="json") for result in results],
        "axial_modulus_mean_gpa": modulus_mean,
        "axial_modulus_cv": modulus_cv,
        "maximum_allowed_modulus_cv": protocol.maximum_replicate_modulus_cv,
        "structure_and_protocol_hashes_match": hashes_match,
        "admissible_as_candidate_measurement": False,
        "scientific_observations_emitted": False,
        "decision": (
            "proceed_to_finite_chain_defect_reference"
            if passed
            else "repair_crystalline_pe_backend_before_candidate_compute"
        ),
        "limitations": [
            "Perfect periodic PE crystal only; no chain ends, tie molecules, amorphous phase, "
            "voids, or bundle interfaces.",
            "The MD strain rate is 2e9 s^-1 and cannot establish quasi-static tensile strength.",
            "No Fiber v1 candidate is validated or qualified by this report.",
        ],
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
