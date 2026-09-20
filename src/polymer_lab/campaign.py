"""Closed-loop campaign state machine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .errors import ApprovalRequired, BudgetExceeded, InvalidStateTransition
from .models import (
    AgentProposal,
    AgentStepResult,
    Approval,
    CampaignConfig,
    CampaignRecord,
    CampaignState,
    JobState,
    PhysicsJob,
    PhysicsResult,
    PolymerCandidate,
    Prediction,
    PropertyName,
    RankedCandidate,
    SimulationSpec,
)
from .optimization import rank_candidates, select_population
from .protocols import (
    ArtifactStore,
    CandidateGenerator,
    Executor,
    PhysicsEvaluator,
    PropertyPredictor,
    ResearchAgent,
)
from .repository import Repository


class CampaignEngine:
    def __init__(
        self,
        *,
        repository: Repository,
        predictor: PropertyPredictor,
        generator: CandidateGenerator,
        evaluator: PhysicsEvaluator,
        executor: Executor,
        agent: ResearchAgent,
        work_root: str | Path,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.repository = repository
        self.predictor = predictor
        self.generator = generator
        self.evaluator = evaluator
        self.executor = executor
        self.agent = agent
        self.artifact_store = artifact_store
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)

    def archive(self, campaign_id: str, *, rationale: str) -> CampaignRecord:
        """Retire a campaign and cancel every unfinished scheduler job.

        Archiving is deliberately terminal. Existing artifacts and observations
        remain immutable, but the agent can no longer continue the campaign.
        """

        if not rationale.strip():
            raise ValueError("campaign archival requires a rationale")
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state == CampaignState.ARCHIVED:
            return campaign
        cancelled: list[dict[str, str | None]] = []
        active_states = {
            JobState.CREATED,
            JobState.PENDING_APPROVAL,
            JobState.APPROVED,
            JobState.SUBMITTED,
            JobState.RUNNING,
            JobState.PREEMPTED,
        }
        for job in self.repository.jobs_for_campaign(campaign_id):
            if job.state not in active_states:
                continue
            if job.external_id:
                self.executor.cancel(job.external_id)
            self.repository.save_job(job.model_copy(update={"state": JobState.CANCELLED}))
            cancelled.append({"job_id": job.id, "external_id": job.external_id})
        archived = campaign.model_copy(
            update={"state": CampaignState.ARCHIVED, "updated_at": datetime.now(UTC)}
        )
        self.repository.save_campaign(archived)
        self.repository.record_event(
            campaign_id,
            "campaign.archived",
            {
                "rationale": rationale,
                "cancelled_jobs": cancelled,
                "artifacts_preserved": True,
                "eligible_for_agent_continuation": False,
            },
        )
        return archived

    def _archive_result(
        self,
        job: PhysicsJob,
        result_path: Path,
        result: PhysicsResult,
    ) -> dict[str, str]:
        if self.artifact_store is None:
            return {}
        root = result_path.parent.resolve()
        relative_paths = {
            Path("manifest.json"),
            Path(result_path.name),
            *(Path(item) for item in result.artifact_checksums),
        }
        uris: dict[str, str] = {}
        for relative_path in sorted(relative_paths, key=str):
            source = (root / relative_path).resolve()
            if root not in source.parents or not source.is_file():
                raise ValueError(f"artifact cannot be archived: {relative_path}")
            key = f"campaigns/{job.campaign_id}/jobs/{job.id}/{relative_path.as_posix()}"
            uris[relative_path.as_posix()] = self.artifact_store.put_file(key, source)
        return uris

    def _require_prediction_coverage(
        self,
        candidates: Sequence[PolymerCandidate],
        predictions: Sequence[Prediction],
        config: CampaignConfig,
    ) -> None:
        counts: dict[tuple[str, PropertyName], int] = {}
        objective_units = {objective.property: objective.unit for objective in config.objectives}
        for prediction in predictions:
            key = (prediction.candidate_id, prediction.property)
            counts[key] = counts.get(key, 0) + 1
            if prediction.model_version != self.predictor.version:
                raise ValueError("surrogate emitted a stale or inconsistent model version")
            if prediction.property in objective_units and prediction.unit != objective_units[prediction.property]:
                raise ValueError(f"surrogate emitted non-canonical unit for {prediction.property.value}")
        actual = set(counts)
        missing = [
            f"{candidate.id}:{objective.property.value}"
            for candidate in candidates
            for objective in config.objectives
            if (candidate.id, objective.property) not in actual
        ]
        if missing:
            raise ValueError(f"surrogate does not cover every campaign objective: {missing[:10]}")
        duplicates = [key for key, count in counts.items() if count != 1]
        if duplicates:
            raise ValueError(f"surrogate emitted duplicate predictions: {duplicates[:10]}")

    def create(self, config: CampaignConfig, seeds: Sequence[PolymerCandidate]) -> CampaignRecord:
        if not seeds:
            raise ValueError("a campaign requires at least one seed candidate")
        unique_seeds = list({candidate.structure_hash: candidate for candidate in seeds}.values())
        if len(unique_seeds) > config.max_candidates:
            raise BudgetExceeded("seed library exceeds max_candidates")
        persisted_seeds = [self.repository.save_candidate(candidate) for candidate in unique_seeds]
        campaign = CampaignRecord(config=config, candidate_count=len(persisted_seeds))
        self.repository.save_campaign(campaign)
        self.repository.attach_candidates(campaign.id, persisted_seeds, generation=0)
        self.repository.record_event(
            campaign.id,
            "campaign.created",
            {
                "seed_ids": [candidate.id for candidate in persisted_seeds],
                "config": config.model_dump(mode="json"),
            },
        )
        return campaign

    def start(self, campaign_id: str) -> CampaignRecord:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state != CampaignState.CREATED:
            raise InvalidStateTransition(f"campaign {campaign_id} is already started")
        candidates = self.repository.campaign_candidates(campaign_id, generation=0)
        predictions = self.predictor.predict(candidates)
        self._require_prediction_coverage(candidates, predictions, campaign.config)
        self.repository.save_predictions(predictions)
        updated = campaign.model_copy(
            update={
                "state": CampaignState.RUNNING,
                "latest_model_version": self.predictor.version,
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_campaign(updated)
        self.repository.record_event(
            campaign_id,
            "generation.predicted",
            {"generation": 0, "model_version": self.predictor.version, "count": len(candidates)},
        )
        return updated

    def ranked_population(self, campaign_id: str) -> list[RankedCandidate]:
        campaign = self.repository.get_campaign(campaign_id)
        candidates = self.repository.campaign_candidates(campaign_id, generation=campaign.generation)
        predictions = self.repository.predictions_for(
            [candidate.id for candidate in candidates], campaign.latest_model_version
        )
        return rank_candidates(candidates, predictions, campaign.config)

    def request_physics(
        self,
        campaign_id: str,
        *,
        spec: SimulationSpec,
        estimated_core_hours_per_job: float,
        count: int | None = None,
    ) -> list[PhysicsJob]:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state != CampaignState.RUNNING:
            raise InvalidStateTransition("physics can only be requested while a campaign is running")
        if count is not None and count < 1:
            raise ValueError("physics job count must be positive")
        if estimated_core_hours_per_job <= 0:
            raise ValueError("estimated_core_hours_per_job must be positive")
        existing_jobs = self.repository.jobs_for_campaign(campaign_id)
        requested_count = min(
            count if count is not None else campaign.config.physics_batch_size,
            campaign.config.physics_batch_size,
        )
        already_requested = {(job.candidate.id, job.spec.protocol_hash) for job in existing_jobs}
        ranked = [
            item
            for item in self.ranked_population(campaign_id)
            if (item.candidate.id, spec.protocol_hash) not in already_requested
        ]
        selected = ranked[:requested_count]
        if not selected:
            return []
        if len(existing_jobs) + len(selected) > campaign.config.max_physics_jobs:
            raise BudgetExceeded("physics request exceeds max_physics_jobs")
        estimated = len(selected) * estimated_core_hours_per_job
        committed = sum(job.estimated_core_hours for job in existing_jobs if job.state != JobState.CANCELLED)
        if committed + estimated > campaign.config.max_core_hours:
            raise BudgetExceeded("physics request exceeds max_core_hours")
        jobs: list[PhysicsJob] = []
        for item in selected:
            job_dir = self.work_root / campaign_id / item.candidate.id / spec.protocol_hash[:12]
            state = JobState.PENDING_APPROVAL if campaign.config.require_physics_approval else JobState.APPROVED
            job = PhysicsJob(
                campaign_id=campaign_id,
                candidate=item.candidate,
                spec=spec,
                artifact_uri=job_dir.as_uri(),
                estimated_core_hours=estimated_core_hours_per_job,
                state=state,
            )
            self.repository.save_job(job)
            self.evaluator.write_manifest(job, job_dir / "manifest.json")
            jobs.append(job)
        next_state = (
            CampaignState.WAITING_APPROVAL
            if campaign.config.require_physics_approval
            else CampaignState.WAITING_PHYSICS
        )
        self.repository.save_campaign(
            campaign.model_copy(update={"state": next_state, "updated_at": datetime.now(UTC)})
        )
        self.repository.record_event(
            campaign_id,
            "physics.requested",
            {
                "job_ids": [job.id for job in jobs],
                "candidate_ids": [job.candidate.id for job in jobs],
                "estimated_core_hours": sum(job.estimated_core_hours for job in jobs),
            },
        )
        return jobs

    def approve(
        self,
        campaign_id: str,
        job_ids: Sequence[str],
        *,
        approved_by: str,
        rationale: str,
        approved_core_hours: float | None = None,
    ) -> Approval:
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("approval job ids must be unique")
        jobs = [self.repository.get_job(job_id) for job_id in job_ids]
        if not jobs or any(job.campaign_id != campaign_id for job in jobs):
            raise ValueError("approval jobs must belong to the requested campaign")
        if any(job.state != JobState.PENDING_APPROVAL for job in jobs):
            raise InvalidStateTransition("only pending jobs can be approved")
        previously_approved = {
            job_id for approval in self.repository.approvals_for_campaign(campaign_id) for job_id in approval.job_ids
        }
        if previously_approved.intersection(job_ids):
            raise InvalidStateTransition("one or more jobs were already approved")
        requested = sum(job.estimated_core_hours for job in jobs)
        limit = approved_core_hours if approved_core_hours is not None else requested
        if limit < requested:
            raise ApprovalRequired("approval does not cover estimated job cost")
        approval = Approval(
            campaign_id=campaign_id,
            job_ids=tuple(job_ids),
            approved_core_hours=limit,
            approved_by=approved_by,
            rationale=rationale,
        )
        self.repository.save_approval(approval)
        for job in jobs:
            approved_job = job.model_copy(update={"state": JobState.APPROVED})
            self.repository.save_job(approved_job)
            manifest = Path(approved_job.artifact_uri.removeprefix("file://")) / "manifest.json"
            self.evaluator.write_manifest(approved_job, manifest)
        campaign = self.repository.get_campaign(campaign_id)
        self.repository.save_campaign(
            campaign.model_copy(update={"state": CampaignState.WAITING_PHYSICS, "updated_at": datetime.now(UTC)})
        )
        self.repository.record_event(
            campaign_id,
            "physics.approved",
            {"approval_id": approval.id, "job_ids": list(job_ids), "approved_by": approved_by},
        )
        return approval

    def submit_approved(self, campaign_id: str) -> list[PhysicsJob]:
        campaign = self.repository.get_campaign(campaign_id)
        approvals = self.repository.approvals_for_campaign(campaign_id)
        approved_ids = {job_id for approval in approvals for job_id in approval.job_ids}
        submitted: list[PhysicsJob] = []
        for job in self.repository.jobs_for_campaign(campaign_id):
            if job.state != JobState.APPROVED:
                continue
            if campaign.config.require_physics_approval and job.id not in approved_ids:
                raise ApprovalRequired(f"job {job.id} has no persisted approval")
            manifest = Path(job.artifact_uri.removeprefix("file://")) / "manifest.json"
            external_id = self.executor.submit(job, manifest)
            updated = job.model_copy(update={"state": JobState.SUBMITTED, "external_id": external_id})
            self.repository.save_job(updated)
            submitted.append(updated)
        if submitted:
            campaign = self.repository.get_campaign(campaign_id)
            self.repository.save_campaign(
                campaign.model_copy(
                    update={
                        "state": CampaignState.WAITING_PHYSICS,
                        "submitted_jobs": campaign.submitted_jobs + len(submitted),
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
            self.repository.record_event(
                campaign_id,
                "physics.submitted",
                {"jobs": {job.id: job.external_id for job in submitted}},
            )
        return submitted

    def poll(self, campaign_id: str) -> list[PhysicsJob]:
        updated_jobs: list[PhysicsJob] = []
        for job in self.repository.jobs_for_campaign(campaign_id):
            if job.state not in {JobState.SUBMITTED, JobState.RUNNING} or not job.external_id:
                continue
            state = self.executor.status(job.external_id)
            if state != job.state:
                updated = job.model_copy(update={"state": state})
                self.repository.save_job(updated)
                updated_jobs.append(updated)
        return updated_jobs

    def ingest_completed(self, campaign_id: str) -> list[str]:
        admitted: list[str] = []
        existing_observation_jobs = {
            event["payload"].get("job_id")
            for event in self.repository.events_for_campaign(campaign_id)
            if event["kind"] == "physics.admitted"
        }
        for job in self.repository.jobs_for_campaign(campaign_id):
            if job.state != JobState.SUCCEEDED or job.id in existing_observation_jobs:
                continue
            result_path = Path(job.artifact_uri.removeprefix("file://")) / "result.json"
            result = self.evaluator.read_result(job, result_path)
            artifact_uris = self._archive_result(job, result_path, result)
            self.repository.save_observations(result.observations)
            self.repository.record_event(
                campaign_id,
                "physics.admitted",
                {
                    "job_id": job.id,
                    "observation_ids": [item.id for item in result.observations],
                    "artifact_uris": artifact_uris,
                },
            )
            admitted.append(job.id)
        unfinished = any(
            job.state
            in {
                JobState.PENDING_APPROVAL,
                JobState.APPROVED,
                JobState.SUBMITTED,
                JobState.RUNNING,
                JobState.PREEMPTED,
            }
            for job in self.repository.jobs_for_campaign(campaign_id)
        )
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state == CampaignState.WAITING_PHYSICS and not unfinished:
            running = campaign.model_copy(update={"state": CampaignState.RUNNING, "updated_at": datetime.now(UTC)})
            self.repository.save_campaign(running)
            self.repository.record_event(
                campaign_id,
                "physics.batch_closed",
                {"admitted_job_ids": admitted},
            )
        return admitted

    def retrain_and_advance(
        self,
        campaign_id: str,
        *,
        preferred_mutations: Sequence[str] = (),
    ) -> CampaignRecord:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state not in {CampaignState.RUNNING, CampaignState.WAITING_PHYSICS}:
            raise InvalidStateTransition("retraining requires a running or physics-waiting campaign")
        unfinished = [
            job.id
            for job in self.repository.jobs_for_campaign(campaign_id)
            if job.state
            in {
                JobState.PENDING_APPROVAL,
                JobState.APPROVED,
                JobState.SUBMITTED,
                JobState.RUNNING,
                JobState.PREEMPTED,
            }
        ]
        if unfinished:
            raise InvalidStateTransition(f"physics batch is still unfinished: {unfinished}")
        all_candidates = self.repository.campaign_candidates(campaign_id, selected_only=False)
        examples = self.repository.training_examples()
        if not examples:
            raise ValueError("no admitted physics or experimental evidence is available for retraining")
        model_version = self.predictor.fit(examples)
        current = self.repository.campaign_candidates(campaign_id, generation=campaign.generation)
        current_predictions = self.predictor.predict(current)
        self._require_prediction_coverage(current, current_predictions, campaign.config)
        self.repository.save_predictions(current_predictions)
        ranked = rank_candidates(current, current_predictions, campaign.config)
        parents = select_population(ranked, min(len(ranked), campaign.config.population_size))
        next_generation = campaign.generation + 1
        remaining = campaign.config.max_candidates - campaign.candidate_count
        proposed_offspring = self.generator.generate(
            parents,
            min(campaign.config.offspring_size, remaining),
            next_generation,
            preferred_mutations=preferred_mutations,
        )
        known_hashes = {candidate.structure_hash for candidate in all_candidates}
        offspring: list[PolymerCandidate] = []
        for candidate in proposed_offspring:
            if candidate.structure_hash in known_hashes:
                continue
            persisted = self.repository.save_candidate(candidate)
            known_hashes.add(persisted.structure_hash)
            offspring.append(persisted)
        if offspring:
            self.repository.attach_candidates(
                campaign_id,
                offspring,
                generation=next_generation,
                selected=False,
            )
            offspring_predictions = self.predictor.predict(offspring)
            self._require_prediction_coverage(offspring, offspring_predictions, campaign.config)
            self.repository.save_predictions(offspring_predictions)
            combined = [*current, *offspring]
            combined_predictions = [*current_predictions, *offspring_predictions]
            survivor_ranking = rank_candidates(combined, combined_predictions, campaign.config)
            survivors = select_population(
                survivor_ranking,
                min(len(survivor_ranking), campaign.config.population_size),
            )
            self.repository.attach_candidates(
                campaign_id,
                survivors,
                generation=next_generation,
                selected=True,
            )
        else:
            survivors = []
        completed = next_generation >= campaign.config.max_generations or not offspring
        updated = campaign.model_copy(
            update={
                "state": CampaignState.COMPLETED if completed else CampaignState.RUNNING,
                "generation": next_generation,
                "candidate_count": len(all_candidates) + len(offspring),
                "latest_model_version": model_version,
                "consumed_core_hours": sum(
                    job.estimated_core_hours
                    for job in self.repository.jobs_for_campaign(campaign_id)
                    if job.state == JobState.SUCCEEDED
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_campaign(updated)
        self.repository.record_event(
            campaign_id,
            "generation.advanced",
            {
                "generation": next_generation,
                "parent_ids": [parent.id for parent in parents],
                "offspring_ids": [candidate.id for candidate in offspring],
                "survivor_ids": [candidate.id for candidate in survivors],
                "preferred_mutations": list(preferred_mutations),
                "admitted_job_count": sum(
                    event["kind"] == "physics.admitted" for event in self.repository.events_for_campaign(campaign_id)
                ),
                "model_version": model_version,
            },
        )
        return updated

    def agent_proposal(self, campaign_id: str) -> AgentProposal:
        campaign = self.repository.get_campaign(campaign_id)
        events = self.repository.events_for_campaign(campaign_id)
        candidates = self.repository.campaign_candidates(campaign_id)
        all_campaign_candidates = self.repository.campaign_candidates(campaign_id, selected_only=False)
        observations = self.repository.observations_for(candidate.id for candidate in all_campaign_candidates)
        frontier = self.ranked_population(campaign_id) if campaign.latest_model_version else []
        available_mutations = [mutation.name for mutation in getattr(self.generator, "mutations", ())]
        evidence = {
            "evidence_ids": [
                *[event["id"] for event in events],
                *[observation.id for observation in observations],
                *[candidate.id for candidate in candidates],
            ],
            "recent_events": events[-20:],
            "observations": [observation.model_dump(mode="json") for observation in observations[-50:]],
            "pareto_frontier": [
                {
                    "candidate_id": item.candidate.id,
                    "psmiles": item.candidate.canonical_psmiles,
                    "pareto_rank": item.pareto_rank,
                    "feasible": item.feasible,
                    "constraint_violation": item.constraint_violation,
                    "acquisition_score": item.acquisition_score,
                    "predictions": [prediction.model_dump(mode="json") for prediction in item.predictions],
                }
                for item in frontier[:20]
            ],
            "available_mutations": available_mutations,
            "completed_physics_jobs": sum(
                job.state == JobState.SUCCEEDED for job in self.repository.jobs_for_campaign(campaign_id)
            ),
            "last_retrain_job_count": max(
                (
                    event["payload"].get("admitted_job_count", 0)
                    for event in events
                    if event["kind"] == "generation.advanced"
                ),
                default=0,
            ),
            "generation": campaign.generation,
            "remaining_core_hours": campaign.config.max_core_hours - campaign.consumed_core_hours,
        }
        proposal = self.agent.propose(campaign, evidence)
        self.repository.record_event(
            campaign_id,
            "agent.proposed",
            proposal.model_dump(mode="json"),
        )
        return proposal

    def run_agent_step(
        self,
        campaign_id: str,
        *,
        spec: SimulationSpec,
        estimated_core_hours_per_job: float,
    ) -> AgentStepResult:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state == CampaignState.WAITING_PHYSICS:
            self.poll(campaign_id)
            self.ingest_completed(campaign_id)
        proposal = self.agent_proposal(campaign_id)
        campaign = self.repository.get_campaign(campaign_id)
        jobs: list[PhysicsJob] = []
        if proposal.action == "advance_generation":
            if campaign.state != CampaignState.CREATED:
                raise InvalidStateTransition("baseline prediction is only valid for a created campaign")
            campaign = self.start(campaign_id)
        elif proposal.action == "request_physics":
            jobs = self.request_physics(
                campaign_id,
                spec=spec,
                estimated_core_hours_per_job=estimated_core_hours_per_job,
                count=proposal.parameters.count,
            )
            if jobs and not campaign.config.require_physics_approval:
                self.submit_approved(campaign_id)
            campaign = self.repository.get_campaign(campaign_id)
        elif proposal.action == "retrain":
            campaign = self.retrain_and_advance(
                campaign_id,
                preferred_mutations=proposal.parameters.preferred_mutations,
            )
        elif proposal.action != "stop":
            raise InvalidStateTransition(f"unsupported agent action: {proposal.action}")
        self.repository.record_event(
            campaign_id,
            "agent.executed",
            {
                "action": proposal.action,
                "job_ids": [job.id for job in jobs],
                "resulting_state": campaign.state.value,
            },
        )
        return AgentStepResult(
            proposal=proposal,
            campaign=campaign,
            job_ids=tuple(job.id for job in jobs),
        )
