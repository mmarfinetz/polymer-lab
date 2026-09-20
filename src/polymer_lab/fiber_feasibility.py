"""Physics-based bounds and a reproducible Fiber v1 laboratory test point."""

from __future__ import annotations

import math
from typing import Any

from .fiber import (
    FiberChemistry,
    FiberConstituent,
    FiberMaterialFamily,
    FiberProcess,
    FiberRole,
    SpinningMethod,
    make_fiber_candidate,
)

ACS_OMEGA_2024 = "https://doi.org/10.1021/acsomega.3c09230"
KIST_ZONE_DRAW_1996 = "https://pubs.kist.re.kr/handle/201004/144249"
PARAFFIN_GEL_SPIN_1986 = "https://citeseerx.ist.psu.edu/document?doi=b78f189de926fd0c87e2d80e19853415bd2342be&repid=rep1&type=pdf"


def bundle_area_fraction(filaments: int, filament_um: float, bundle_mm: float) -> float:
    if filaments <= 0 or filament_um <= 0 or bundle_mm <= 0:
        raise ValueError("all bundle dimensions must be positive")
    return filaments * (filament_um / (bundle_mm * 1000)) ** 2


def outer_helix_path_factor(bundle_mm: float, twist_turns_per_m: float) -> float:
    radius_m = bundle_mm / 2000
    return math.hypot(1.0, 2 * math.pi * radius_m * twist_turns_per_m)


def screen_bimodal_lead() -> dict[str, Any]:
    """Use favorable published fiber limits to bound the old 75/25 design.

    A rectangular stress envelope maximizes possible work for the assumed
    constituent strengths and strains. The result is a conditional rejection,
    not a measurement of this exact bundle.
    """
    packing = bundle_area_fraction(3200, 20, 1.3)
    path_factor = outer_helix_path_factor(1.3, 25)
    high_break_global = path_factor * 1.03 - 1
    high_fraction, bridge_fraction = 0.75, 0.25
    high_strength_gpa, bridge_strength_gpa = 3.50, 0.26
    maximum_peak_gpa = packing * (
        high_fraction * high_strength_gpa + bridge_fraction * bridge_strength_gpa
    )
    # Intentionally generous: full peak stress is sustained from zero strain
    # until failure, with no twist, defects, friction, or stress-transfer loss.
    maximum_work_mj_m3 = 1000 * packing * (
        high_fraction * high_strength_gpa * high_break_global
        + bridge_fraction * bridge_strength_gpa * 0.15
    )
    return {
        "candidate_id": "fiber-9ee296fee9e08765",
        "status": "conditional_screening_rejection",
        "reference_scenario": {
            "high_draw_strength_gpa": high_strength_gpa,
            "high_draw_break_strain": 0.03,
            "lower_draw_strength_gpa": bridge_strength_gpa,
            "lower_draw_assumed_survival_strain": 0.15,
            "source": ACS_OMEGA_2024,
        },
        "geometric_area_fraction": packing,
        "maximum_outer_filament_path_factor": path_factor,
        "high_draw_global_break_strain_upper_scenario": high_break_global,
        "peak_bundle_stress_upper_scenario_gpa": maximum_peak_gpa,
        "work_to_15_percent_strain_upper_scenario_mj_m3": maximum_work_mj_m3,
        "target_toughness_mj_m3": 100,
        "decision": "do_not_prioritize_75_25_bundle_for_fiber_v1_target",
        "interpretation": (
            "Under the cited constituent scenario even a rectangular stress envelope cannot "
            "reach 100 MJ/m3. Matching bundle tests could overturn the scenario."
        ),
        "admissible_as_candidate_measurement": False,
    }


