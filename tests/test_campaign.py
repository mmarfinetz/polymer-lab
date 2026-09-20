from __future__ import annotations

from pathlib import Path

import pytest

from polymer_lab.agent import DeterministicResearchAgent
from polymer_lab.artifacts import LocalArtifactStore
from polymer_lab.campaign import CampaignEngine
from polymer_lab.errors import ApprovalRequired
from polymer_lab.executors import RecordingExecutor
from polymer_lab.generation import GeneticMutationGenerator
from polymer_lab.models import (
    CampaignConfig,
    CampaignState,
    JobState,
    Observation,
    PhysicsResult,
    PropertyName,
    Provenance,
    SimulationSpec,
)
from polymer_lab.physics import RadonPyEvaluator
from polymer_lab.predictor import DeterministicSurrogate
from polymer_lab.repository import SQLiteRepository
from polymer_lab.validation import BasicPSmilesValidator


def _engine(tmp_path) -> tuple[CampaignEngine, RecordingExecutor]:
    validator = BasicPSmilesValidator()
    executor = RecordingExecutor()
    return (
        CampaignEngine(
            repository=SQLiteRepository(tmp_path / "lab.sqlite3"),
            predictor=DeterministicSurrogate(),
            generator=GeneticMutationGenerator(validator, random_seed=1),
            evaluator=RadonPyEvaluator(),
            executor=executor,
            agent=DeterministicResearchAgent(),
            work_root=tmp_path / "jobs",
        ),
        executor,
    )


def test_approval_gates_submission_and_result_closes_learning_loop(tmp_path) -> None:
    engine, executor = _engine(tmp_path)
    engine.artifact_store = LocalArtifactStore(tmp_path / "archive")
    validator = BasicPSmilesValidator()
    seeds = [
        validator.validate("[*]CC([*])c1ccccc1"),
        validator.validate("[*]COc1ccc(cc1)OC[*]"),
        validator.validate("[*]CC[*]"),
    ]
    config = CampaignConfig(
        name="loop",
        population_size=3,
        offspring_size=2,
        physics_batch_size=1,
        max_generations=3,
        max_candidates=20,
        max_core_hours=100,
        max_physics_jobs=3,
    )
    campaign = engine.create(config, seeds)
    campaign = engine.start(campaign.id)
    jobs = engine.request_physics(
        campaign.id,
        spec=SimulationSpec(),
        estimated_core_hours_per_job=20,
    )
    assert engine.repository.get_campaign(campaign.id).state == CampaignState.WAITING_APPROVAL
    assert engine.submit_approved(campaign.id) == []
    approval = engine.approve(
        campaign.id,
        [jobs[0].id],
        approved_by="scientist@example.edu",
        rationale="first active-learning batch",
    )
    assert approval.job_ids == (jobs[0].id,)
    submitted = engine.submit_approved(campaign.id)
    assert len(submitted) == 1
    external_id = submitted[0].external_id
    assert external_id is not None
    executor.states[external_id] = JobState.SUCCEEDED
    engine.poll(campaign.id)

    job = engine.repository.get_job(jobs[0].id)
    result = PhysicsResult(
        job_id=job.id,
        candidate_id=job.candidate.id,
        protocol_hash=job.spec.protocol_hash,
        converged=True,
        software_versions={
            "radonpy": "1.0b2",
            "rdkit": "test",
            "psi4": "1.10",
            "lammps": "test",
        },
        observations=(
            Observation(
                candidate_id=job.candidate.id,
                property=PropertyName.DENSITY,
                value=1.01,
                unit="g/cm^3",
                provenance=Provenance.MD,
                protocol_hash=job.spec.protocol_hash,
            ),
            Observation(
                candidate_id=job.candidate.id,
                property=PropertyName.TG,
                value=205,
                unit="degC",
                provenance=Provenance.MD,
                protocol_hash=job.spec.protocol_hash,
            ),
        ),
    )
    result_path = Path(job.artifact_uri.removeprefix("file://")) / "result.json"
    result_path.write_text(result.model_dump_json())
    assert engine.ingest_completed(campaign.id) == [job.id]
    advanced = engine.retrain_and_advance(campaign.id)
    assert advanced.generation == 1
    assert advanced.latest_model_version == "deterministic-test-v1-n2"
    assert advanced.candidate_count > len(seeds)
    assert engine.repository.observations_for([job.candidate.id])
    next_population = engine.repository.campaign_candidates(campaign.id, generation=1)
    all_generated = engine.repository.campaign_candidates(campaign.id, selected_only=False)
    assert len(next_population) == config.population_size
    assert len(all_generated) == advanced.candidate_count
    event = next(
        item for item in engine.repository.events_for_campaign(campaign.id) if item["kind"] == "generation.advanced"
    )
    assert {candidate.id for candidate in next_population} == set(event["payload"]["survivor_ids"])
    admitted_event = next(
        item for item in engine.repository.events_for_campaign(campaign.id) if item["kind"] == "physics.admitted"
    )
    assert set(admitted_event["payload"]["artifact_uris"]) == {
        "manifest.json",
        "result.json",
    }


