#!/usr/bin/env python3
"""Recover strict RadonPy analysis from a checkpointed completed fiber equilibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymer_lab.radonpy_analysis import recover_equilibration_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--auto-md-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report_path = recover_equilibration_analysis(
        manifest_path=args.manifest.resolve(),
        auto_md_dir=args.auto_md_dir.resolve(),
        output_dir=args.output_dir.resolve() if args.output_dir else None,
    )
    print(json.dumps(json.loads(report_path.read_text()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
