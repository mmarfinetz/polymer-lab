"""Scientifically gated design contracts for the ``fiber-v1`` campaign.

The original closed loop optimizes repeat-unit chemistry for amorphous Tg and
density.  A load-bearing fiber is a different object: chemistry, molecular
weight, spinning, drawing, crystallinity, filament geometry, and bundle
construction jointly determine performance.  This module makes that design
envelope explicit without manufacturing surrogate measurements.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import FrozenModel, Provenance, stable_hash, utc_now


class FiberMaterialFamily(StrEnum):
    UHMWPE = "uhmwpe"
    ARAMID = "aramid"
    PBO = "pbo"
    SEGMENTED_POLYURETHANE_UREA = "segmented_polyurethane_urea"
    SILK_INSPIRED_MULTIBLOCK = "silk_inspired_multiblock"
    RECOMBINANT_SPIDROIN = "recombinant_spidroin"
    PROTECTIVE_SHEATH = "protective_sheath"
    ENERGY_DISSIPATING_INTERPHASE = "energy_dissipating_interphase"


class FiberRole(StrEnum):
    LOAD_BEARING_CORE = "load_bearing_core"
    SOFT_SEGMENT = "soft_segment"
    INTERPHASE = "interphase"
    SHEATH = "sheath"


class SpinningMethod(StrEnum):
    GEL = "gel_spin"
    WET = "wet_spin"
    DRY_JET_WET = "dry_jet_wet_spin"
    MELT = "melt_spin"
    HYBRID_ASSEMBLY = "hybrid_assembly"


class FiberPopulationRole(StrEnum):
    PRIMARY_LOAD_BEARING = "primary_load_bearing"
    DUCTILE_BRIDGE = "ductile_bridge"
    RIGID_REINFORCEMENT = "rigid_reinforcement"
    DISSIPATIVE_INTERPHASE = "dissipative_interphase"
    PROTECTIVE_SHEATH = "protective_sheath"


class FiberArchitectureTopology(StrEnum):
    BIMODAL_PARALLEL_BUNDLE = "bimodal_parallel_bundle"
    MULTIPHASE_INTERPHASE_BUNDLE = "multiphase_interphase_bundle"


class FiberPopulation(FrozenModel):
    name: str = Field(min_length=1)
    constituent_name: str = Field(min_length=1)
    role: FiberPopulationRole
    mass_fraction: float = Field(gt=0, le=1)
    draw_ratio: float | None = Field(default=None, gt=1)
    filament_count: int | None = Field(default=None, ge=1)
    filament_diameter_um: float | None = Field(default=None, gt=0)
    lay_angle_deg: float = Field(default=0, ge=0, le=90)


class FiberArchitecture(FrozenModel):
    topology: FiberArchitectureTopology
    populations: tuple[FiberPopulation, ...] = Field(min_length=2)
    assembly_description: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_populations(self) -> FiberArchitecture:
        if len({population.name for population in self.populations}) != len(self.populations):
            raise ValueError("fiber population names must be unique")
        if not math.isclose(
            sum(population.mass_fraction for population in self.populations),
            1.0,
            abs_tol=1e-6,
        ):
            raise ValueError("fiber population mass fractions must sum to one")
        if not any(
            population.role == FiberPopulationRole.PRIMARY_LOAD_BEARING
            for population in self.populations
        ):
            raise ValueError("fiber architecture requires a primary load-bearing population")
        return self


class FiberStage(StrEnum):
    THERMOPHYSICAL = "thermophysical"
    ALIGNED_CHAIN = "aligned_chain"
    FRACTURE = "fracture"
    BUNDLE = "bundle"
    EXPERIMENTAL = "experimental"


class FiberProperty(StrEnum):
    DENSITY = "density"
    TG = "tg"
    AXIAL_MODULUS = "axial_modulus"
    YIELD_STRESS_PROXY = "yield_stress_proxy"
    CHAIN_ORIENTATION = "chain_orientation"
    CHAIN_SLIP = "chain_slip"
    TENSILE_STRENGTH = "tensile_strength"
    STRAIN_AT_FAILURE = "strain_at_failure"
    TOUGHNESS = "toughness"
    FATIGUE_LIFE = "fatigue_life"
    KNOT_EFFICIENCY = "knot_efficiency"
    FILAMENT_DIAMETER = "filament_diameter"
    BUNDLE_DIAMETER = "bundle_diameter"
    ENVIRONMENTAL_STABILITY = "environmental_stability"


FIBER_PROPERTY_UNITS: dict[FiberProperty, str] = {
    FiberProperty.DENSITY: "g/cm^3",
    FiberProperty.TG: "degC",
    FiberProperty.AXIAL_MODULUS: "GPa",
    FiberProperty.YIELD_STRESS_PROXY: "GPa",
    FiberProperty.CHAIN_ORIENTATION: "ratio",
    FiberProperty.CHAIN_SLIP: "fractional_box_length",
    FiberProperty.TENSILE_STRENGTH: "GPa",
    FiberProperty.STRAIN_AT_FAILURE: "%",
    FiberProperty.TOUGHNESS: "MJ/m^3",
    FiberProperty.FATIGUE_LIFE: "cycles",
    FiberProperty.KNOT_EFFICIENCY: "ratio",
    FiberProperty.FILAMENT_DIAMETER: "um",
    FiberProperty.BUNDLE_DIAMETER: "mm",
    FiberProperty.ENVIRONMENTAL_STABILITY: "pass",
}


class FiberConstituent(FrozenModel):
    name: str = Field(min_length=1)
    material_family: FiberMaterialFamily
    role: FiberRole
    mass_fraction: float | None = Field(default=None, gt=0, le=1)
    representation: str | None = None
    representation_type: Literal["psmiles", "protein_sequence", "material_family", "unspecified"] = "unspecified"
    evidence_basis: str = Field(min_length=1)


class FiberChemistry(FrozenModel):
    constituents: tuple[FiberConstituent, ...] = Field(min_length=1)
    number_average_molecular_weight_g_mol: float | None = Field(default=None, gt=0)
    weight_average_molecular_weight_g_mol: float | None = Field(default=None, gt=0)
    hard_segment_fraction: float | None = Field(default=None, ge=0, le=1)
    soft_segment_fraction: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def coherent_composition(self) -> FiberChemistry:
        fractions = [item.mass_fraction for item in self.constituents]
        if all(item is not None for item in fractions) and not math.isclose(
            sum(item for item in fractions if item is not None), 1.0, abs_tol=1e-6
        ):
            raise ValueError("fully specified constituent mass fractions must sum to one")
        if self.hard_segment_fraction is not None and self.soft_segment_fraction is not None:
            if not math.isclose(self.hard_segment_fraction + self.soft_segment_fraction, 1.0, abs_tol=1e-6):
                raise ValueError("hard and soft segment fractions must sum to one")
        return self


class FiberProcess(FrozenModel):
    spinning_method: SpinningMethod
    dope_concentration_mass_fraction: float | None = Field(default=None, gt=0, lt=1)
    solvent_or_buffer: str | None = None
    coagulation_or_trigger: str | None = None
    spinning_temperature_c: float | None = None
    draw_ratio: float | None = Field(default=None, gt=1)
    zone_draw_temperature_c: float | None = None
    zone_draw_stress_mpa: float | None = Field(default=None, gt=0)
    heat_band_speed_mm_min: float | None = Field(default=None, gt=0)
    crystallinity_fraction: float | None = Field(default=None, ge=0, le=1)
    filament_diameter_um: float | None = Field(default=None, gt=0)
    filament_count: int | None = Field(default=None, ge=1)
    twist_turns_per_m: float | None = Field(default=None, ge=0)
    bundle_diameter_mm: float | None = Field(default=None, gt=0)
    core_mass_fraction: float | None = Field(default=None, gt=0, le=1)
    sheath_mass_fraction: float | None = Field(default=None, ge=0, lt=1)
    anneal_temperature_c: float | None = None
    anneal_under_tension: bool | None = None
    unresolved_parameters: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent_geometry_and_layers(self) -> FiberProcess:
        if self.core_mass_fraction is not None and self.sheath_mass_fraction is not None:
            if not math.isclose(self.core_mass_fraction + self.sheath_mass_fraction, 1.0, abs_tol=1e-6):
                raise ValueError("core and sheath fractions must sum to one")
        if (
            self.filament_diameter_um is not None
            and self.bundle_diameter_mm is not None
            and self.filament_diameter_um / 1000 > self.bundle_diameter_mm
        ):
            raise ValueError("an individual filament cannot be wider than its bundle")
        if len(self.unresolved_parameters) != len(set(self.unresolved_parameters)):
            raise ValueError("unresolved parameter names must be unique")
        return self


class FiberCandidate(FrozenModel):
    id: str
    name: str = Field(min_length=1)
    design_hash: str
    chemistry: FiberChemistry
    process: FiberProcess
    architecture: FiberArchitecture | None = None
    generation: int = Field(default=0, ge=0)
    parent_ids: tuple[str, ...] = ()
    status: Literal["hypothesis", "screened", "qualified"] = "hypothesis"
    hypothesis_basis: str = Field(min_length=1)
    assumptions: tuple[str, ...] = ()
    source_references: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)


def make_fiber_candidate(
    *,
    name: str,
    chemistry: FiberChemistry,
    process: FiberProcess,
    architecture: FiberArchitecture | None = None,
    hypothesis_basis: str,
    assumptions: tuple[str, ...] = (),
    source_references: tuple[str, ...] = (),
    generation: int = 0,
    parent_ids: tuple[str, ...] = (),
) -> FiberCandidate:
    process_payload = process.model_dump(mode="json")
    # Preserve v1 design hashes when newly optional zone-drawing fields are unset.
    for optional_field in (
        "zone_draw_temperature_c",
        "zone_draw_stress_mpa",
        "heat_band_speed_mm_min",
    ):
        if process_payload[optional_field] is None:
            process_payload.pop(optional_field)
    design_payload = {
        "name": name,
        "chemistry": chemistry.model_dump(mode="json"),
        "process": process_payload,
        "generation": generation,
        "parent_ids": parent_ids,
        "hypothesis_basis": hypothesis_basis,
        "assumptions": assumptions,
        "source_references": source_references,
    }
    if architecture is not None:
        design_payload["architecture"] = architecture.model_dump(mode="json")
    design_hash = stable_hash(design_payload)
    return FiberCandidate(
        id=f"fiber-{design_hash[:16]}",
        name=name,
        design_hash=design_hash,
        chemistry=chemistry,
        process=process,
        architecture=architecture,
        generation=generation,
        parent_ids=parent_ids,
        hypothesis_basis=hypothesis_basis,
        assumptions=assumptions,
        source_references=source_references,
    )


class NumericTarget(FrozenModel):
    minimum: float | None = None
    maximum: float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_bounds(self) -> NumericTarget:
        if self.minimum is None and self.maximum is None:
            raise ValueError("a target requires a minimum or maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("target minimum cannot exceed maximum")
        return self

    def accepts(self, value: float) -> bool:
        minimum_ok = self.minimum is None or (
            value >= self.minimum if self.minimum_inclusive else value > self.minimum
        )
        maximum_ok = self.maximum is None or (
            value <= self.maximum if self.maximum_inclusive else value < self.maximum
        )
        return minimum_ok and maximum_ok


class FiberV1Target(FrozenModel):
    tensile_strength: NumericTarget = NumericTarget(minimum=2.0, unit="GPa")
    tensile_strength_stretch_goal_gpa: float = 4.0
    strain_at_failure: NumericTarget = NumericTarget(minimum=15.0, maximum=40.0, unit="%")
    toughness: NumericTarget = NumericTarget(minimum=100.0, minimum_inclusive=False, unit="MJ/m^3")
    density: NumericTarget = NumericTarget(maximum=1.3, maximum_inclusive=False, unit="g/cm^3")
    bundle_diameter: NumericTarget = NumericTarget(minimum=0.5, maximum=2.0, unit="mm")
    filament_diameter: NumericTarget = NumericTarget(minimum=10.0, maximum=30.0, unit="um")
    fatigue_life: NumericTarget = NumericTarget(minimum=10_000.0, minimum_inclusive=False, unit="cycles")
    knot_efficiency: NumericTarget = NumericTarget(minimum=0.60, minimum_inclusive=False, unit="ratio")
    environmental_temperature_min_c: float = -20.0
    environmental_temperature_max_c: float = 80.0
    humid_air_required: bool = True
    reference_service_load_n: float = Field(default=1000.0, gt=0)


class FiberMeasurement(FrozenModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str
    design_hash: str
    property: FiberProperty
    value: float
    unit: str
    uncertainty: float | None = Field(default=None, ge=0)
    replicate_count: int = Field(default=1, ge=1)
    provenance: Provenance
    stage: FiberStage
    protocol_hash: str = Field(min_length=1)
    converged: bool = True
    source_reference: str | None = None
    artifact_checksums: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def canonical_unit(self) -> FiberMeasurement:
        expected = FIBER_PROPERTY_UNITS[self.property]
        if self.unit != expected:
            raise ValueError(f"{self.property.value} must use canonical unit {expected!r}")
        evidence_provenance = {Provenance.EXPERIMENTAL, Provenance.MD, Provenance.DFT}
        if self.provenance in evidence_provenance:
            if not self.source_reference:
                raise ValueError("scientific fiber evidence requires a source reference")
            if not self.artifact_checksums:
                raise ValueError("scientific fiber evidence requires checksummed raw artifacts")
            invalid_digests = [
                name
                for name, digest in self.artifact_checksums.items()
                if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower())
            ]
            if invalid_digests:
                raise ValueError(f"invalid SHA-256 artifact digests: {sorted(invalid_digests)}")
        if self.provenance == Provenance.EXPERIMENTAL:
            if self.replicate_count < 3:
                raise ValueError("experimental qualification requires at least three replicates")
            if self.uncertainty is None:
                raise ValueError("experimental qualification requires reported uncertainty")
        return self


class FiberEvaluationStep(FrozenModel):
    stage: FiberStage
    backend: str
    properties: tuple[FiberProperty, ...]
    admission_rule: str
    implemented: bool


class FiberQualificationReport(FrozenModel):
    candidate_id: str
    design_hash: str
    simulation_screen_passed: bool
    experimentally_qualified: bool
    nominal_service_load_capacity_n: float | None
    service_load_gate_passed: bool
    passed_properties: tuple[FiberProperty, ...]
    missing_simulation_evidence: tuple[FiberProperty, ...]
    missing_experimental_evidence: tuple[FiberProperty, ...]
    failed_targets: dict[str, str]
    warnings: tuple[str, ...]
    evidence_ids: tuple[str, ...]


_TARGET_PROPERTIES = (
    FiberProperty.TENSILE_STRENGTH,
    FiberProperty.STRAIN_AT_FAILURE,
    FiberProperty.TOUGHNESS,
    FiberProperty.DENSITY,
    FiberProperty.FATIGUE_LIFE,
    FiberProperty.KNOT_EFFICIENCY,
    FiberProperty.FILAMENT_DIAMETER,
    FiberProperty.BUNDLE_DIAMETER,
    FiberProperty.ENVIRONMENTAL_STABILITY,
)

_MINIMUM_STAGES = {
    FiberProperty.DENSITY: FiberStage.THERMOPHYSICAL,
    FiberProperty.TG: FiberStage.THERMOPHYSICAL,
    FiberProperty.AXIAL_MODULUS: FiberStage.ALIGNED_CHAIN,
    FiberProperty.YIELD_STRESS_PROXY: FiberStage.ALIGNED_CHAIN,
    FiberProperty.CHAIN_ORIENTATION: FiberStage.ALIGNED_CHAIN,
    FiberProperty.CHAIN_SLIP: FiberStage.ALIGNED_CHAIN,
    FiberProperty.TENSILE_STRENGTH: FiberStage.FRACTURE,
    FiberProperty.STRAIN_AT_FAILURE: FiberStage.FRACTURE,
    FiberProperty.TOUGHNESS: FiberStage.FRACTURE,
    FiberProperty.FATIGUE_LIFE: FiberStage.BUNDLE,
    FiberProperty.KNOT_EFFICIENCY: FiberStage.BUNDLE,
    FiberProperty.FILAMENT_DIAMETER: FiberStage.BUNDLE,
    FiberProperty.BUNDLE_DIAMETER: FiberStage.BUNDLE,
    FiberProperty.ENVIRONMENTAL_STABILITY: FiberStage.EXPERIMENTAL,
}

_STAGE_ORDER = {stage: index for index, stage in enumerate(FiberStage)}


def _target_for(target: FiberV1Target, property_name: FiberProperty) -> NumericTarget | None:
    return {
        FiberProperty.TENSILE_STRENGTH: target.tensile_strength,
        FiberProperty.STRAIN_AT_FAILURE: target.strain_at_failure,
        FiberProperty.TOUGHNESS: target.toughness,
        FiberProperty.DENSITY: target.density,
        FiberProperty.FATIGUE_LIFE: target.fatigue_life,
        FiberProperty.KNOT_EFFICIENCY: target.knot_efficiency,
        FiberProperty.FILAMENT_DIAMETER: target.filament_diameter,
        FiberProperty.BUNDLE_DIAMETER: target.bundle_diameter,
    }.get(property_name)


def _environment_covers_target(measurement: FiberMeasurement, target: FiberV1Target) -> bool:
    return (
        measurement.value == 1.0
        and float(measurement.metadata.get("temperature_min_c", math.inf))
        <= target.environmental_temperature_min_c
        and float(measurement.metadata.get("temperature_max_c", -math.inf))
        >= target.environmental_temperature_max_c
        and (not target.humid_air_required or measurement.metadata.get("humid_air") is True)
    )


def assess_fiber_candidate(
    candidate: FiberCandidate,
    measurements: tuple[FiberMeasurement, ...] | list[FiberMeasurement],
    *,
    target: FiberV1Target | None = None,
) -> FiberQualificationReport:
    """Assess evidence without allowing predictions to become measurements.

    Simulation screening accepts only converged MD/DFT evidence from an
    appropriate fidelity stage. Final qualification requires experimental
    evidence for every engineering target and exact candidate design identity.
    """

    target = target or FiberV1Target()
    relevant = [
        item
        for item in measurements
        if item.candidate_id == candidate.id
        and item.design_hash == candidate.design_hash
        and item.converged
        and math.isfinite(item.value)
    ]
    valid: dict[tuple[FiberProperty, Provenance], list[FiberMeasurement]] = {}
    for item in relevant:
        if _STAGE_ORDER[item.stage] < _STAGE_ORDER[_MINIMUM_STAGES[item.property]]:
            continue
        valid.setdefault((item.property, item.provenance), []).append(item)

    passed: set[FiberProperty] = set()
    failed: dict[str, str] = {}
    missing_sim: list[FiberProperty] = []
    missing_exp: list[FiberProperty] = []
    evidence_ids: set[str] = set()
    simulation_core = {
        FiberProperty.DENSITY,
        FiberProperty.TENSILE_STRENGTH,
        FiberProperty.STRAIN_AT_FAILURE,
        FiberProperty.TOUGHNESS,
    }

    def passing(items: list[FiberMeasurement]) -> list[FiberMeasurement]:
        accepted: list[FiberMeasurement] = []
        for item in items:
            if item.property == FiberProperty.ENVIRONMENTAL_STABILITY:
                if _environment_covers_target(item, target):
                    accepted.append(item)
            else:
                numeric_target = _target_for(target, item.property)
                if numeric_target is None or numeric_target.accepts(item.value):
                    accepted.append(item)
        return accepted

    for property_name in _TARGET_PROPERTIES:
        simulated = passing(
            valid.get((property_name, Provenance.MD), [])
            + valid.get((property_name, Provenance.DFT), [])
        )
        experimental = passing(valid.get((property_name, Provenance.EXPERIMENTAL), []))
        if property_name in simulation_core and not simulated and not experimental:
            missing_sim.append(property_name)
        if not experimental:
            missing_exp.append(property_name)
        else:
            passed.add(property_name)
            evidence_ids.update(item.id for item in experimental)
        available = (
            valid.get((property_name, Provenance.MD), [])
            + valid.get((property_name, Provenance.DFT), [])
            + valid.get((property_name, Provenance.EXPERIMENTAL), [])
        )
        if available and not passing(available):
            failed[property_name.value] = "available converged evidence does not meet fiber-v1 target"

    warnings: list[str] = []
    if candidate.process.unresolved_parameters:
        warnings.append(
            "candidate still has unresolved design variables: "
            + ", ".join(candidate.process.unresolved_parameters)
        )
    if any(item.provenance == Provenance.SURROGATE for item in relevant):
        warnings.append("surrogate predictions were ignored by the measurement admission gate")
    nominal_capacity: float | None = None
    service_load_gate_passed = False
    strength_rows = passing(valid.get((FiberProperty.TENSILE_STRENGTH, Provenance.EXPERIMENTAL), []))
    knot_rows = passing(valid.get((FiberProperty.KNOT_EFFICIENCY, Provenance.EXPERIMENTAL), []))
    filament_rows = passing(valid.get((FiberProperty.FILAMENT_DIAMETER, Provenance.EXPERIMENTAL), []))
    bundle_rows = passing(valid.get((FiberProperty.BUNDLE_DIAMETER, Provenance.EXPERIMENTAL), []))
    if strength_rows and knot_rows and filament_rows and bundle_rows and candidate.process.filament_count:
        strength_gpa = min(item.value for item in strength_rows)
        knot_efficiency = min(item.value for item in knot_rows)
        filament_diameter_mm = min(item.value for item in filament_rows) / 1000
        bundle_diameter_mm = min(item.value for item in bundle_rows)
        filament_area_mm2 = (
            candidate.process.filament_count * math.pi * filament_diameter_mm**2 / 4
        )
        bundle_area_mm2 = math.pi * bundle_diameter_mm**2 / 4
        if filament_area_mm2 > bundle_area_mm2:
            failed["bundle_geometry"] = (
                "declared filament count and diameter exceed the measured bundle cross-section"
            )
        else:
            # 1 GPa = 1000 N/mm^2. This is nominal axial capacity before any
            # safety factor beyond the separately measured knot efficiency.
            nominal_capacity = strength_gpa * 1000 * filament_area_mm2 * knot_efficiency
            service_load_gate_passed = nominal_capacity >= target.reference_service_load_n
            if not service_load_gate_passed:
                failed["service_load_capacity"] = (
                    f"nominal capacity {nominal_capacity:.1f} N is below the "
                    f"{target.reference_service_load_n:.1f} N reference load"
                )
    else:
        warnings.append("service-load capacity cannot be checked until filament count and geometry are measured")
    simulation_screen_passed = not missing_sim and not any(
        property_name.value in failed for property_name in simulation_core
    )
    experimentally_qualified = (
        not missing_exp
        and not failed
        and not candidate.process.unresolved_parameters
        and service_load_gate_passed
    )
    return FiberQualificationReport(
        candidate_id=candidate.id,
        design_hash=candidate.design_hash,
        simulation_screen_passed=simulation_screen_passed,
        experimentally_qualified=experimentally_qualified,
        nominal_service_load_capacity_n=nominal_capacity,
        service_load_gate_passed=service_load_gate_passed,
        passed_properties=tuple(sorted(passed, key=lambda item: item.value)),
        missing_simulation_evidence=tuple(sorted(missing_sim, key=lambda item: item.value)),
        missing_experimental_evidence=tuple(sorted(missing_exp, key=lambda item: item.value)),
        failed_targets=failed,
        warnings=tuple(warnings),
        evidence_ids=tuple(sorted(evidence_ids)),
    )


class FiberV1Manifest(FrozenModel):
    schema_version: Literal[1] = 1
    name: Literal["fiber-v1"] = "fiber-v1"
    campaign_id: str
    state: Literal["initialized", "screening", "experimental_validation", "qualified"] = "initialized"
    target: FiberV1Target
    candidates: tuple[FiberCandidate, ...]
    evaluation_plan: tuple[FiberEvaluationStep, ...]
    excluded_campaign_ids: tuple[str, ...] = ()
    scientific_status: str
    created_at: datetime = Field(default_factory=utc_now)


def default_fiber_v1_candidates() -> tuple[FiberCandidate, ...]:
    common_unresolved = (
        "molecular_weight_distribution",
        "dope_concentration",
        "draw_ratio",
        "crystallinity",
        "filament_count",
        "twist",
        "bundle_diameter",
        "annealing_conditions",
    )

    def family_candidate(
        name: str,
        family: FiberMaterialFamily,
        method: SpinningMethod,
        basis: str,
    ) -> FiberCandidate:
        return make_fiber_candidate(
            name=name,
            chemistry=FiberChemistry(
                constituents=(
                    FiberConstituent(
                        name=name,
                        material_family=family,
                        role=FiberRole.LOAD_BEARING_CORE,
                        evidence_basis="material-family seed; exact chemistry unresolved",
                    ),
                )
            ),
            process=FiberProcess(spinning_method=method, unresolved_parameters=common_unresolved),
            hypothesis_basis=basis,
        )

    candidates = [
        make_fiber_candidate(
            name="uhmwpe-gel-draw-100-doe-001",
            chemistry=FiberChemistry(
                constituents=(
                    FiberConstituent(
                        name="linear UHMWPE",
                        material_family=FiberMaterialFamily.UHMWPE,
                        role=FiberRole.LOAD_BEARING_CORE,
                        mass_fraction=1.0,
                        representation="[*]CC[*]",
                        representation_type="psmiles",
                        evidence_basis="exact repeat chemistry; molecular-weight values are DOE setpoints",
                    ),
                ),
                number_average_molecular_weight_g_mol=1_500_000,
                weight_average_molecular_weight_g_mol=3_000_000,
            ),
            process=FiberProcess(
                spinning_method=SpinningMethod.GEL,
                dope_concentration_mass_fraction=0.05,
                solvent_or_buffer="paraffin oil",
                coagulation_or_trigger="ambient-air quench, n-hexane extraction, vacuum dry",
                spinning_temperature_c=170,
                draw_ratio=100,
                crystallinity_fraction=0.85,
                filament_diameter_um=20,
                filament_count=3200,
                twist_turns_per_m=25,
                bundle_diameter_mm=1.3,
                core_mass_fraction=1.0,
                sheath_mass_fraction=0.0,
                anneal_temperature_c=148,
                anneal_under_tension=True,
            ),
            hypothesis_basis=(
                "First concrete fiber-v1 DOE point. Chemistry and process settings are design inputs, "
                "not measured output."
            ),
            assumptions=(
                "The 0.85 crystallinity fraction is a DOE target requiring measurement.",
                "The 25 turns/m bundle twist is an initial bundle variable, not an optimized value.",
                "Atomistic cells use finite chains and draw ratios 2/4/6; they cannot reproduce the full "
                "1.5 M g/mol chain or draw 100.",
            ),
            source_references=(
                "https://doi.org/10.1007/BF00955487",
                "https://doi.org/10.1002/polb.20682",
                "https://research.rug.nl/en/publications/mechanical-properties-of-ultra-high-molecular-weight-polyethylene",
            ),
        ),
        make_fiber_candidate(
            name="ppta-dry-jet-wet-doe-001",
            chemistry=FiberChemistry(
                constituents=(
                    FiberConstituent(
                        name="poly(p-phenylene terephthalamide)",
                        material_family=FiberMaterialFamily.ARAMID,
                        role=FiberRole.LOAD_BEARING_CORE,
                        mass_fraction=1.0,
                        representation="[*]C(=O)c1ccc(cc1)C(=O)Nc1ccc(cc1)N[*]",
                        representation_type="psmiles",
                        evidence_basis="exact PPTA repeat chemistry; molecular-weight values are DOE setpoints",
                    ),
                ),
                number_average_molecular_weight_g_mol=20_000,
                weight_average_molecular_weight_g_mol=40_000,
            ),
            process=FiberProcess(
                spinning_method=SpinningMethod.DRY_JET_WET,
                dope_concentration_mass_fraction=0.15,
                solvent_or_buffer="concentrated sulfuric acid",
                coagulation_or_trigger="6 mm air gap then room-temperature water bath",
                spinning_temperature_c=60,
                draw_ratio=3.5,
                crystallinity_fraction=0.75,
                filament_diameter_um=20,
                filament_count=3200,
                twist_turns_per_m=25,
                bundle_diameter_mm=1.3,
                core_mass_fraction=1.0,
                sheath_mass_fraction=0.0,
                anneal_temperature_c=300,
                anneal_under_tension=True,
            ),
            hypothesis_basis=(
                "Second concrete fiber-v1 DOE point and rigid-chain comparator; process values are inputs, "
                "not measurements."
            ),
            assumptions=(
                "The molecular-weight distribution and 0.75 crystallinity are DOE values requiring measurement.",
                "Pure PPTA is expected to challenge the density target and is retained as a strength comparator.",
                "GAFF2 aligned-cell results cannot establish PPTA fracture strength; a validated reactive "
                "potential is required later.",
            ),
            source_references=(
                "https://doi.org/10.1016/j.polymer.2006.10.006",
                "https://doi.org/10.1016/j.polymer.2017.03.012",
            ),
        ),
        family_candidate(
            "segmented-polyurethane-urea-family",
            FiberMaterialFamily.SEGMENTED_POLYURETHANE_UREA,
            SpinningMethod.WET,
            "Candidate family for hard/soft-segment optimization; segment chemistry and ratio unresolved.",
        ),
        family_candidate(
            "silk-inspired-multiblock-family",
            FiberMaterialFamily.SILK_INSPIRED_MULTIBLOCK,
            SpinningMethod.WET,
            "Candidate family for combined crystalline and energy-dissipating blocks; sequence unresolved.",
        ),
        make_fiber_candidate(
            name="masp-70-30-prior-hypothesis",
            chemistry=FiberChemistry(
                constituents=(
                    FiberConstituent(
                        name="MaSp1 candidate protein",
                        material_family=FiberMaterialFamily.RECOMBINANT_SPIDROIN,
                        role=FiberRole.LOAD_BEARING_CORE,
                        mass_fraction=0.70,
                        evidence_basis="motif-proxy optimization only; seven repetitive units",
                    ),
                    FiberConstituent(
                        name="MaSp2 candidate protein",
                        material_family=FiberMaterialFamily.RECOMBINANT_SPIDROIN,
                        role=FiberRole.SOFT_SEGMENT,
                        mass_fraction=0.30,
                        evidence_basis="motif-proxy optimization only; six repetitive units",
                    ),
                ),
                hard_segment_fraction=0.70,
                soft_segment_fraction=0.30,
            ),
            process=FiberProcess(
                spinning_method=SpinningMethod.WET,
                unresolved_parameters=(
                    "protein_molecular_weight_distribution",
                    "protein_concentration",
                    "buffer",
                    "trigger_composition",
                    "pH_and_ionic_strength",
                    "temperature",
                    "viscosity_curve",
                    "core_trigger_flow_ratio",
                    "gelation_time",
                    "draw_ratio",
                    "crystallinity",
                    "filament_geometry",
                    "bundle_construction",
                    "drying_and_annealing",
                ),
            ),
            hypothesis_basis=(
                "Preserved from the earlier motif-based search as an explicitly unvalidated hypothesis; "
                "its old mean-baseline strength estimate is not evidence."
            ),
        ),
    ]
    return tuple(candidates)


def default_fiber_v1_evaluation_plan() -> tuple[FiberEvaluationStep, ...]:
    return (
        FiberEvaluationStep(
            stage=FiberStage.THERMOPHYSICAL,
            backend="RadonPy/Psi4/LAMMPS for compatible synthetic chemistries",
            properties=(FiberProperty.DENSITY, FiberProperty.TG),
            admission_rule=(
                "Converged MD is screening evidence only; protein systems require a protein-specific backend."
            ),
            implemented=True,
        ),
        FiberEvaluationStep(
            stage=FiberStage.ALIGNED_CHAIN,
            backend="LAMMPS aligned-chain protocol",
            properties=(
                FiberProperty.AXIAL_MODULUS,
                FiberProperty.YIELD_STRESS_PROXY,
                FiberProperty.CHAIN_ORIENTATION,
                FiberProperty.CHAIN_SLIP,
            ),
            admission_rule=(
                "Protocol-validation runs are diagnostic only. Production evidence requires temperature, "
                "strain-completion, fit-quality, identity, software-version, and artifact-checksum gates."
            ),
            implemented=True,
        ),
        FiberEvaluationStep(
            stage=FiberStage.FRACTURE,
            backend="validated reactive-potential fracture protocol",
            properties=(
                FiberProperty.TENSILE_STRENGTH,
                FiberProperty.STRAIN_AT_FAILURE,
                FiberProperty.TOUGHNESS,
            ),
            admission_rule="Require an applicable validated potential, replicated trajectories, and uncertainty.",
            implemented=False,
        ),
        FiberEvaluationStep(
            stage=FiberStage.BUNDLE,
            backend="mesoscale filament/bundle model",
            properties=(
                FiberProperty.FATIGUE_LIFE,
                FiberProperty.KNOT_EFFICIENCY,
                FiberProperty.FILAMENT_DIAMETER,
                FiberProperty.BUNDLE_DIAMETER,
            ),
            admission_rule="Require explicit filament count, twist, defects, interfaces, and anchor/knot geometry.",
            implemented=False,
        ),
        FiberEvaluationStep(
            stage=FiberStage.EXPERIMENTAL,
            backend="spinning plus tensile/environmental test program",
            properties=_TARGET_PROPERTIES,
            admission_rule="Only matching-design experimental evidence can qualify fiber-v1.",
            implemented=False,
        ),
    )


def initialize_fiber_v1(
    root: str | Path,
    *,
    excluded_campaign_ids: tuple[str, ...] = (),
    force: bool = False,
) -> FiberV1Manifest:
    destination = Path(root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists() and not force:
        return FiberV1Manifest.model_validate_json(manifest_path.read_text())
    target = FiberV1Target()
    candidates = default_fiber_v1_candidates()
    plan = default_fiber_v1_evaluation_plan()
    campaign_hash = stable_hash(
        {
            "name": "fiber-v1",
            "target": target.model_dump(mode="json"),
            "candidate_hashes": [candidate.design_hash for candidate in candidates],
            "evaluation_plan": [step.model_dump(mode="json") for step in plan],
        }
    )
    manifest = FiberV1Manifest(
        campaign_id=f"fiber-v1-{campaign_hash[:16]}",
        target=target,
        candidates=candidates,
        evaluation_plan=plan,
        excluded_campaign_ids=excluded_campaign_ids,
        scientific_status=(
            "Design space initialized. No fiber candidate is qualified and no surrogate value is stored "
            "as a measurement."
        ),
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n")
    (destination / "target.json").write_text(target.model_dump_json(indent=2) + "\n")
    (destination / "candidates.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in candidates], indent=2, default=str) + "\n"
    )
    (destination / "evaluation-plan.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in plan], indent=2, default=str) + "\n"
    )
    empty_reports = [assess_fiber_candidate(candidate, []).model_dump(mode="json") for candidate in candidates]
    (destination / "qualification.json").write_text(json.dumps(empty_reports, indent=2, default=str) + "\n")
    return manifest


def summarize_fiber_v1(root: str | Path) -> dict[str, Any]:
    source = Path(root).resolve()
    manifest = FiberV1Manifest.model_validate_json((source / "manifest.json").read_text())
    reports = [assess_fiber_candidate(candidate, []) for candidate in manifest.candidates]
    return {
        "name": manifest.name,
        "campaign_id": manifest.campaign_id,
        "state": manifest.state,
        "candidate_count": len(manifest.candidates),
        "qualified_candidates": sum(item.experimentally_qualified for item in reports),
        "implemented_stages": [step.stage for step in manifest.evaluation_plan if step.implemented],
        "blocked_stages": [step.stage for step in manifest.evaluation_plan if not step.implemented],
        "excluded_campaign_ids": manifest.excluded_campaign_ids,
        "scientific_status": manifest.scientific_status,
    }
