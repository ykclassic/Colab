"""Adapters that expose the existing in-memory service contracts over PostgreSQL."""
from __future__ import annotations

from uuid import UUID

from .operations import ExecutionJob, MetricsSnapshot, OperationalEvent
from .production_persistence import PostgresPlatformStore
from .productization import ArtifactRecord, KnowledgeDocument, ToolDefinition, Workspace


class PostgresWorkspaceManager:
    def __init__(self, store: PostgresPlatformStore) -> None:
        self._store = store

    def submit(self, workspace: Workspace) -> Workspace:
        return self._store.submit_workspace(workspace)

    def get(self, workspace_id: UUID) -> Workspace:
        return self._store.get_workspace(workspace_id)

    def list(self) -> list[Workspace]:
        return self._store.list_workspaces()


class PostgresArtifactStore:
    def __init__(self, store: PostgresPlatformStore) -> None:
        self._store = store

    def put(self, artifact: ArtifactRecord) -> ArtifactRecord:
        return self._store.put_artifact(artifact)

    def list(self, workspace_id: UUID) -> list[ArtifactRecord]:
        return self._store.list_artifacts(workspace_id)


class PostgresKnowledgeBase:
    def __init__(self, store: PostgresPlatformStore) -> None:
        self._store = store

    def upsert(self, document: KnowledgeDocument) -> KnowledgeDocument:
        return self._store.upsert_knowledge(document)

    def search(self, query: str, limit: int = 10) -> list[KnowledgeDocument]:
        return self._store.search_knowledge(query, limit)


class PostgresToolRegistry:
    def __init__(self, store: PostgresPlatformStore) -> None:
        self._store = store

    def register(self, tool: ToolDefinition) -> None:
        self._store.register_tool(tool)

    def list(self) -> list[ToolDefinition]:
        return self._store.list_tools()


class PostgresExecutionCoordinator:
    def __init__(self, store: PostgresPlatformStore, lease_seconds: int = 300) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self._store = store
        self.lease_seconds = lease_seconds

    def enqueue(
        self,
        workflow_id: UUID,
        workspace_id: UUID,
        stage: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> ExecutionJob:
        return self._store.enqueue_execution(
            workflow_id, workspace_id, stage, idempotency_key, max_attempts
        )

    def claim(self, worker_id: str) -> ExecutionJob | None:
        return self._store.claim_execution(worker_id, self.lease_seconds)

    def heartbeat(self, job_id: UUID, worker_id: str) -> ExecutionJob:
        return self._store.heartbeat_execution(job_id, worker_id, self.lease_seconds)

    def complete(self, job_id: UUID, worker_id: str) -> ExecutionJob:
        return self._store.complete_execution(job_id, worker_id)

    def fail(self, job_id: UUID, worker_id: str, error: str) -> ExecutionJob:
        return self._store.fail_execution(job_id, worker_id, error)

    def cancel(self, job_id: UUID) -> ExecutionJob:
        return self._store.cancel_execution(job_id)

    def snapshot(self) -> MetricsSnapshot:
        return self._store.metrics()


class PostgresObservabilityRecorder:
    def __init__(self, store: PostgresPlatformStore) -> None:
        self._store = store

    def record(self, event: OperationalEvent) -> OperationalEvent:
        return self._store.record_event(event)

    def query(
        self,
        workflow_id: UUID | None = None,
        workspace_id: UUID | None = None,
        job_id: UUID | None = None,
        limit: int = 100,
    ) -> list[OperationalEvent]:
        return self._store.query_events(workflow_id, workspace_id, job_id, limit)
