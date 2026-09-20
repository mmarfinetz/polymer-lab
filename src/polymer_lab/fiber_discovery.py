"""Architecture-aware discovery plan for the fiber-v1 engineering target."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from .fiber import (
    FiberArchitecture,
    FiberArchitectureTopology,
    FiberCandidate,
    FiberChemistry,
    FiberConstituent,
    FiberMaterialFamily,
    FiberPopulation,
    FiberPopulationRole,
    FiberProcess,
    FiberRole,
    FiberV1Manifest,
    SpinningMethod,
    make_fiber_candidate,
)
from .models import FrozenModel, stable_hash, utc_now

SPU_HA_FORMULATION = "PTMEG2000:HMDI:ADH:BDA=5.0:10.0:2.5:2.5 mmol"
PBO_PSMILES = "[*]C2=NC1=CC(N=C(C4=CC=C([*])C=C4)O3)=C3C=C1O2"


class FiberDiscoveryStage(FrozenModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    gate: str = Field(min_length=1)
    can_emit_candidate_measurements: bool = False
    implemented: bool = False


class FiberDiscoveryPlan(FrozenModel):
    schema_version: Literal[1] = 1
    name: Literal["fiber-v1-discovery-v2"] = "fiber-v1-discovery-v2"
    plan_id: str
    parent_campaign_id: str
    candidates: tuple[FiberCandidate, ...]
    priority_order: tuple[str, ...]
    stages: tuple[FiberDiscoveryStage, ...]
    compute_policy: tuple[str, ...]
    scientific_status: str
    created_at: datetime = Field(default_factory=utc_now)


def _uhmwpe_constituent(
    *,
    name: str,
    role: FiberRole,
    mass_fraction: float,
) -> FiberConstituent:
    return FiberConstituent(
        name=name,
        material_family=FiberMaterialFamily.UHMWPE,
        role=role,
        mass_fraction=mass_fraction,
        representation="[*]CC[*]",
        representation_type="psmiles",
        evidence_basis="exact polyethylene repeat; population draw ratio is a DOE input",
    )


def _spu_ha_constituent(*, mass_fraction: float) -> FiberConstituent:
    return FiberConstituent(
        name="SPU-HA supramolecular polyurethane interphase",
        material_family=FiberMaterialFamily.SEGMENTED_POLYURETHANE_UREA,
        role=FiberRole.INTERPHASE,
        mass_fraction=mass_fraction,
        representation=SPU_HA_FORMULATION,
        representation_type="material_family",
        evidence_basis=(
            "published constituent stoichiometry; copolymer sequence and compatibility with the "
            "fiber coating process remain unresolved"
        ),
    )


def _pbo_constituent(*, mass_fraction: float) -> FiberConstituent:
    return FiberConstituent(
        name="poly(p-phenylene benzobisoxazole)",
        material_family=FiberMaterialFamily.PBO,
        role=FiberRole.LOAD_BEARING_CORE,
        mass_fraction=mass_fraction,
        representation=PBO_PSMILES,
        representation_type="psmiles",
        evidence_basis="explicit PBO repeat chemistry; draw ratio is a DOE input",
    )


def _population(
    *,
    name: str,
    constituent_name: str,
    role: FiberPopulationRole,
    mass_fraction: float,
    draw_ratio: float | None,
    filament_count: int | None,
) -> FiberPopulation:
    return FiberPopulation(
        name=name,
        constituent_name=constituent_name,
        role=role,
        mass_fraction=mass_fraction,
        draw_ratio=draw_ratio,
        filament_count=filament_count,
        filament_diameter_um=20 if filament_count is not None else None,
        lay_angle_deg=0,
    )


def _assembly_process(
    *,
    filament_count: int,
    core_fraction: float,
    interphase_fraction: float,
    unresolved: tuple[str, ...],
) -> FiberProcess:
    return FiberProcess(
        spinning_method=SpinningMethod.HYBRID_ASSEMBLY,
        solvent_or_buffer="population-specific spinning followed by dry bundle assembly",
        coagulation_or_trigger="population-specific solidification before interphase application",
        filament_diameter_um=20,
        filament_count=filament_count,
        twist_turns_per_m=25,
        bundle_diameter_mm=1.3,
        core_mass_fraction=core_fraction,
        sheath_mass_fraction=interphase_fraction,
        anneal_temperature_c=80 if interphase_fraction else 148,
        anneal_under_tension=True,
        unresolved_parameters=unresolved,
    )


def default_fiber_discovery_candidates(campaign: FiberV1Manifest) -> tuple[FiberCandidate, ...]:
    """Return explicit architecture hypotheses without creating property claims."""

    uhmwpe_matches = [item for item in campaign.candidates if item.name == "uhmwpe-gel-draw-100-doe-001"]
    if len(uhmwpe_matches) != 1:
        raise ValueError("fiber-v1 discovery requires exactly one UHMWPE seed")
    parent = uhmwpe_matches[0]
    molecular_weight = {
        "number_average_molecular_weight_g_mol": parent.chemistry.number_average_molecular_weight_g_mol,
        "weight_average_molecular_weight_g_mol": parent.chemistry.weight_average_molecular_weight_g_mol,
    }

    high_name = "high-draw UHMWPE"
    bridge_name = "lower-draw UHMWPE bridge"
    bimodal = make_fiber_candidate(
        name="uhmwpe-bimodal-draw-bundle-doe-001",
        chemistry=FiberChemistry(
            constituents=(
                _uhmwpe_constituent(name=high_name, role=FiberRole.LOAD_BEARING_CORE, mass_fraction=0.75),
                _uhmwpe_constituent(name=bridge_name, role=FiberRole.SOFT_SEGMENT, mass_fraction=0.25),
            ),
            **molecular_weight,
        ),
        process=_assembly_process(
            filament_count=3200,
            core_fraction=1.0,
            interphase_fraction=0.0,
            unresolved=("population_load_sharing", "post_peak_bridge_retention"),
        ),
        architecture=FiberArchitecture(
            topology=FiberArchitectureTopology.BIMODAL_PARALLEL_BUNDLE,
            populations=(
                _population(
                    name="strength population",
                    constituent_name=high_name,
                    role=FiberPopulationRole.PRIMARY_LOAD_BEARING,
                    mass_fraction=0.75,
                    draw_ratio=100,
                    filament_count=2400,
                ),
                _population(
                    name="ductile bridge population",
                    constituent_name=bridge_name,
                    role=FiberPopulationRole.DUCTILE_BRIDGE,
                    mass_fraction=0.25,
                    draw_ratio=10,
                    filament_count=800,
                ),
            ),
            assembly_description=(
                "Separately draw two UHMWPE filament populations, combine them in parallel, then apply "
                "low bundle twist and tension annealing."
            ),
        ),
        generation=1,
        parent_ids=(parent.id,),
        hypothesis_basis=(
            "Search strength and terminal strain independently using high- and lower-draw populations "
            "of the same low-density recyclable chemistry."
        ),
        assumptions=(
            "The 75/25 population split and draw ratios are DOE inputs, not optimized values.",
            "Constituent literature behavior is not evidence for the assembled bundle.",
            "A matching bundle tensile curve is required to determine strength, terminal strain, and toughness.",
        ),
        source_references=(
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC10955568/",
            "https://doi.org/10.1016/j.polymer.2024.127564",
        ),
    )

    interphase_name = "SPU-HA supramolecular polyurethane interphase"
    interphase = make_fiber_candidate(
        name="uhmwpe-bimodal-spu-interphase-doe-001",
        chemistry=FiberChemistry(
            constituents=(
                _uhmwpe_constituent(name=high_name, role=FiberRole.LOAD_BEARING_CORE, mass_fraction=0.75),
                _uhmwpe_constituent(name=bridge_name, role=FiberRole.SOFT_SEGMENT, mass_fraction=0.15),
                _spu_ha_constituent(mass_fraction=0.10),
            ),
            **molecular_weight,
        ),
        process=_assembly_process(
            filament_count=2880,
            core_fraction=0.90,
            interphase_fraction=0.10,
            unresolved=(
                "interphase_coating_method",
                "uhmwpe_interfacial_adhesion",
                "population_load_sharing",
                "post_coating_solvent_removal",
            ),
        ),
        architecture=FiberArchitecture(
            topology=FiberArchitectureTopology.MULTIPHASE_INTERPHASE_BUNDLE,
            populations=(
                _population(
                    name="strength population",
                    constituent_name=high_name,
                    role=FiberPopulationRole.PRIMARY_LOAD_BEARING,
                    mass_fraction=0.75,
                    draw_ratio=100,
                    filament_count=2400,
                ),
                _population(
                    name="ductile bridge population",
                    constituent_name=bridge_name,
                    role=FiberPopulationRole.DUCTILE_BRIDGE,
                    mass_fraction=0.15,
                    draw_ratio=10,
                    filament_count=480,
                ),
                _population(
                    name="continuous dissipative interphase",
                    constituent_name=interphase_name,
                    role=FiberPopulationRole.DISSIPATIVE_INTERPHASE,
                    mass_fraction=0.10,
                    draw_ratio=None,
                    filament_count=None,
                ),
            ),
            assembly_description=(
                "Coat a parallel bimodal UHMWPE bundle with a continuous SPU-HA interphase, remove "
                "solvent, then tension-condition below the UHMWPE melting range."
            ),
        ),
        generation=1,
        parent_ids=(parent.id,),
        hypothesis_basis=(
            "Retain a high-draw UHMWPE strength skeleton while a lower-draw population and reversible "
            "hydrogen-bonded interphase dissipate energy and protect contacts."
        ),
        assumptions=(
            "The 75/15/10 mass split is a DOE input and has no candidate-specific property evidence.",
            "Published SPU-HA film properties cannot be transferred to a thin fiber interphase without testing.",
            "Plasma or primer treatment may be required to bond the interphase to inert UHMWPE surfaces.",
        ),
        source_references=(
            "https://doi.org/10.1038/s41467-025-62449-8",
            "https://doi.org/10.1016/j.compscitech.2020.108112",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC10955568/",
        ),
    )

    pbo_name = "poly(p-phenylene benzobisoxazole)"
    hybrid = make_fiber_candidate(
        name="uhmwpe-pbo-spu-hybrid-bundle-doe-001",
        chemistry=FiberChemistry(
            constituents=(
                _uhmwpe_constituent(name=high_name, role=FiberRole.LOAD_BEARING_CORE, mass_fraction=0.60),
                _uhmwpe_constituent(name=bridge_name, role=FiberRole.SOFT_SEGMENT, mass_fraction=0.15),
                _pbo_constituent(mass_fraction=0.15),
                _spu_ha_constituent(mass_fraction=0.10),
            ),
        ),
        process=_assembly_process(
            filament_count=2880,
            core_fraction=0.90,
            interphase_fraction=0.10,
            unresolved=(
                "interphase_coating_method",
                "mixed_fiber_interfacial_adhesion",
                "population_load_sharing",
                "pbo_uv_protection",
                "post_coating_solvent_removal",
            ),
        ),
        architecture=FiberArchitecture(
            topology=FiberArchitectureTopology.MULTIPHASE_INTERPHASE_BUNDLE,
            populations=(
                _population(
                    name="UHMWPE strength population",
                    constituent_name=high_name,
                    role=FiberPopulationRole.PRIMARY_LOAD_BEARING,
                    mass_fraction=0.60,
                    draw_ratio=100,
                    filament_count=1920,
                ),
                _population(
                    name="UHMWPE ductile bridge population",
                    constituent_name=bridge_name,
                    role=FiberPopulationRole.DUCTILE_BRIDGE,
                    mass_fraction=0.15,
                    draw_ratio=10,
                    filament_count=480,
                ),
                _population(
                    name="PBO reinforcement population",
                    constituent_name=pbo_name,
                    role=FiberPopulationRole.RIGID_REINFORCEMENT,
                    mass_fraction=0.15,
                    draw_ratio=10,
                    filament_count=480,
                ),
                _population(
                    name="continuous dissipative interphase",
                    constituent_name=interphase_name,
                    role=FiberPopulationRole.DISSIPATIVE_INTERPHASE,
                    mass_fraction=0.10,
                    draw_ratio=None,
                    filament_count=None,
                ),
            ),
            assembly_description=(
                "Assemble separately spun UHMWPE and PBO populations in parallel, apply a continuous "
                "SPU-HA interphase, remove solvent, and tension-condition the bundle."
            ),
        ),
        generation=1,
        parent_ids=(parent.id,),
        hypothesis_basis=(
            "Use a minority rigid-rod population to preserve peak load while UHMWPE controls density and "
            "the bridge/interphase populations provide post-peak energy dissipation."
        ),
        assumptions=(
            "The 60/15/15/10 mass split is a DOE input, not a mixture-property prediction.",
            "PBO constituent strength and density do not establish hybrid performance.",
            "The whole design requires mesoscale load-transfer modeling and matching experiments.",
        ),
        source_references=(
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC6571651/",
            "https://doi.org/10.1038/s41467-025-62449-8",
            "https://doi.org/10.1016/j.compscitech.2020.108112",
        ),
    )
    return bimodal, interphase, hybrid


def make_fiber_discovery_plan(campaign: FiberV1Manifest) -> FiberDiscoveryPlan:
    candidates = default_fiber_discovery_candidates(campaign)
    stages = (
        FiberDiscoveryStage(
            name="component_reference_validation",
            purpose="Validate each physics backend against published component-level curves.",
            backend="PE crystal AIREBO-M; chemistry-specific PBO; SPU fragment DFT and polymer MD",
            gate="No architecture job until its component backend reproduces reference mechanisms.",
        ),
        FiberDiscoveryStage(
            name="restartable_component_pilots",
            purpose="Run short replicated cells and reject force-field, packing, or convergence failures early.",
            backend="Betty Slurm checkpointed pilots with three independent defect/seed realizations",
            gate="All required components converge; failed pilots emit diagnostics and no measurements.",
        ),
        FiberDiscoveryStage(
            name="architecture_load_transfer",
            purpose="Resolve population load sharing, slip, sequential failure, and interphase pullout.",
            backend="Mesoscale multifilament stress-transfer model calibrated only from admitted component data",
            gate="Predicted envelopes may prioritize prototypes but are never admitted as measurements.",
        ),
        FiberDiscoveryStage(
            name="matching_design_experiments",
            purpose="Spin, assemble, and test the exact architecture under the fiber-v1 conditions.",
            backend="Replicated tensile, density, fatigue, knot, creep, humidity, and temperature tests",
            gate="Only matching-design experiments can qualify a candidate against the full target.",
            can_emit_candidate_measurements=True,
        ),
    )
    compute_policy = (
        "Do not use amorphous RadonPy convergence as the sole gate for a semicrystalline fiber.",
        "Use crystalline PE cells for axial response and the amorphous cell only for tie-chain/interphase diagnostics.",
        "Run three restartable pilots before any production trajectory.",
        "Stop at the first failed identity, force-field, convergence, density, or orientation gate.",
        "Never convert constituent literature values, mixture estimates, or surrogate outputs into "
        "candidate measurements.",
    )
    identity = {
        "parent_campaign_id": campaign.campaign_id,
        "candidate_design_hashes": [candidate.design_hash for candidate in candidates],
        "stages": [stage.model_dump(mode="json") for stage in stages],
        "compute_policy": compute_policy,
    }
    return FiberDiscoveryPlan(
        plan_id=f"fiber-discovery-{stable_hash(identity)[:16]}",
        parent_campaign_id=campaign.campaign_id,
        candidates=candidates,
        priority_order=tuple(candidate.id for candidate in candidates),
        stages=stages,
        compute_policy=compute_policy,
        scientific_status=(
            "Architecture hypotheses and staged gates only; no candidate-specific properties are predicted, "
            "measured, admitted, or qualified."
        ),
    )


def write_fiber_discovery_plan(campaign_path: Path, output_dir: Path) -> FiberDiscoveryPlan:
    campaign = FiberV1Manifest.model_validate_json(campaign_path.read_text())
    proposed = make_fiber_discovery_plan(campaign)
    plan_path = output_dir / "plan.json"
    if plan_path.exists():
        existing = FiberDiscoveryPlan.model_validate_json(plan_path.read_text())
        if existing.plan_id != proposed.plan_id:
            raise RuntimeError("existing fiber discovery plan has a different immutable identity")
        return existing
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(proposed.model_dump_json(indent=2) + "\n")
    (output_dir / "candidates.json").write_text(
        "[\n"
        + ",\n".join(candidate.model_dump_json(indent=2) for candidate in proposed.candidates)
        + "\n]\n"
    )
    return proposed
