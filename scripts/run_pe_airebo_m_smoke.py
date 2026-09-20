#!/usr/bin/env python3
"""Run a checksum-pinned, non-scientific LAMMPS AIREBO-M capability test."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

EXPECTED_HASHES = {
    "potential": "fd5bda23807ad3e342def4bd2c80049a9f3bf6dde36fcbed0b5c91d2d4fd86b4",
    "data": "a69042d92930445633dba338f54d65e41f68017835a5f750de74da04f5772fd6",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lammps", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--potential", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    paths = {
        "lammps": args.lammps.resolve(),
        "input": args.input.resolve(),
        "data": args.data.resolve(),
        "potential": args.potential.resolve(),
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"AIREBO-M smoke test is missing files: {missing}")
    checksums = {name: file_sha256(path) for name, path in paths.items() if name != "lammps"}
    for name, expected in EXPECTED_HASHES.items():
        if checksums[name] != expected:
            raise RuntimeError(f"pinned {name} checksum mismatch")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stdout_path = output / "lammps.stdout"
    log_path = output / "log.lammps"
    command = [
        str(paths["lammps"]),
        "-in",
        str(paths["input"]),
        "-log",
        str(log_path),
        "-var",
        "data_file",
        str(paths["data"]),
        "-var",
        "potential_file",
        str(paths["potential"]),
    ]
    with stdout_path.open("wb") as stdout:
        completed = subprocess.run(command, stdout=stdout, stderr=subprocess.STDOUT, check=False)
    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    passed = completed.returncode == 0 and "Loop time" in log_text and "ERROR:" not in log_text
    result = {
        "schema_version": 1,
        "test": "lammps-airebo-m-polyethylene-capability",
        "passed": passed,
        "returncode": completed.returncode,
        "command": command,
        "checksums": {
            **checksums,
            "lammps_stdout": file_sha256(stdout_path),
            "lammps_log": file_sha256(log_path) if log_path.exists() else None,
        },
        "pinned_lammps_commit": "9e42b6f0f2c68a092d5847d4127a053dc50e126a",
        "admissible_as_scientific_evidence": False,
        "scientific_observations_emitted": False,
        "next_action": (
            "implement and validate a crystalline-PE reference protocol"
            if passed
            else "repair the AIREBO-M environment before any candidate compute"
        ),
    }
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not passed:
        raise RuntimeError("LAMMPS AIREBO-M capability smoke test failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
