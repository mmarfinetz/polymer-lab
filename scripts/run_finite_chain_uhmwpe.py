#!/usr/bin/env python3
"""Run a capped short-chain PE reference with stage restarts and force readout."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
from pathlib import Path

from polymer_lab.finite_chain import generate_finite_chain_data, write_finite_chain_protocol
from polymer_lab.pe_reference import file_sha256, parse_lammps_thermo

EXPECTED_POTENTIAL_SHA256 = "fd5bda23807ad3e342def4bd2c80049a9f3bf6dde36fcbed0b5c91d2d4fd86b4"


def _input_stages(
    output: Path, data: Path, potential: Path, seed: int, structure: dict, smoke: bool
) -> dict[str, str]:
    minimum, ramp, stability, tensile = (
        (2_000, 5_000, 10_000, 5_000)
        if smoke else (20_000, 125_000, 250_000, 75_000)
    )
    common = "units metal\natom_style molecular\nboundary p p f\n"
    force_field = (
        "newton on\n"
        "pair_style airebo/morse 3.0\n"
        f"pair_coeff * * {potential.resolve()} C H\n"
        "neighbor 2.0 bin\n"
        "neigh_modify delay 0 every 1 check yes\n"
        "timestep 0.0002\n"
    )
    bottom = " ".join(map(str, structure["bottom_atom_ids"]))
    top = " ".join(map(str, structure["top_atom_ids"]))
    return {
        "00_minimize": (
            common + f"read_data {data}\n" + force_field
            + "thermo 100\nmin_style fire\n"
            + f"minimize 1.0e-6 1.0e-8 {minimum} {minimum * 10}\n"
            + f"write_restart {output / '00.restart'}\n"
        ),
        "01_ramp": (
            common + f"read_restart {output / '00.restart'}\n" + force_field
            + f"velocity all create 30 {seed} mom yes rot yes dist gaussian\n"
            + "fix integrator all npt temp 30 300 0.1 x 0 0 0.5 y 0 0 0.5 couple xy\n"
            + "thermo 500\nthermo_style custom step temp lx ly lz pxx pyy pzz\n"
            + f"run {ramp}\nwrite_restart {output / '01.restart'}\n"
        ),
        "02_stability": (
            common + f"read_restart {output / '01.restart'}\n" + force_field
            + "fix integrator all npt temp 300 300 0.1 x 0 0 0.5 y 0 0 0.5 couple xy\n"
            + "thermo 500\nthermo_style custom step temp lx ly lz pxx pyy pzz\n"
            + f"run {stability}\nwrite_restart {output / '02.restart'}\n"
        ),
        "03_pull": (
            common + f"read_restart {output / '02.restart'}\n" + force_field
            + f"group bottom id {bottom}\n"
            + f"group top id {top}\n"
            + "group mobile subtract all bottom top\n"
            + "velocity bottom set 0 0 0\nvelocity top set 0 0 0\n"
            + "compute bottom_com bottom com\ncompute top_com top com\n"
            + "compute top_force top reduce sum fz\n"
            + "compute mobile_temp mobile temp\n"
            + "run 0\n"
            + "variable initial_gauge equal $(c_top_com[3]-c_bottom_com[3])\n"
            + "variable end_strain equal (c_top_com[3]-c_bottom_com[3]-v_initial_gauge)/v_initial_gauge\n"
            + "variable reaction_gpa equal -c_top_force*160.21766208/(lx*ly)\n"
            + "fix bottom_hold bottom setforce 0 0 0\n"
            + "fix top_pull top move linear 0 0 0.08 units box\n"
            + "fix mobile_nvt mobile nvt temp 300 300 0.1\n"
            + "thermo_modify temp mobile_temp\n"
            + "thermo 50\n"
            + "thermo_style custom step temp v_end_strain v_reaction_gpa c_top_force lx ly lz\n"
            + f"run {tensile}\nwrite_restart {output / '03.restart'}\n"
        ),
    }


def _analyze(output: Path, seed: int, structure: dict, smoke: bool) -> dict:
    stability = parse_lammps_thermo(
        output / "02_stability.log", ("Step", "Temp", "Lx", "Ly", "Lz", "Pxx", "Pyy", "Pzz")
    )
    pull = parse_lammps_thermo(
        output / "03_pull.log",
        ("Step", "Temp", "v_end_strain", "v_reaction_gpa", "c_top_force", "Lx", "Ly", "Lz"),
    )
    tail = stability[len(stability) // 2 :]
    mean_temperature = statistics.fmean(row["Temp"] for row in tail)
    maximum_strain = max(row["v_end_strain"] for row in pull)
    maximum_reaction = max(row["v_reaction_gpa"] for row in pull)
    failed = []
    if abs(mean_temperature - 300) / 300 > 0.05:
        failed.append("stability_temperature")
    if len(stability) < (20 if smoke else 450):
        failed.append("stability_samples")
    if len(pull) < (100 if smoke else 1_000):
        failed.append("pull_samples")
    if maximum_strain < (0.001 if smoke else 0.01):
        failed.append("end_to_end_strain")
    if not math.isfinite(maximum_reaction):
        failed.append("reaction_force")
    artifacts = {
        path.name: file_sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name not in {"result.json"}
    }
    return {
        "version": "capped-pe-chain-end-reference-v2",
        "seed": seed, "smoke": smoke,
        "passed": not failed,
        "failed_checks": failed,
        "mean_stability_temperature_k": mean_temperature,
        "maximum_end_to_end_strain": maximum_strain,
        "maximum_reaction_stress_gpa_at_md_rate": maximum_reaction,
        "stability_sample_count": len(stability),
        "pull_sample_count": len(pull),
        "structure": {key: value for key, value in structure.items() if key not in {"bottom_atom_ids", "top_atom_ids"}},
        "artifact_checksums": artifacts,
        "scientific_scope": "C32 PE oligomer defect reference under fast pull; not UHMWPE fiber strength",
        "admissible_as_candidate_measurement": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lammps", type=Path, required=True)
    parser.add_argument("--mpiexec", type=Path, required=True)
    parser.add_argument("--potential", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--mpi-ranks", type=int, default=8)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.seed <= 0 or args.mpi_ranks < 1:
        parser.error("seed and MPI ranks must be positive")
    for path in (args.lammps, args.mpiexec, args.potential):
        if not path.is_file():
            raise RuntimeError(f"missing executable/input: {path}")
    if file_sha256(args.potential) != EXPECTED_POTENTIAL_SHA256:
        raise RuntimeError("pinned CH.airebo-m checksum mismatch")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = output / "finite-chain.data"
    structure = generate_finite_chain_data(data)
    write_finite_chain_protocol(output / "protocol.json", args.seed, args.smoke)
    stages = _input_stages(output, data, args.potential, args.seed, structure, args.smoke)
    for stage, body in stages.items():
        input_path = output / f"{stage}.in"
        input_path.write_text(body)
        marker = output / f"{stage}.complete"
        if marker.exists():
            continue
        log = output / f"{stage}.log"
        command = [
            str(args.mpiexec), "-n", str(args.mpi_ranks), str(args.lammps),
            "-in", str(input_path), "-log", str(log),
        ]
        with (output / f"{stage}.stdout").open("wb") as stdout:
            completed = subprocess.run(command, stdout=stdout, stderr=subprocess.STDOUT, check=False)
        log_text = log.read_text(errors="replace") if log.exists() else ""
        if completed.returncode or "ERROR:" in log_text or "Loop time" not in log_text:
            failure = {"status": "failed", "stage": stage, "returncode": completed.returncode,
                       "admissible_as_candidate_measurement": False}
            (output / "result.json").write_text(json.dumps(failure, indent=2) + "\n")
            raise RuntimeError(f"LAMMPS stage {stage} failed; inspect {stage}.stdout and .log")
        marker.write_text(json.dumps({"stage": stage, "command": command}) + "\n")
    result = _analyze(output, args.seed, structure, args.smoke)
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "artifact_checksums"}, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
