#!/usr/bin/env python3
"""Run one restartable crystalline-PE AIREBO-M reference replicate."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from polymer_lab.pe_reference import (
    PECrystalStructure,
    PEReferenceProtocol,
    analyze_pe_reference_replicate,
    file_sha256,
    generate_pe_crystal_data,
    render_pe_reference_inputs,
    write_json,
)

EXPECTED_POTENTIAL_SHA256 = "fd5bda23807ad3e342def4bd2c80049a9f3bf6dde36fcbed0b5c91d2d4fd86b4"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lammps", type=Path, required=True)
    parser.add_argument("--mpiexec", type=Path, required=True)
    parser.add_argument("--mpi-ranks", type=int, default=8)
    parser.add_argument("--potential", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--protocol-version",
        choices=("pe-airebo-m-reference-v1", "pe-airebo-m-reference-v2"),
        default="pe-airebo-m-reference-v1",
    )
    args = parser.parse_args()
    if args.seed <= 0 or args.mpi_ranks < 1:
        parser.error("seed and MPI rank count must be positive")
    for path in (args.lammps, args.mpiexec, args.potential):
        if not path.is_file():
            raise RuntimeError(f"required executable/input does not exist: {path}")
    if file_sha256(args.potential) != EXPECTED_POTENTIAL_SHA256:
        raise RuntimeError("pinned CH.airebo-m checksum mismatch")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    structure = PECrystalStructure()
    protocol = PEReferenceProtocol(version=args.protocol_version)
    data_path = output / "pe-crystal.data"
    structure_report = generate_pe_crystal_data(data_path, structure)
    inputs = render_pe_reference_inputs(
        output=output,
        data_path=data_path,
        potential_path=args.potential,
        seed=args.seed,
        protocol=protocol,
    )
    write_json(output / "structure.json", {**structure.model_dump(mode="json"), **structure_report})
    write_json(
        output / "protocol.json",
        {
            **protocol.model_dump(mode="json"),
            "protocol_hash": protocol.protocol_hash,
            "seed": args.seed,
            "lammps_commit": "9e42b6f0f2c68a092d5847d4127a053dc50e126a",
            "potential_sha256": EXPECTED_POTENTIAL_SHA256,
            "admissible_as_candidate_measurement": False,
        },
    )

    stage_order = ("00_minimize", "01_ramp", "02_stability", "03_tensile")
    for stage in stage_order:
        marker = output / f"{stage}.complete"
        if marker.is_file():
            continue
        command = [
            str(args.mpiexec),
            "-n",
            str(args.mpi_ranks),
            str(args.lammps),
            "-in",
            str(inputs[f"{stage}.in"]),
            "-log",
            str(output / f"{stage}.log"),
        ]
        stdout_path = output / f"{stage}.stdout"
        with stdout_path.open("wb") as stdout:
            completed = subprocess.run(command, stdout=stdout, stderr=subprocess.STDOUT, check=False)
        log_text = (output / f"{stage}.log").read_text(errors="replace")
        if completed.returncode or "ERROR:" in log_text or "Loop time" not in log_text:
            raise RuntimeError(f"LAMMPS stage {stage} failed; see {stdout_path}")
        marker.write_text(json.dumps({"stage": stage, "returncode": 0, "command": command}) + "\n")

    result = analyze_pe_reference_replicate(
        output=output,
        seed=args.seed,
        structure=structure,
        protocol=protocol,
    )
    (output / "replicate-result.json").write_text(result.model_dump_json(indent=2) + "\n")
    print(result.model_dump_json(indent=2))
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
