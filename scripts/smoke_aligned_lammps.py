#!/usr/bin/env python3
"""Run one timestep per aligned phase against an existing RadonPy cell."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from polymer_lab.aligned import (
    AlignedChainProtocol,
    extract_forcefield_preamble,
    lammps_box_lengths,
    render_lammps_phase,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--source-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lammps", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "checkpoints").mkdir(exist_ok=True)
    protocol = AlignedChainProtocol(
        draw_ratio=1.000004,
        draw_true_strain_rate_s=5e9,
        relaxation_steps=1,
        tensile_true_strain_rate_s=5e9,
        tensile_max_true_strain=0.000004,
        sample_every_steps=1,
        restart_every_steps=1,
        mpi_ranks=1,
        minimum_tensile_samples=10,
    )
    preamble = extract_forcefield_preamble(args.source_input.read_text())
    sources = {
        "draw": args.data,
        "relax": args.output / "draw.data",
        "tensile": args.output / "relax.data",
    }
    environment = {**os.environ, "OMP_NUM_THREADS": "1"}
    for phase in ("draw", "relax", "tensile"):
        source = sources[phase]
        input_path = args.output / f"{phase}.in"
        input_path.write_text(
            render_lammps_phase(
                phase=phase,  # type: ignore[arg-type]
                source=source,
                source_is_restart=False,
                preamble=preamble,
                destination=args.output,
                protocol=protocol,
                initial_lz=lammps_box_lengths(source)[2],
            )
        )
        with (args.output / f"{phase}.stdout").open("wb") as log:
            completed = subprocess.run(
                [str(args.lammps), "-in", str(input_path)],
                cwd=args.output,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if completed.returncode != 0:
            raise RuntimeError(f"aligned LAMMPS smoke phase {phase} failed")
    print(f"aligned LAMMPS syntax smoke passed: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
