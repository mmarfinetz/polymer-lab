"""Geometry-only Fiber v1 bundle screen; deliberately not a strength predictor."""
from __future__ import annotations

import math
from typing import Any


def screen_first_architecture() -> dict[str, Any]:
    filament_count, filament_diameter_um, bundle_diameter_mm = 3200, 20.0, 1.3
    filament_area = filament_count * math.pi * (filament_diameter_um / 2) ** 2
    bundle_area = math.pi * (bundle_diameter_mm * 1000 / 2) ** 2
    return {
        "candidate": "uhmwpe-bimodal-draw-bundle-doe-001",
        "status": "screening_only",
        "filament_count": filament_count,
        "filament_diameter_um": filament_diameter_um,
        "bundle_diameter_mm": bundle_diameter_mm,
        "geometric_area_fraction": filament_area / bundle_area,
        "interphase_decision": "defer_until_finite_chain_bundle_pullout",
        "requires_matching_bundle_experiment": True,
        "admissible_as_candidate_measurement": False,
        "scientific_observations_emitted": False,
    }