def zone_draw_test_candidate(draw_ratio: float = 24.5):
    """Freeze one fabricable process point beside a published 26.4x control."""
    if draw_ratio not in {24.5, 25.5, 26.4}:
        raise ValueError("draw ratio must belong to the predeclared laboratory matrix")
    return make_fiber_candidate(
        name=f"uhmwpe-zone-draw-{str(draw_ratio).replace('.', 'p')}-bundle-doe-001",
        chemistry=FiberChemistry(
            constituents=(
                FiberConstituent(
                    name="linear ultra-high-molecular-weight polyethylene",
                    material_family=FiberMaterialFamily.UHMWPE,
                    role=FiberRole.LOAD_BEARING_CORE,
                    mass_fraction=1.0,
                    representation="[*]CC[*]",
                    representation_type="psmiles",
                    evidence_basis="known PE repeat; Mn/Mw are procurement specifications",
                ),
            ),
            number_average_molecular_weight_g_mol=1_500_000,
            weight_average_molecular_weight_g_mol=3_000_000,
        ),
        process=FiberProcess(
            spinning_method=SpinningMethod.GEL,
            dope_concentration_mass_fraction=0.05,
            solvent_or_buffer="paraffin oil",
            coagulation_or_trigger="room-temperature quench; n-hexane extraction; dry before zone draw",
            spinning_temperature_c=170,
            draw_ratio=draw_ratio,
            zone_draw_temperature_c=128,
            zone_draw_stress_mpa=20,
            heat_band_speed_mm_min=1,
            filament_diameter_um=20,
            filament_count=3200,
            twist_turns_per_m=25,
            bundle_diameter_mm=1.25,
            core_mass_fraction=1.0,
            sheath_mass_fraction=0.0,
        ),
        hypothesis_basis=(
            "A published 5 wt% gel-spun UHMWPE zone-draw point achieved 2.63 GPa and 12.75% strain at 26.4x. "
            f"{draw_ratio}x is a preregistered experiment for the strength-strain tradeoff."
        ),
        assumptions=(
            f"The {draw_ratio}x specimen from this exact formulation has no measured strength, "
            "strain, toughness, or fatigue life.",
            "The paraffin-oil/170C spinning route and the 1996 zone-draw result come "
            "from different studies; this combination must be tested.",
            "20 um and 1.25 mm are fabrication targets to verify by microscopy.",
            "The 25 turns/m bundle twist is a starting setpoint; matched bundle testing "
            "determines whether it is acceptable.",
            "No interphase is included until measured slip or bundle efficiency warrants it.",
        ),
        source_references=(KIST_ZONE_DRAW_1996, PARAFFIN_GEL_SPIN_1986),
        generation=2,
        parent_ids=("fiber-9ee296fee9e08765",),
    )


def zone_draw_test_plan() -> dict[str, Any]:
    candidate = zone_draw_test_candidate()
    packing = bundle_area_fraction(3200, 20, 1.25)
    path_factor = outer_helix_path_factor(1.25, 25)
    required_filament_strength = 2.0 * path_factor / packing
    return {
        "candidate": candidate.model_dump(mode="json"),
        "control_candidates": [
            zone_draw_test_candidate(draw_ratio).model_dump(mode="json")
            for draw_ratio in (25.5, 26.4)
        ],
        "readiness": "ready_for_controlled_laboratory_test",
        "production_qualified": False,
        "published_near_target_observation": {
            "zone_draw_ratio": 26.4,
            "strength_gpa": 2.63,
            "strain_at_break_fraction": 0.1275,
            "modulus_gpa": 43.3,
            "heat_band_speed_mm_min": 1,
            "temperature_c": 128,
            "drawing_stress_mpa": 20,
            "source": KIST_ZONE_DRAW_1996,
            "same_as_candidate": False,
        },
        "geometry": {
            "filament_area_fraction": packing,
            "outer_helix_path_factor": path_factor,
            "ideal_filament_strength_needed_for_2_gpa_bundle_gpa": required_filament_strength,
            "interpretation": "Ideal load sharing only; observed bundle strength may be lower.",
        },
        "preregistered_draw_ratio_controls": [24.5, 25.5, 26.4],
        "replicates_per_setting": 5,
        "minimum_reported_data": [
            "raw single-filament force-extension curves",
            "measured filament diameter and density",
            "raw 3200-filament bundle force-extension curves",
            "toughness by integrating actual stress-strain curves",
            "failure strain, knot efficiency, creep, and 10000-cycle fatigue",
            "-20C, room-temperature humid-air, and 80C testing",
            "resin molecular-weight distribution and residual-solvent assay",
        ],
        "go_no_go": {
            "bundle_tensile_strength_gpa_min": 2.0,
            "bundle_break_strain_fraction_min": 0.15,
            "bundle_break_strain_fraction_max": 0.40,
            "bundle_toughness_mj_m3_strictly_above": 100,
            "density_g_cm3_strictly_below": 1.3,
            "knot_efficiency_strictly_above": 0.60,
            "fatigue_cycles_strictly_above": 10_000,
        },
        "interphase_rule": (
            "Add a separately specified interphase only after measured bundle load-transfer "
            "or slip failure, then assign a new candidate ID."
        ),
        "candidate_specific_measurements": [],
    }
