#!/usr/bin/env python3
"""Write the immutable architecture-aware fiber-v1 discovery plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymer_lab.fiber_discovery import write_fiber_discovery_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=Path("runs/fiber-v1/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/fiber-v1/discovery-v2"))
    args = parser.parse_args()
    plan = write_fiber_discovery_plan(args.campaign.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                "plan_id": plan.plan_id,
                "parent_campaign_id": plan.parent_campaign_id,
                "candidate_count": len(plan.candidates),
                "priority_order": list(plan.priority_order),
                "scientific_status": plan.scientific_status,
                "plan": str(args.output.resolve() / "plan.json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
