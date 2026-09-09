# ruff: noqa: I001,E701,E702
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from colab.api import PlatformServices, create_app
from colab.operations import EventLevel, ExecutionCoordinator, ExecutionStatus, MetricsSnapshot, ObservabilityRecorder, OperationalEvent


class Clock:
    def __init__(self) -> None: self.now = datetime(2026, 9, 7, tzinfo=UTC)
    def __call__(self) -> datetime: return self.now
    def advance(self, seconds: int) -> None: self.now += timedelta(seconds=seconds)


def test_enqueue_is_idempotent_and_claim_requires_worker() -> None:
    clock = Clock(); coordinator = ExecutionCoordinator(lease_seconds=30, clock=clock); workflow_id, workspace_id = uuid4(), uuid4(); first = coordinator.enqueue(workflow_id, workspace_id, "research", "same-key"); second = coordinator.enqueue(workflow_id, workspace_id, "research", "same-key")
    assert second.job_id == first.job_id; assert coordinator.claim("worker-a") == first; assert coordinator.snapshot().running == 1
    with pytest.raises(ValueError): coordinator.claim(" ")


def test_lease_ownership_heartbeat_complete_and_cancel() -> None:
    clock = Clock(); coordinator = ExecutionCoordinator(lease_seconds=30, clock=clock); workflow_id, workspace_id = uuid4(), uuid4(); job = coordinator.enqueue(workflow_id, workspace_id, "validation", "key-1")
    assert coordinator.claim("worker-a") == job
    with pytest.raises(PermissionError): coordinator.complete(job.job_id, "other")
    coordinator.heartbeat(job.job_id, "worker-a"); assert coordinator.complete(job.job_id, "worker-a").status == ExecutionStatus.SUCCEEDED; assert coordinator.cancel(job.job_id).status == ExecutionStatus.SUCCEEDED
    queued = coordinator.enqueue(workflow_id, workspace_id, "synthesis", "key-2"); assert coordinator.cancel(queued.job_id).status == ExecutionStatus.CANCELLED


def test_failure_retries_then_becomes_terminal() -> None:
    clock = Clock(); coordinator = ExecutionCoordinator(lease_seconds=30, clock=clock); workflow_id, workspace_id = uuid4(), uuid4(); job = coordinator.enqueue(workflow_id, workspace_id, "implementation", "key", max_attempts=2)
    assert coordinator.claim("worker-a") is not None; assert coordinator.fail(job.job_id, "worker-a", "transient").status == ExecutionStatus.PENDING; assert coordinator.claim("worker-b") is not None; assert coordinator.fail(job.job_id, "worker-b", "terminal").status == ExecutionStatus.FAILED
    snapshot = coordinator.snapshot(); assert snapshot.retries == 1; assert snapshot.failed == 1


def test_expired_lease_is_requeued_and_then_can_fail_terminally() -> None:
    clock = Clock(); coordinator = ExecutionCoordinator(lease_seconds=10, clock=clock); workflow_id, workspace_id = uuid4(), uuid4(); job = coordinator.enqueue(workflow_id, workspace_id, "research", "key", max_attempts=1)
    assert coordinator.claim("worker-a") is not None; clock.advance(10); assert coordinator.claim("worker-b") is None; assert job.status == ExecutionStatus.FAILED; assert job.error == "execution lease expired"; assert coordinator.snapshot().expired_leases == 1


def test_heartbeat_rejects_expired_lease() -> None:
    clock = Clock(); coordinator = ExecutionCoordinator(lease_seconds=5, clock=clock); job = coordinator.enqueue(uuid4(), uuid4(), "risk", "key"); assert coordinator.claim("worker") is not None; clock.advance(6)
    with pytest.raises(RuntimeError, match="expired"): coordinator.heartbeat(job.job_id, "worker")


def test_observability_is_bounded_and_filterable() -> None:
    workflow_id, workspace_id, job_id = uuid4(), uuid4(), uuid4(); recorder = ObservabilityRecorder(max_events=2)
    for index in range(3): recorder.record(OperationalEvent(workflow_id=workflow_id, workspace_id=workspace_id, job_id=job_id, event_type=f"event_{index}", level=EventLevel.INFO, actor="worker", message="ok"))
    assert len(recorder.events) == 2; assert recorder.query(workflow_id=workflow_id, job_id=job_id, limit=1)[0].event_type == "event_2"; assert recorder.query(workflow_id=uuid4()) == []
    with pytest.raises(ValueError): recorder.query(limit=0)


def test_validation_of_operational_limits() -> None:
    with pytest.raises(ValueError): ExecutionCoordinator(lease_seconds=0)
    with pytest.raises(ValueError): ObservabilityRecorder(max_events=0)
    assert MetricsSnapshot().pending == 0


def test_api_execution_lifecycle_and_events() -> None:
    services = PlatformServices(); client = TestClient(create_app(services)); workflow_id, workspace_id = uuid4(), uuid4(); payload = {"workflow_id": str(workflow_id), "workspace_id": str(workspace_id), "stage": "research", "idempotency_key": "api-key"}
    created = client.post("/api/executions", json=payload); assert created.status_code == 201; job = created.json(); duplicate = client.post("/api/executions", json=payload); assert duplicate.status_code == 201; assert duplicate.json()["job_id"] == job["job_id"]
    assert client.get("/api/operations/metrics").json()["pending"] == 1; claimed = client.post("/api/executions/claim", json={"worker_id": "worker-a"}); assert claimed.status_code == 200; job_id = claimed.json()["job_id"]
    assert client.post(f"/api/executions/{job_id}/heartbeat", json={"worker_id": "worker-a"}).status_code == 200; assert client.post(f"/api/executions/{job_id}/complete", json={"worker_id": "worker-a"}).json()["status"] == "succeeded"; assert client.get("/api/operations/metrics").json()["succeeded"] == 1
    events = client.get("/api/operations/events", params={"job_id": job_id, "workspace_id": str(workspace_id)}).json(); assert {event["event_type"] for event in events} >= {"execution_enqueued", "execution_claimed", "execution_succeeded"}
    assert client.post("/api/executions/claim", json={"worker_id": "worker-a"}).status_code == 409; assert client.post("/api/executions/not-a-uuid/cancel").status_code == 422
