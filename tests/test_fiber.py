from __future__ import annotations

import pytest

from polymer_lab.fiber import (
    FIBER_PROPERTY_UNITS,
    FiberArchitecture,
    FiberArchitectureTopology,
    FiberCandidate,
    FiberChemistry,
    FiberConstituent,
    FiberMaterialFamily,
    FiberMeasurement,
    FiberPopulation,
    FiberPopulationRole,
    FiberProcess,
    FiberProperty,
    FiberRole,
    FiberStage,
    SpinningMethod,
    assess_fiber_candidate,
    initialize_fiber_v1,
    make_fiber_candidate,
    summarize_fiber_v1,
)
from polymer_lab.fiber_discovery import make_fiber_discovery_plan
from polymer_lab.models import Provenance


def test_fiber_v1_initialization_is_idempotent_and_contains_no_claimed_result(tmp_path) -> None:
    first = initialize_fiber_v1(tmp_path, excluded_campaign_ids=("old-polystyrene",))
    second = initialize_fiber_v1(tmp_path, excluded_campaign_ids=("ignored-on-reload",))

    assert first == second
    assert first.name == "fiber-v1"
    assert first.excluded_campaign_ids == ("old-polystyrene",)
    assert all(candidate.status == "hypothesis" for candidate in first.candidates)
    assert [step.stage for step in first.evaluation_plan if step.implemented] == [
        FiberStage.THERMOPHYSICAL,
        FiberStage.ALIGNED_CHAIN,
    ]
    assert summarize_fiber_v1(tmp_path)["qualified_candidates"] == 0
    assert (tmp_path / "qualification.json").is_file()


def test_architecture_discovery_candidates_are_hypotheses_without_measurements(tmp_path) -> None:
    campaign = initialize_fiber_v1(tmp_path)
    plan = make_fiber_discovery_plan(campaign)

    assert len(plan.candidates) == 3
    assert plan.priority_order == tuple(candidate.id for candidate in plan.candidates)
    assert all(candidate.status == "hypothesis" for candidate in plan.candidates)
    assert all(candidate.architecture is not None for candidate in plan.candidates)
    assert "no candidate-specific properties" in plan.scientific_status
    assert campaign.candidates[0].design_hash == (
        "2ce891491668e51e906e8fee06489144cb9fd6082ec9468d5b9f2f52e6c26d40"
    )
    for candidate in plan.candidates:
        assert candidate.architecture is not None
        assert sum(item.mass_fraction for item in candidate.architecture.populations) == pytest.approx(1.0)


def test_fiber_architecture_rejects_incoherent_population_fractions() -> None:
    with pytest.raises(ValueError, match="must sum to one"):
        FiberArchitecture(
            topology=FiberArchitectureTopology.BIMODAL_PARALLEL_BUNDLE,
            populations=(
                FiberPopulation(
                    name="strength",
                    constituent_name="PE",
                    role=FiberPopulationRole.PRIMARY_LOAD_BEARING,
                    mass_fraction=0.8,
                    draw_ratio=100,
                ),
                FiberPopulation(
                    name="bridge",
                    constituent_name="PE",
                    role=FiberPopulationRole.DUCTILE_BRIDGE,
                    mass_fraction=0.1,
                    draw_ratio=10,
                ),
            ),
            assembly_description="test fixture",
        )


def _resolved_candidate() -> FiberCandidate:
    return make_fiber_candidate(
        name="resolved-test-fiber",
        chemistry=FiberChemistry(
            constituents=(
                FiberConstituent(
                    name="test core",
                    material_family=FiberMaterialFamily.UHMWPE,
                    role=FiberRole.LOAD_BEARING_CORE,
                    mass_fraction=1.0,
                    evidence_basis="test fixture",
                ),
            ),
            number_average_molecular_weight_g_mol=1_000_000,
        ),
        process=FiberProcess(
            spinning_method=SpinningMethod.GEL,
            dope_concentration_mass_fraction=0.1,
            solvent_or_buffer="test fixture",
            coagulation_or_trigger="test fixture",
            draw_ratio=10,
            crystallinity_fraction=0.8,
            filament_diameter_um=20,
            filament_count=2000,
            twist_turns_per_m=10,
            bundle_diameter_mm=1.0,
            core_mass_fraction=1.0,
            sheath_mass_fraction=0.0,
            anneal_under_tension=True,
        ),
        hypothesis_basis="test fixture",
    )


