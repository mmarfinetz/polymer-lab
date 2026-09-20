"""Stable provider interfaces for scientific and infrastructure adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from .models import (
    AgentProposal,
    CampaignRecord,
    JobState,
    PhysicsJob,
    PhysicsResult,
    PolymerCandidate,
    Prediction,
)


class CandidateValidator(Protocol):
    def validate(
        self,
        psmiles: str,
        *,
        parent_ids: Sequence[str] = (),
        generation_method: str = "seed",
        generation: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> PolymerCandidate: ...


class CandidateGenerator(Protocol):
    def generate(
        self,
        parents: Sequence[PolymerCandidate],
        count: int,
        generation: int,
        *,
        preferred_mutations: Sequence[str] = (),
    ) -> list[PolymerCandidate]: ...


class PropertyPredictor(Protocol):
    @property
    def version(self) -> str: ...

    def fit(self, observations: Iterable[Any]) -> str: ...

    def predict(self, candidates: Sequence[PolymerCandidate]) -> list[Prediction]: ...


class Executor(Protocol):
    def submit(self, job: PhysicsJob, manifest_path: Path) -> str: ...

    def status(self, external_id: str) -> JobState: ...

    def cancel(self, external_id: str) -> None: ...


class PhysicsEvaluator(Protocol):
    def write_manifest(self, job: PhysicsJob, destination: Path) -> Path: ...

    def read_result(self, job: PhysicsJob, source: Path) -> PhysicsResult: ...


class ResearchAgent(Protocol):
    def propose(self, campaign: CampaignRecord, evidence: Mapping[str, Any]) -> AgentProposal: ...


class ArtifactStore(Protocol):
    def put_bytes(self, key: str, data: bytes) -> str: ...

    def put_file(self, key: str, source: Path) -> str: ...

    def get_bytes(self, uri: str) -> bytes: ...

    def exists(self, uri: str) -> bool: ...
