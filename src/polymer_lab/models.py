"""Typed, immutable domain contracts shared by every adapter."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PropertyName(StrEnum):
    TG = "tg"
    DENSITY = "density"


class Provenance(StrEnum):
    EXPERIMENTAL = "experimental"
    SURROGATE = "surrogate"
    MD = "md"
    DFT = "dft"


class JobState(StrEnum):
    CREATED = "created"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PREEMPTED = "preempted"


class CampaignState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_PHYSICS = "waiting_physics"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class Objective(FrozenModel):
    property: PropertyName
    direction: Literal["minimize", "maximize"]
    threshold: float
    unit: str


DEFAULT_OBJECTIVES = (
    Objective(property=PropertyName.TG, direction="maximize", threshold=180.0, unit="degC"),
    Objective(property=PropertyName.DENSITY, direction="minimize", threshold=1.2, unit="g/cm^3"),
)


class PolymerCandidate(FrozenModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    psmiles: str
    canonical_psmiles: str
    structure_hash: str
    architecture: Literal["linear_homopolymer"] = "linear_homopolymer"
    parent_ids: tuple[str, ...] = ()
    generation_method: str = "seed"
    generation: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Prediction(FrozenModel):
    candidate_id: str
    property: PropertyName
    mean: float
    uncertainty: float = Field(ge=0)
    unit: str
    model_version: str
    created_at: datetime = Field(default_factory=utc_now)


class TrainingExample(FrozenModel):
    candidate: PolymerCandidate
    observation: Observation


class Observation(FrozenModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str
    property: PropertyName
    value: float
    unit: str
    uncertainty: float | None = Field(default=None, ge=0)
    provenance: Provenance
    protocol_hash: str
    source_reference: str | None = None
    converged: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SimulationSpec(FrozenModel):
    profile: Literal["smoke", "production"] = "production"
    target_atoms_per_chain: int = Field(default=1000, ge=10)
    chain_count: int = Field(default=10, ge=1)
    initial_density_g_cm3: float = Field(default=0.05, gt=0)
    tacticity: Literal["atactic"] = "atactic"
    force_field: str = "GAFF2_mod"
    charge_method: str = "RESP"
    temperature_k: float = Field(default=300.0, gt=0)
    pressure_atm: float = Field(default=1.0, gt=0)
    tg_cooling_rate_k_per_ns: Literal[8000.0] = 8000.0
    random_seed: int = Field(default=1, ge=0)
    radonpy_version: str = "1.0b2"
    rdkit_version: str = "environment"
    psi4_version: str = "1.10"
    lammps_version: str = "stable"
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def protocol_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class PhysicsJob(FrozenModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    candidate: PolymerCandidate
    spec: SimulationSpec
    requested_properties: tuple[PropertyName, ...] = (
        PropertyName.DENSITY,
        PropertyName.TG,
    )
    artifact_uri: str
    estimated_core_hours: float = Field(gt=0)
    state: JobState = JobState.PENDING_APPROVAL
    external_id: str | None = None
    retry_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def manifest_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"state", "external_id", "retry_count"})
        return stable_hash(payload)


class PhysicsResult(FrozenModel):
    job_id: str
    candidate_id: str
    protocol_hash: str
    observations: tuple[Observation, ...]
    converged: bool
    software_versions: dict[str, str]
    artifact_checksums: dict[str, str] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class Approval(FrozenModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    job_ids: tuple[str, ...]
    approved_core_hours: float = Field(gt=0)
    approved_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class CampaignConfig(FrozenModel):
    name: str = Field(min_length=1)
    objectives: tuple[Objective, ...] = DEFAULT_OBJECTIVES
    population_size: int = Field(default=100, ge=2)
    offspring_size: int = Field(default=100, ge=1)
    physics_batch_size: int = Field(default=10, ge=1)
    max_generations: int = Field(default=5, ge=1)
    max_candidates: int = Field(default=10_000, ge=1)
    max_core_hours: float = Field(default=1_000.0, gt=0)
    max_physics_jobs: int = Field(default=50, ge=1)
    uncertainty_weight: float = Field(default=0.25, ge=0)
    diversity_weight: float = Field(default=0.15, ge=0)
    random_seed: int = Field(default=42, ge=0)
    require_physics_approval: bool = True

    @model_validator(mode="after")
    def coherent_limits_and_objectives(self) -> CampaignConfig:
        if self.population_size > self.max_candidates:
            raise ValueError("population_size cannot exceed max_candidates")
        if self.physics_batch_size > self.max_physics_jobs:
            raise ValueError("physics_batch_size cannot exceed max_physics_jobs")
        properties = [objective.property for objective in self.objectives]
        if len(properties) != len(set(properties)):
            raise ValueError("campaign objectives must use unique properties")
        canonical_units = {
            PropertyName.TG: "degC",
            PropertyName.DENSITY: "g/cm^3",
        }
        for objective in self.objectives:
            if objective.unit != canonical_units[objective.property]:
                raise ValueError(
                    f"{objective.property.value} objective must use canonical unit "
                    f"{canonical_units[objective.property]!r}"
                )
        return self


class CampaignRecord(FrozenModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    config: CampaignConfig
    state: CampaignState = CampaignState.CREATED
    generation: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    submitted_jobs: int = Field(default=0, ge=0)
    consumed_core_hours: float = Field(default=0.0, ge=0)
    latest_model_version: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RankedCandidate(FrozenModel):
    candidate: PolymerCandidate
    predictions: tuple[Prediction, ...]
    pareto_rank: int = Field(ge=0)
    crowding_distance: float = Field(ge=0)
    constraint_violation: float = Field(ge=0)
    acquisition_score: float
    feasible: bool


class ProposalParameters(FrozenModel):
    count: int | None = Field(default=None, ge=1)
    preferred_mutations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_mutations(self) -> ProposalParameters:
        if len(self.preferred_mutations) != len(set(self.preferred_mutations)):
            raise ValueError("preferred mutation strategies must be unique")
        return self


class AgentProposal(FrozenModel):
    action: Literal["advance_generation", "request_physics", "retrain", "stop"]
    rationale: str
    evidence_ids: tuple[str, ...]
    parameters: ProposalParameters = Field(default_factory=ProposalParameters)


class AgentStepResult(FrozenModel):
    proposal: AgentProposal
    campaign: CampaignRecord
    job_ids: tuple[str, ...] = ()
