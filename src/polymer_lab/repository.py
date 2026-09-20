"""Persistence ports plus a dependency-free SQLite development implementation."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .errors import DependencyUnavailable, InvalidStateTransition
from .models import (
    Approval,
    CampaignRecord,
    CampaignState,
    JobState,
    Observation,
    PhysicsJob,
    PolymerCandidate,
    Prediction,
    TrainingExample,
)


class Repository(Protocol):
    def save_candidate(self, candidate: PolymerCandidate) -> PolymerCandidate: ...

    def attach_candidates(
        self,
        campaign_id: str,
        candidates: Iterable[PolymerCandidate],
        generation: int | None = None,
        selected: bool = True,
    ) -> None: ...

    def campaign_candidates(
        self,
        campaign_id: str,
        generation: int | None = None,
        *,
        selected_only: bool = True,
    ) -> list[PolymerCandidate]: ...

    def save_predictions(self, predictions: Iterable[Prediction]) -> None: ...

    def predictions_for(self, candidate_ids: Iterable[str], model_version: str | None = None) -> list[Prediction]: ...

    def save_observations(self, observations: Iterable[Observation]) -> None: ...

    def observations_for(self, candidate_ids: Iterable[str] = ()) -> list[Observation]: ...

    def training_examples(self) -> list[TrainingExample]: ...

    def save_campaign(self, campaign: CampaignRecord) -> None: ...

    def get_campaign(self, campaign_id: str) -> CampaignRecord: ...

    def save_job(self, job: PhysicsJob) -> None: ...

    def get_job(self, job_id: str) -> PhysicsJob: ...

    def jobs_for_campaign(self, campaign_id: str) -> list[PhysicsJob]: ...

    def save_approval(self, approval: Approval) -> None: ...

    def approvals_for_campaign(self, campaign_id: str) -> list[Approval]: ...

    def record_event(self, campaign_id: str, kind: str, payload: dict[str, Any]) -> str: ...

    def events_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]: ...


CAMPAIGN_TRANSITIONS: dict[CampaignState, set[CampaignState]] = {
    CampaignState.CREATED: {CampaignState.RUNNING, CampaignState.FAILED, CampaignState.ARCHIVED},
    CampaignState.RUNNING: {
        CampaignState.WAITING_APPROVAL,
        CampaignState.WAITING_PHYSICS,
        CampaignState.COMPLETED,
        CampaignState.FAILED,
        CampaignState.ARCHIVED,
    },
    CampaignState.WAITING_APPROVAL: {
        CampaignState.WAITING_PHYSICS,
        CampaignState.RUNNING,
        CampaignState.FAILED,
        CampaignState.ARCHIVED,
    },
    CampaignState.WAITING_PHYSICS: {
        CampaignState.RUNNING,
        CampaignState.COMPLETED,
        CampaignState.FAILED,
        CampaignState.ARCHIVED,
    },
    CampaignState.COMPLETED: {CampaignState.ARCHIVED},
    CampaignState.FAILED: {CampaignState.ARCHIVED},
    CampaignState.ARCHIVED: set(),
}


JOB_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.CREATED: {JobState.PENDING_APPROVAL, JobState.APPROVED, JobState.CANCELLED},
    JobState.PENDING_APPROVAL: {JobState.APPROVED, JobState.CANCELLED},
    JobState.APPROVED: {JobState.SUBMITTED, JobState.CANCELLED},
    JobState.SUBMITTED: {
        JobState.RUNNING,
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.PREEMPTED,
        JobState.CANCELLED,
    },
    JobState.RUNNING: {JobState.SUCCEEDED, JobState.FAILED, JobState.PREEMPTED, JobState.CANCELLED},
    JobState.PREEMPTED: {JobState.SUBMITTED, JobState.CANCELLED},
    JobState.SUCCEEDED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


class SQLiteRepository:
    """Small, auditable development store with the same domain semantics as PostgreSQL."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def close(self) -> None:
        self._connection.close()

    def _migrate(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "migrations" / "001_initial.sql"
        if schema_path.exists():
            schema = schema_path.read_text()
        else:
            raise RuntimeError(f"missing schema migration: {schema_path}")
        with self._connection:
            self._connection.executescript(schema)

    def save_candidate(self, candidate: PolymerCandidate) -> PolymerCandidate:
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT payload FROM candidates WHERE structure_hash = ?",
                (candidate.structure_hash,),
            ).fetchone()
            if existing:
                return PolymerCandidate.model_validate_json(existing["payload"])
            self._connection.execute(
                "INSERT INTO candidates (id, structure_hash, canonical_psmiles, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    candidate.id,
                    candidate.structure_hash,
                    candidate.canonical_psmiles,
                    candidate.model_dump_json(),
                    candidate.created_at.isoformat(),
                ),
            )
        return candidate

    def attach_candidates(
        self,
        campaign_id: str,
        candidates: Iterable[PolymerCandidate],
        generation: int | None = None,
        selected: bool = True,
    ) -> None:
        with self._lock, self._connection:
            for candidate in candidates:
                saved = self.save_candidate(candidate)
                self._connection.execute(
                    """INSERT INTO campaign_candidates
                       (campaign_id, candidate_id, generation, selected) VALUES (?, ?, ?, ?)
                       ON CONFLICT (campaign_id, candidate_id, generation)
                       DO UPDATE SET selected = MAX(selected, excluded.selected)""",
                    (
                        campaign_id,
                        saved.id,
                        saved.generation if generation is None else generation,
                        int(selected),
                    ),
                )

    def campaign_candidates(
        self,
        campaign_id: str,
        generation: int | None = None,
        *,
        selected_only: bool = True,
    ) -> list[PolymerCandidate]:
        query = (
            "SELECT DISTINCT c.payload, c.created_at FROM candidates c "
            "JOIN campaign_candidates cc ON c.id = cc.candidate_id "
            "WHERE cc.campaign_id = ?"
        )
        args: list[Any] = [campaign_id]
        if generation is not None:
            query += " AND cc.generation = ?"
            args.append(generation)
        if selected_only:
            query += " AND cc.selected = 1"
        query += " ORDER BY c.created_at"
        rows = self._connection.execute(query, args).fetchall()
        return [PolymerCandidate.model_validate_json(row["payload"]) for row in rows]

    def save_predictions(self, predictions: Iterable[Prediction]) -> None:
        with self._lock, self._connection:
            for prediction in predictions:
                self._connection.execute(
                    """INSERT OR REPLACE INTO predictions
                       (candidate_id, property, model_version, payload, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        prediction.candidate_id,
                        prediction.property.value,
                        prediction.model_version,
                        prediction.model_dump_json(),
                        prediction.created_at.isoformat(),
                    ),
                )

    def predictions_for(self, candidate_ids: Iterable[str], model_version: str | None = None) -> list[Prediction]:
        ids = tuple(candidate_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        query = f"SELECT payload FROM predictions WHERE candidate_id IN ({placeholders})"
        args: list[Any] = list(ids)
        if model_version:
            query += " AND model_version = ?"
            args.append(model_version)
        rows = self._connection.execute(query, args).fetchall()
        return [Prediction.model_validate_json(row["payload"]) for row in rows]

    def save_observations(self, observations: Iterable[Observation]) -> None:
        with self._lock, self._connection:
            for observation in observations:
                self._connection.execute(
                    """INSERT OR IGNORE INTO observations
                       (id, candidate_id, property, provenance, protocol_hash, payload, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        observation.id,
                        observation.candidate_id,
                        observation.property.value,
                        observation.provenance.value,
                        observation.protocol_hash,
                        observation.model_dump_json(),
                        observation.created_at.isoformat(),
                    ),
                )

    def observations_for(self, candidate_ids: Iterable[str] = ()) -> list[Observation]:
        ids = tuple(candidate_ids)
        query = "SELECT payload FROM observations"
        args: list[Any] = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            query += f" WHERE candidate_id IN ({placeholders})"
            args.extend(ids)
        query += " ORDER BY created_at"
        rows = self._connection.execute(query, args).fetchall()
        return [Observation.model_validate_json(row["payload"]) for row in rows]

    def training_examples(self) -> list[TrainingExample]:
        rows = self._connection.execute(
            """SELECT c.payload AS candidate_payload, o.payload AS observation_payload
               FROM observations o JOIN candidates c ON c.id = o.candidate_id
               ORDER BY o.created_at"""
        ).fetchall()
        return [
            TrainingExample(
                candidate=PolymerCandidate.model_validate_json(row["candidate_payload"]),
                observation=Observation.model_validate_json(row["observation_payload"]),
            )
            for row in rows
        ]

    def save_campaign(self, campaign: CampaignRecord) -> None:
        with self._lock, self._connection:
            existing = self._connection.execute("SELECT payload FROM campaigns WHERE id = ?", (campaign.id,)).fetchone()
            if existing:
                previous = CampaignRecord.model_validate_json(existing["payload"])
                if campaign.state != previous.state and campaign.state not in CAMPAIGN_TRANSITIONS[previous.state]:
                    raise InvalidStateTransition(f"campaign {campaign.id}: {previous.state} -> {campaign.state}")
            self._connection.execute(
                """INSERT OR REPLACE INTO campaigns (id, state, payload, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    campaign.id,
                    campaign.state.value,
                    campaign.model_dump_json(),
                    campaign.updated_at.isoformat(),
                ),
            )

    def get_campaign(self, campaign_id: str) -> CampaignRecord:
        row = self._connection.execute("SELECT payload FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            raise KeyError(campaign_id)
        return CampaignRecord.model_validate_json(row["payload"])

    def save_job(self, job: PhysicsJob) -> None:
        with self._lock, self._connection:
            existing = self._connection.execute("SELECT payload FROM physics_jobs WHERE id = ?", (job.id,)).fetchone()
            if existing:
                previous = PhysicsJob.model_validate_json(existing["payload"])
                if job.state != previous.state and job.state not in JOB_TRANSITIONS[previous.state]:
                    raise InvalidStateTransition(f"job {job.id}: {previous.state} -> {job.state}")
            self._connection.execute(
                """INSERT OR REPLACE INTO physics_jobs
                   (id, campaign_id, candidate_id, state, manifest_hash, payload, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id,
                    job.campaign_id,
                    job.candidate.id,
                    job.state.value,
                    job.manifest_hash,
                    job.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_job(self, job_id: str) -> PhysicsJob:
        row = self._connection.execute("SELECT payload FROM physics_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return PhysicsJob.model_validate_json(row["payload"])

    def jobs_for_campaign(self, campaign_id: str) -> list[PhysicsJob]:
        rows = self._connection.execute(
            "SELECT payload FROM physics_jobs WHERE campaign_id = ? ORDER BY updated_at",
            (campaign_id,),
        ).fetchall()
        return [PhysicsJob.model_validate_json(row["payload"]) for row in rows]

    def save_approval(self, approval: Approval) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO approvals (id, campaign_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    approval.id,
                    approval.campaign_id,
                    approval.model_dump_json(),
                    approval.created_at.isoformat(),
                ),
            )

    def approvals_for_campaign(self, campaign_id: str) -> list[Approval]:
        rows = self._connection.execute(
            "SELECT payload FROM approvals WHERE campaign_id = ? ORDER BY created_at",
            (campaign_id,),
        ).fetchall()
        return [Approval.model_validate_json(row["payload"]) for row in rows]

    def record_event(self, campaign_id: str, kind: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO audit_events (id, campaign_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    event_id,
                    campaign_id,
                    kind,
                    json.dumps(payload, sort_keys=True, default=str),
                    created_at,
                ),
            )
        return event_id

    def events_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT id, kind, payload, created_at FROM audit_events WHERE campaign_id = ? ORDER BY created_at",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class PostgresRepository:
    """Production PostgreSQL implementation using JSONB domain snapshots."""

    def __init__(self, database_url: str, *, apply_migrations: bool = False) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise DependencyUnavailable("PostgreSQL persistence requires polymer-lab[postgres]") from exc
        self.Jsonb = Jsonb
        self.connection = psycopg.connect(database_url, row_factory=dict_row)
        self._lock = threading.RLock()
        if apply_migrations:
            self.migrate()

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        path = Path(__file__).resolve().parents[2] / "migrations" / "001_initial_postgres.sql"
        statements = [statement.strip() for statement in path.read_text().split(";") if statement.strip()]
        with self.connection.transaction():
            for statement in statements:
                self.connection.execute(statement)

    @staticmethod
    def _payload(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="json")

    def save_candidate(self, candidate: PolymerCandidate) -> PolymerCandidate:
        with self._lock, self.connection.transaction():
            row = self.connection.execute(
                """INSERT INTO candidates (id, structure_hash, canonical_psmiles, payload, created_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (structure_hash) DO NOTHING RETURNING payload""",
                (
                    candidate.id,
                    candidate.structure_hash,
                    candidate.canonical_psmiles,
                    self.Jsonb(self._payload(candidate)),
                    candidate.created_at,
                ),
            ).fetchone()
            if not row:
                row = self.connection.execute(
                    "SELECT payload FROM candidates WHERE structure_hash = %s",
                    (candidate.structure_hash,),
                ).fetchone()
        return PolymerCandidate.model_validate(row["payload"])

    def attach_candidates(
        self,
        campaign_id: str,
        candidates: Iterable[PolymerCandidate],
        generation: int | None = None,
        selected: bool = True,
    ) -> None:
        with self._lock, self.connection.transaction():
            for candidate in candidates:
                saved = self.save_candidate(candidate)
                self.connection.execute(
                    """INSERT INTO campaign_candidates
                       (campaign_id, candidate_id, generation, selected)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (campaign_id, candidate_id, generation)
                       DO UPDATE SET selected = campaign_candidates.selected OR EXCLUDED.selected""",
                    (
                        campaign_id,
                        saved.id,
                        saved.generation if generation is None else generation,
                        selected,
                    ),
                )

    def campaign_candidates(
        self,
        campaign_id: str,
        generation: int | None = None,
        *,
        selected_only: bool = True,
    ) -> list[PolymerCandidate]:
        query = (
            "SELECT DISTINCT c.payload, c.created_at FROM candidates c "
            "JOIN campaign_candidates cc ON c.id = cc.candidate_id "
            "WHERE cc.campaign_id = %s"
        )
        args: list[Any] = [campaign_id]
        if generation is not None:
            query += " AND cc.generation = %s"
            args.append(generation)
        if selected_only:
            query += " AND cc.selected = TRUE"
        query += " ORDER BY c.created_at"
        rows = self.connection.execute(query, args).fetchall()
        return [PolymerCandidate.model_validate(row["payload"]) for row in rows]

    def save_predictions(self, predictions: Iterable[Prediction]) -> None:
        with self._lock, self.connection.transaction():
            for prediction in predictions:
                self.connection.execute(
                    """INSERT INTO predictions
                       (candidate_id, property, model_version, payload, created_at)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (candidate_id, property, model_version)
                       DO UPDATE SET payload = EXCLUDED.payload, created_at = EXCLUDED.created_at""",
                    (
                        prediction.candidate_id,
                        prediction.property.value,
                        prediction.model_version,
                        self.Jsonb(self._payload(prediction)),
                        prediction.created_at,
                    ),
                )

    def predictions_for(self, candidate_ids: Iterable[str], model_version: str | None = None) -> list[Prediction]:
        ids = [uuid.UUID(candidate_id) for candidate_id in candidate_ids]
        if not ids:
            return []
        query = "SELECT payload FROM predictions WHERE candidate_id = ANY(%s)"
        args: list[Any] = [ids]
        if model_version:
            query += " AND model_version = %s"
            args.append(model_version)
        rows = self.connection.execute(query, args).fetchall()
        return [Prediction.model_validate(row["payload"]) for row in rows]

    def save_observations(self, observations: Iterable[Observation]) -> None:
        with self._lock, self.connection.transaction():
            for observation in observations:
                self.connection.execute(
                    """INSERT INTO observations
                       (id, candidate_id, property, provenance, protocol_hash, payload, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (
                        observation.id,
                        observation.candidate_id,
                        observation.property.value,
                        observation.provenance.value,
                        observation.protocol_hash,
                        self.Jsonb(self._payload(observation)),
                        observation.created_at,
                    ),
                )

    def observations_for(self, candidate_ids: Iterable[str] = ()) -> list[Observation]:
        ids = [uuid.UUID(candidate_id) for candidate_id in candidate_ids]
        if ids:
            rows = self.connection.execute(
                "SELECT payload FROM observations WHERE candidate_id = ANY(%s) ORDER BY created_at",
                (ids,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT payload FROM observations ORDER BY created_at").fetchall()
        return [Observation.model_validate(row["payload"]) for row in rows]

    def training_examples(self) -> list[TrainingExample]:
        rows = self.connection.execute(
            """SELECT c.payload AS candidate_payload, o.payload AS observation_payload
               FROM observations o JOIN candidates c ON c.id = o.candidate_id
               ORDER BY o.created_at"""
        ).fetchall()
        return [
            TrainingExample(
                candidate=PolymerCandidate.model_validate(row["candidate_payload"]),
                observation=Observation.model_validate(row["observation_payload"]),
            )
            for row in rows
        ]

    def save_campaign(self, campaign: CampaignRecord) -> None:
        with self._lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT payload FROM campaigns WHERE id = %s FOR UPDATE", (campaign.id,)
            ).fetchone()
            if row:
                previous = CampaignRecord.model_validate(row["payload"])
                if campaign.state != previous.state and campaign.state not in CAMPAIGN_TRANSITIONS[previous.state]:
                    raise InvalidStateTransition(f"campaign {campaign.id}: {previous.state} -> {campaign.state}")
            self.connection.execute(
                """INSERT INTO campaigns (id, state, payload, updated_at) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state,
                   payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at""",
                (
                    campaign.id,
                    campaign.state.value,
                    self.Jsonb(self._payload(campaign)),
                    campaign.updated_at,
                ),
            )

    def get_campaign(self, campaign_id: str) -> CampaignRecord:
        row = self.connection.execute("SELECT payload FROM campaigns WHERE id = %s", (campaign_id,)).fetchone()
        if not row:
            raise KeyError(campaign_id)
        return CampaignRecord.model_validate(row["payload"])

    def save_job(self, job: PhysicsJob) -> None:
        with self._lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT payload FROM physics_jobs WHERE id = %s FOR UPDATE", (job.id,)
            ).fetchone()
            if row:
                previous = PhysicsJob.model_validate(row["payload"])
                if job.state != previous.state and job.state not in JOB_TRANSITIONS[previous.state]:
                    raise InvalidStateTransition(f"job {job.id}: {previous.state} -> {job.state}")
            self.connection.execute(
                """INSERT INTO physics_jobs
                   (id, campaign_id, candidate_id, state, manifest_hash, payload, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state,
                   manifest_hash = EXCLUDED.manifest_hash, payload = EXCLUDED.payload,
                   updated_at = EXCLUDED.updated_at""",
                (
                    job.id,
                    job.campaign_id,
                    job.candidate.id,
                    job.state.value,
                    job.manifest_hash,
                    self.Jsonb(self._payload(job)),
                    datetime.now(UTC),
                ),
            )

    def get_job(self, job_id: str) -> PhysicsJob:
        row = self.connection.execute("SELECT payload FROM physics_jobs WHERE id = %s", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return PhysicsJob.model_validate(row["payload"])

    def jobs_for_campaign(self, campaign_id: str) -> list[PhysicsJob]:
        rows = self.connection.execute(
            "SELECT payload FROM physics_jobs WHERE campaign_id = %s ORDER BY updated_at",
            (campaign_id,),
        ).fetchall()
        return [PhysicsJob.model_validate(row["payload"]) for row in rows]

    def save_approval(self, approval: Approval) -> None:
        with self._lock, self.connection.transaction():
            self.connection.execute(
                "INSERT INTO approvals (id, campaign_id, payload, created_at) VALUES (%s, %s, %s, %s)",
                (
                    approval.id,
                    approval.campaign_id,
                    self.Jsonb(self._payload(approval)),
                    approval.created_at,
                ),
            )

    def approvals_for_campaign(self, campaign_id: str) -> list[Approval]:
        rows = self.connection.execute(
            "SELECT payload FROM approvals WHERE campaign_id = %s ORDER BY created_at",
            (campaign_id,),
        ).fetchall()
        return [Approval.model_validate(row["payload"]) for row in rows]

    def record_event(self, campaign_id: str, kind: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        with self._lock, self.connection.transaction():
            self.connection.execute(
                "INSERT INTO audit_events (id, campaign_id, kind, payload, created_at) VALUES (%s, %s, %s, %s, %s)",
                (event_id, campaign_id, kind, self.Jsonb(payload), created_at),
            )
        return event_id

    def events_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, kind, payload, created_at FROM audit_events WHERE campaign_id = %s ORDER BY created_at",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "kind": row["kind"],
                "payload": row["payload"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
