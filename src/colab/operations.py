"""Phase 4 operational primitives: leases, retries, idempotency, and telemetry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ExecutionJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID = Field(default_factory=uuid4)
    workflow_id: UUID
    workspace_id: UUID
    stage: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=255)
    status: ExecutionStatus = ExecutionStatus.PENDING
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    lease_owner: str | None = Field(default=None, max_length=255)
    lease_expires_at: datetime | None = None
    error: str | None = Field(default=None, max_length=5000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class OperationalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    workflow_id: UUID
    workspace_id: UUID
    job_id: UUID | None = None
    event_type: str = Field(min_length=1, max_length=100)
    level: EventLevel = EventLevel.INFO
    actor: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MetricsSnapshot(BaseModel):
    """Point-in-time operational counters; no sensitive payloads are retained."""

    model_config = ConfigDict(extra="forbid")

    pending: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    retries: int = 0
    expired_leases: int = 0


Clock = Callable[[], datetime]


@dataclass
class ExecutionCoordinator:
    """In-process execution coordinator with expiring worker leases.

    This is the deterministic execution-control boundary. Production deployments should
    back the same state machine with PostgreSQL so multiple workers share one source of truth.
    """

    lease_seconds: int = 300
    clock: Clock = field(default=lambda: datetime.now(UTC))
    jobs: dict[UUID, ExecutionJob] = field(default_factory=dict)
    idempotency: dict[str, UUID] = field(default_factory=dict)
    retries: int = 0
    expired_leases: int = 0

    def __post_init__(self) -> None:
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")

    def enqueue(
        self,
        workflow_id: UUID,
        workspace_id: UUID,
        stage: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> ExecutionJob:
        if idempotency_key in self.idempotency:
            return self.jobs[self.idempotency[idempotency_key]]
        job = ExecutionJob(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            stage=stage,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            created_at=self.clock(),
            updated_at=self.clock(),
        )
        self.jobs[job.job_id] = job
        self.idempotency[idempotency_key] = job.job_id
        return job

    def claim(self, worker_id: str) -> ExecutionJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = self.clock()
        self._requeue_expired(now)
        candidates = sorted(
            (job for job in self.jobs.values() if job.status == ExecutionStatus.PENDING),
            key=lambda job: (job.created_at, str(job.job_id)),
        )
        if not candidates:
            return None
        job = candidates[0]
        job.attempt += 1
        job.status = ExecutionStatus.RUNNING
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        job.updated_at = now
        return job

    def heartbeat(self, job_id: UUID, worker_id: str) -> ExecutionJob:
        job = self._owned_running(job_id, worker_id)
        job.lease_expires_at = self.clock() + timedelta(seconds=self.lease_seconds)
        job.updated_at = self.clock()
        return job

    def complete(self, job_id: UUID, worker_id: str) -> ExecutionJob:
        job = self._owned_running(job_id, worker_id)
        now = self.clock()
        job.status = ExecutionStatus.SUCCEEDED
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = now
        job.updated_at = now
        return job

    def fail(self, job_id: UUID, worker_id: str, error: str) -> ExecutionJob:
        if not error.strip():
            raise ValueError("error must not be empty")
        job = self._owned_running(job_id, worker_id)
        now = self.clock()
        job.error = error[:5000]
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = now
        if job.attempt < job.max_attempts:
            job.status = ExecutionStatus.PENDING
            self.retries += 1
        else:
            job.status = ExecutionStatus.FAILED
            job.completed_at = now
        return job

    def cancel(self, job_id: UUID) -> ExecutionJob:
        try:
            job = self.jobs[job_id]
        except KeyError as exc:
            raise KeyError(str(job_id)) from exc
        if job.status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
            return job
        now = self.clock()
        job.status = ExecutionStatus.CANCELLED
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = now
        job.updated_at = now
        return job

    def snapshot(self) -> MetricsSnapshot:
        counts = {status: 0 for status in ExecutionStatus}
        for job in self.jobs.values():
            counts[job.status] += 1
        return MetricsSnapshot(
            pending=counts[ExecutionStatus.PENDING],
            running=counts[ExecutionStatus.RUNNING],
            succeeded=counts[ExecutionStatus.SUCCEEDED],
            failed=counts[ExecutionStatus.FAILED],
            cancelled=counts[ExecutionStatus.CANCELLED],
            retries=self.retries,
            expired_leases=self.expired_leases,
        )

    def _requeue_expired(self, now: datetime) -> None:
        for job in self.jobs.values():
            if (
                job.status == ExecutionStatus.RUNNING
                and job.lease_expires_at is not None
                and job.lease_expires_at <= now
            ):
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = now
                if job.attempt < job.max_attempts:
                    job.status = ExecutionStatus.PENDING
                    self.retries += 1
                    self.expired_leases += 1
                else:
                    job.status = ExecutionStatus.FAILED
                    job.error = "execution lease expired"
                    job.completed_at = now
                    self.expired_leases += 1

    def _owned_running(self, job_id: UUID, worker_id: str) -> ExecutionJob:
        try:
            job = self.jobs[job_id]
        except KeyError as exc:
            raise KeyError(str(job_id)) from exc
        if job.status != ExecutionStatus.RUNNING:
            raise RuntimeError("job is not running")
        if job.lease_owner != worker_id:
            raise PermissionError("worker does not own execution lease")
        if job.lease_expires_at is None or job.lease_expires_at <= self.clock():
            raise RuntimeError("execution lease has expired")
        return job


@dataclass
class ObservabilityRecorder:
    """Append-only operational event recorder with bounded in-memory retention."""

    max_events: int = 10000
    events: list[OperationalEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_events < 1:
            raise ValueError("max_events must be positive")

    def record(self, event: OperationalEvent) -> OperationalEvent:
        self.events.append(event)
        if len(self.events) > self.max_events:
            del self.events[: len(self.events) - self.max_events]
        return event

    def query(
        self,
        workflow_id: UUID | None = None,
        workspace_id: UUID | None = None,
        job_id: UUID | None = None,
        limit: int = 100,
    ) -> list[OperationalEvent]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        matched = [
            event
            for event in reversed(self.events)
            if (workflow_id is None or event.workflow_id == workflow_id)
            and (workspace_id is None or event.workspace_id == workspace_id)
            and (job_id is None or event.job_id == job_id)
        ]
        return matched[:limit]
