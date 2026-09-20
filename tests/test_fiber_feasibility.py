import json
from pathlib import Path

from polymer_lab.fiber_feasibility import screen_bimodal_lead, zone_draw_test_plan


def test_old_bundle_is_weak_under_published_constituent_scenario():
    report = screen_bimodal_lead()
    assert report["work_to_15_percent_strain_upper_scenario_mj_m3"] < 100
    assert report["maximum_outer_filament_path_factor"] < 1.01
    assert report["admissible_as_candidate_measurement"] is False


def test_zone_draw_point_is_frozen_and_requires_real_bundle_tests():
    report = zone_draw_test_plan()
    protocol = json.loads(Path("configs/fiber-v1-zone-draw-test-v1.json").read_text())
    assert report["candidate"]["process"]["draw_ratio"] == 24.5
    assert report["candidate"]["process"]["zone_draw_temperature_c"] == 128
    assert report["candidate"]["process"]["zone_draw_stress_mpa"] == 20
    assert report["geometry"]["ideal_filament_strength_needed_for_2_gpa_bundle_gpa"] > 2.45
    assert report["candidate_specific_measurements"] == []
    assert report["production_qualified"] is False
    candidates = [report["candidate"], *report["control_candidates"]]
    assert [candidate["id"] for candidate in candidates] == [
        row["candidate_id"] for row in protocol["process_groups"]
    ]
    assert [candidate["design_hash"] for candidate in candidates] == [
        row["design_hash"] for row in protocol["process_groups"]
    ]