def _measurement(
    candidate: FiberCandidate,
    property_name: FiberProperty,
    value: float,
    *,
    provenance: Provenance = Provenance.EXPERIMENTAL,
) -> FiberMeasurement:
    stage = {
        FiberProperty.DENSITY: FiberStage.EXPERIMENTAL,
        FiberProperty.TENSILE_STRENGTH: FiberStage.EXPERIMENTAL,
        FiberProperty.STRAIN_AT_FAILURE: FiberStage.EXPERIMENTAL,
        FiberProperty.TOUGHNESS: FiberStage.EXPERIMENTAL,
        FiberProperty.FATIGUE_LIFE: FiberStage.EXPERIMENTAL,
        FiberProperty.KNOT_EFFICIENCY: FiberStage.EXPERIMENTAL,
        FiberProperty.FILAMENT_DIAMETER: FiberStage.EXPERIMENTAL,
        FiberProperty.BUNDLE_DIAMETER: FiberStage.EXPERIMENTAL,
        FiberProperty.ENVIRONMENTAL_STABILITY: FiberStage.EXPERIMENTAL,
    }[property_name]
    metadata = (
        {"temperature_min_c": -20, "temperature_max_c": 80, "humid_air": True}
        if property_name == FiberProperty.ENVIRONMENTAL_STABILITY
        else {}
    )
    return FiberMeasurement(
        candidate_id=candidate.id,
        design_hash=candidate.design_hash,
        property=property_name,
        value=value,
        unit=FIBER_PROPERTY_UNITS[property_name],
        uncertainty=0.1,
        replicate_count=3,
        provenance=provenance,
        stage=stage,
        protocol_hash="test-protocol",
        source_reference="test fixture",
        artifact_checksums={"raw.csv": "a" * 64},
        metadata=metadata,
    )


def test_only_matching_experiments_can_qualify_fiber_v1() -> None:
    candidate = _resolved_candidate()
    values = {
        FiberProperty.TENSILE_STRENGTH: 2.5,
        FiberProperty.STRAIN_AT_FAILURE: 20,
        FiberProperty.TOUGHNESS: 120,
        FiberProperty.DENSITY: 1.0,
        FiberProperty.FATIGUE_LIFE: 12_000,
        FiberProperty.KNOT_EFFICIENCY: 0.7,
        FiberProperty.FILAMENT_DIAMETER: 20,
        FiberProperty.BUNDLE_DIAMETER: 1.0,
        FiberProperty.ENVIRONMENTAL_STABILITY: 1.0,
    }
    measurements = [_measurement(candidate, property_name, value) for property_name, value in values.items()]

    report = assess_fiber_candidate(candidate, measurements)

    assert report.simulation_screen_passed
    assert report.experimentally_qualified
    assert report.service_load_gate_passed
    assert report.nominal_service_load_capacity_n is not None
    assert report.nominal_service_load_capacity_n >= 1000
    assert not report.missing_experimental_evidence
    assert len(report.evidence_ids) == len(values)


def test_surrogate_values_are_never_admitted_as_fiber_measurements() -> None:
    candidate = _resolved_candidate()
    prediction_disguised_as_measurement = _measurement(
        candidate,
        FiberProperty.TENSILE_STRENGTH,
        4.0,
        provenance=Provenance.SURROGATE,
    )

    report = assess_fiber_candidate(candidate, [prediction_disguised_as_measurement])

    assert not report.simulation_screen_passed
    assert not report.experimentally_qualified
    assert FiberProperty.TENSILE_STRENGTH in report.missing_experimental_evidence
    assert any("ignored" in warning for warning in report.warnings)


def test_experimental_evidence_requires_replicates_uncertainty_and_raw_artifacts() -> None:
    candidate = _resolved_candidate()
    with pytest.raises(ValueError, match="source reference"):
        FiberMeasurement(
            candidate_id=candidate.id,
            design_hash=candidate.design_hash,
            property=FiberProperty.DENSITY,
            value=1.0,
            unit="g/cm^3",
            uncertainty=0.01,
            replicate_count=3,
            provenance=Provenance.EXPERIMENTAL,
            stage=FiberStage.EXPERIMENTAL,
            protocol_hash="test-protocol",
        )
