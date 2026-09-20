#!/usr/bin/env python3
"""Apply a predeclared crystalline-PE reference gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymer_lab.pe_reference import PEReferenceProtocol, summarize_pe_reference, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--protocol-version",
        choices=("pe-airebo-m-reference-v1", "pe-airebo-m-reference-v2"),
        default="pe-airebo-m-reference-v1",
    )
    args = parser.parse_args()
    seeds = (104729, 130363, 155921, 177013) if args.protocol_version.endswith("v2") else (104729, 130363, 155921)
    report = summarize_pe_reference(
        args.root.resolve(), seeds=seeds, protocol=PEReferenceProtocol(version=args.protocol_version)
    )
    destination = args.root.resolve() / "reference-report.json"
    write_json(destination, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
