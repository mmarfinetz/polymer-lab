"""User-facing Python façade."""

from __future__ import annotations

from pathlib import Path

from .agent import DeterministicResearchAgent, OpenAIResearchAgent
from .artifacts import LocalArtifactStore
from .campaign import CampaignEngine
from .datasets import IngestBatch
from .executors import LocalExecutor, RecordingExecutor, SlurmConfig, SlurmExecutor
from .generation import GeneticMutationGenerator
from .models import CampaignConfig, PolymerCandidate
from .physics import RadonPyEvaluator
from .predictor import DeterministicSurrogate
from .protocols import ArtifactStore, PropertyPredictor, ResearchAgent
from .repository import PostgresRepository, SQLiteRepository
from .validation import BasicPSmilesValidator, RDKitPSmilesValidator


class PolymerLab:
    def __init__(self, engine: CampaignEngine) -> None:
        self.engine = engine

    @classmethod
    def development(
        cls,
        root: str | Path,
        *,
        scientific_validation: bool = False,
    ) -> PolymerLab:
        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        repository = SQLiteRepository(root_path / "polymer_lab.sqlite3")
        validator = RDKitPSmilesValidator() if scientific_validation else BasicPSmilesValidator()
        predictor = DeterministicSurrogate()
        engine = CampaignEngine(
            repository=repository,
            predictor=predictor,
            generator=GeneticMutationGenerator(validator),
            evaluator=RadonPyEvaluator(),
            executor=RecordingExecutor(),
            agent=DeterministicResearchAgent(),
            work_root=root_path / "jobs",
        )
        return cls(engine)

    @classmethod
    def production(
        cls,
        *,
        database_url: str,
        work_root: str | Path,
        predictor: PropertyPredictor,
        artifact_store: ArtifactStore,
        slurm: SlurmConfig,
        openai_model: str = "gpt-5.6-terra",
        apply_migrations: bool = False,
    ) -> PolymerLab:
        if Path(work_root).resolve() != slurm.workdir.resolve():
            raise ValueError("work_root and SlurmConfig.workdir must identify the same shared path")
        repository = PostgresRepository(database_url, apply_migrations=apply_migrations)
        validator = RDKitPSmilesValidator()
        engine = CampaignEngine(
            repository=repository,
            predictor=predictor,
            generator=GeneticMutationGenerator(validator),
            evaluator=RadonPyEvaluator(),
            executor=SlurmExecutor(slurm),
            agent=OpenAIResearchAgent(model=openai_model),
            work_root=work_root,
            artifact_store=artifact_store,
        )
        return cls(engine)

    @classmethod
    def scientific_local(
        cls,
        root: str | Path,
        *,
        predictor: PropertyPredictor,
        research_agent: str = "deterministic",
        openai_model: str = "gpt-5.6-terra",
        reasoning_effort: str = "medium",
        executor: str = "recording",
    ) -> PolymerLab:
        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        repository = SQLiteRepository(root_path / "polymer_lab.sqlite3")
        validator = RDKitPSmilesValidator()
        if research_agent == "deterministic":
            agent: ResearchAgent = DeterministicResearchAgent()
        elif research_agent == "openai":
            agent = OpenAIResearchAgent(model=openai_model, reasoning_effort=reasoning_effort)
        else:
            raise ValueError("research_agent must be 'deterministic' or 'openai'")
        if executor == "recording":
            physics_executor = RecordingExecutor()
        elif executor == "local":
            physics_executor = LocalExecutor()
        else:
            raise ValueError("executor must be 'recording' or 'local'")
        engine = CampaignEngine(
            repository=repository,
            predictor=predictor,
            generator=GeneticMutationGenerator(validator),
            evaluator=RadonPyEvaluator(),
            executor=physics_executor,
            agent=agent,
            work_root=root_path / "jobs",
            artifact_store=LocalArtifactStore(root_path / "artifacts"),
        )
        return cls(engine)

    @classmethod
    def scientific_slurm(
        cls,
        root: str | Path,
        *,
        predictor: PropertyPredictor,
        slurm: SlurmConfig,
        research_agent: str = "deterministic",
        openai_model: str = "gpt-5.6-terra",
        reasoning_effort: str = "medium",
    ) -> PolymerLab:
        """Build a durable SQLite coordinator whose approved jobs go to Slurm.

        The coordinator and workers must share ``root`` (or a filesystem mounted at
        the same path). Slurm submission occurs only after ``engine.approve``.
        """
        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        if root_path != slurm.workdir.resolve():
            raise ValueError("root and SlurmConfig.workdir must identify the same shared path")
        repository = SQLiteRepository(root_path / "polymer_lab.sqlite3")
        validator = RDKitPSmilesValidator()
        if research_agent == "deterministic":
            agent: ResearchAgent = DeterministicResearchAgent()
        elif research_agent == "openai":
            agent = OpenAIResearchAgent(model=openai_model, reasoning_effort=reasoning_effort)
        else:
            raise ValueError("research_agent must be 'deterministic' or 'openai'")
        engine = CampaignEngine(
            repository=repository,
            predictor=predictor,
            generator=GeneticMutationGenerator(validator),
            evaluator=RadonPyEvaluator(),
            executor=SlurmExecutor(slurm),
            agent=agent,
            work_root=root_path / "jobs",
            artifact_store=LocalArtifactStore(root_path / "artifacts"),
        )
        return cls(engine)

    def candidate(self, psmiles: str) -> PolymerCandidate:
        validator = getattr(self.engine.generator, "validator", BasicPSmilesValidator())
        return validator.validate(psmiles)

    def create_campaign(
        self,
        config: CampaignConfig,
        seeds: list[PolymerCandidate],
    ):
        return self.engine.create(config, seeds)

    def ingest(self, batch: IngestBatch) -> None:
        persisted_ids: dict[str, str] = {}
        for candidate in batch.candidates:
            saved = self.engine.repository.save_candidate(candidate)
            persisted_ids[candidate.id] = saved.id
        if batch.observations:
            self.engine.repository.save_observations(
                observation.model_copy(
                    update={"candidate_id": persisted_ids.get(observation.candidate_id, observation.candidate_id)}
                )
                for observation in batch.observations
            )
