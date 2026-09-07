from __future__ import annotations

from uuid import uuid4

from colab.operations import ExecutionJob, MetricsSnapshot, OperationalEvent
from colab.productization import ArtifactRecord, KnowledgeDocument, ToolDefinition, Workspace
from colab.service_adapters import (
    PostgresArtifactStore,
    PostgresExecutionCoordinator,
    PostgresKnowledgeBase,
    PostgresObservabilityRecorder,
    PostgresToolRegistry,
    PostgresWorkspaceManager,
)


class FakeStore:
    def __init__(self) -> None:
        self.workspace = Workspace(name="w", product_goal="goal")
        self.artifact = ArtifactRecord(
            workspace_id=self.workspace.workspace_id,
            kind="report",
            producer="qa",
            content={"ok": True},
            content_hash="a" * 64,
        )
        self.document = KnowledgeDocument(title="doc", text="text", source="test")
        self.tool = ToolDefinition(name="tool", description="test")
        self.job = ExecutionJob(
            workflow_id=uuid4(),
            workspace_id=self.workspace.workspace_id,
            stage="research",
            idempotency_key="key",
        )
        self.event = OperationalEvent(
            workflow_id=self.job.workflow_id,
            workspace_id=self.job.workspace_id,
            job_id=self.job.job_id,
            event_type="test",
            actor="test",
            message="ok",
        )

    def submit_workspace(self, workspace): return workspace
    def get_workspace(self, workspace_id): return self.workspace
    def list_workspaces(self): return [self.workspace]
    def put_artifact(self, artifact): return artifact
    def list_artifacts(self, workspace_id): return [self.artifact]
    def upsert_knowledge(self, document): return document
    def search_knowledge(self, query, limit=10): return [self.document][:limit]
    def register_tool(self, tool): return tool
    def list_tools(self): return [self.tool]
    def enqueue_execution(self, workflow_id, workspace_id, stage, idempotency_key, max_attempts=3): return self.job
    def claim_execution(self, worker_id, lease_seconds): return self.job
    def heartbeat_execution(self, job_id, worker_id, lease_seconds): return self.job
    def complete_execution(self, job_id, worker_id): return self.job
    def fail_execution(self, job_id, worker_id, error): return self.job
    def cancel_execution(self, job_id): return self.job
    def metrics(self): return MetricsSnapshot()
    def record_event(self, event): return event
    def query_events(self, workflow_id=None, workspace_id=None, job_id=None, limit=100): return [self.event][:limit]


def test_all_postgres_service_adapters_delegate() -> None:
    store = FakeStore()
    workspace_service = PostgresWorkspaceManager(store)
    artifact_service = PostgresArtifactStore(store)
    knowledge_service = PostgresKnowledgeBase(store)
    tool_service = PostgresToolRegistry(store)
    execution_service = PostgresExecutionCoordinator(store, lease_seconds=30)
    observability_service = PostgresObservabilityRecorder(store)

    assert workspace_service.submit(store.workspace) == store.workspace
    assert workspace_service.get(store.workspace.workspace_id) == store.workspace
    assert workspace_service.list() == [store.workspace]
    assert artifact_service.put(store.artifact) == store.artifact
    assert artifact_service.list(store.workspace.workspace_id) == [store.artifact]
    assert knowledge_service.upsert(store.document) == store.document
    assert knowledge_service.search("text") == [store.document]
    assert tool_service.register(store.tool) is None
    assert tool_service.list() == [store.tool]
    assert execution_service.enqueue(uuid4(), uuid4(), "research", "key") == store.job
    assert execution_service.claim("worker") == store.job
    assert execution_service.heartbeat(store.job.job_id, "worker") == store.job
    assert execution_service.complete(store.job.job_id, "worker") == store.job
    assert execution_service.fail(store.job.job_id, "worker", "error") == store.job
    assert execution_service.cancel(store.job.job_id) == store.job
    assert execution_service.snapshot() == MetricsSnapshot()
    assert observability_service.record(store.event) == store.event
    assert observability_service.query() == [store.event]


def test_postgres_execution_adapter_rejects_invalid_lease() -> None:
    store = FakeStore()
    try:
        PostgresExecutionCoordinator(store, lease_seconds=0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive lease must fail")
