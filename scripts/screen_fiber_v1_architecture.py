#!/usr/bin/env python3
"""Record Fiber v1 mechanical bounds and a frozen lab test candidate."""

from __future__ import annotations

import json
from pathlib import Path

from polymer_lab.fiber_feasibility import screen_bimodal_lead, zone_draw_test_plan


def main() -> None:
    root = Path("runs/fiber-v1/discovery-v3")
    root.mkdir(parents=True, exist_ok=True)
    for filename, payload in (
        ("architecture-screen-v2.json", screen_bimodal_lead()),
        ("zone-draw-test-candidate.json", zone_draw_test_plan()),
    ):
        destination = root / filename
        destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(destination)


if __name__ == "__main__":
    main()