def test_approval_must_cover_estimated_cost(tmp_path) -> None:
    engine, _ = _engine(tmp_path)
    candidate = BasicPSmilesValidator().validate("[*]CC[*]")
    campaign = engine.start(engine.create(CampaignConfig(name="budget"), [candidate]).id)
    job = engine.request_physics(campaign.id, spec=SimulationSpec(), estimated_core_hours_per_job=20, count=1)[0]
    with pytest.raises(ApprovalRequired):
        engine.approve(
            campaign.id,
            [job.id],
            approved_by="scientist",
            rationale="insufficient",
            approved_core_hours=10,
        )


def test_agent_step_starts_campaign_then_requests_gated_physics(tmp_path) -> None:
    engine, _ = _engine(tmp_path)
    validator = BasicPSmilesValidator()
    seeds = [
        validator.validate("[*]CC[*]"),
        validator.validate("[*]COC[*]"),
    ]
    config = CampaignConfig(
        name="agent-loop",
        population_size=2,
        physics_batch_size=1,
        max_physics_jobs=2,
    )
    campaign = engine.create(config, seeds)
    baseline = engine.run_agent_step(
        campaign.id,
        spec=SimulationSpec(),
        estimated_core_hours_per_job=10,
    )
    assert baseline.proposal.action == "advance_generation"
    assert baseline.campaign.state == CampaignState.RUNNING
    physics = engine.run_agent_step(
        campaign.id,
        spec=SimulationSpec(),
        estimated_core_hours_per_job=10,
    )
    assert physics.proposal.action == "request_physics"
    assert len(physics.job_ids) == 1
    assert physics.campaign.state == CampaignState.WAITING_APPROVAL


def test_archiving_cancels_active_jobs_and_terminates_campaign(tmp_path) -> None:
    engine, executor = _engine(tmp_path)
    candidate = BasicPSmilesValidator().validate("[*]CC[*]")
    config = CampaignConfig(name="obsolete", physics_batch_size=1, max_physics_jobs=1)
    campaign = engine.start(engine.create(config, [candidate]).id)
    job = engine.request_physics(
        campaign.id,
        spec=SimulationSpec(),
        estimated_core_hours_per_job=10,
    )[0]
    engine.approve(
        campaign.id,
        [job.id],
        approved_by="scientist",
        rationale="test approval",
    )
    submitted = engine.submit_approved(campaign.id)[0]

    archived = engine.archive(campaign.id, rationale="objective changed to fiber-v1")

    assert archived.state == CampaignState.ARCHIVED
    assert submitted.external_id is not None
    assert executor.states[submitted.external_id] == JobState.CANCELLED
    assert engine.repository.get_job(job.id).state == JobState.CANCELLED
    event = engine.repository.events_for_campaign(campaign.id)[-1]
    assert event["kind"] == "campaign.archived"
    assert not event["payload"]["eligible_for_agent_continuation"]
