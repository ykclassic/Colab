from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self
from uuid import uuid4

import pytest

from colab.contracts import (
    AgentRole,
    AgentTask,
    Artifact,
    Decision,
    RiskAssessment,
    Stage,
    WorkflowState,
)
from colab.persistence import (
    ConcurrentWorkflowUpdate,
    PersistenceError,
    PostgresWorkflowRepository,
    WorkflowNotFound,
    connection_factory_from_dsn,
)


class FakeCursor:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.rowcount = 1
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> Any:
        return self.rows.pop(0) if self.rows else None

    def fetchall(self) -> list[Any]:
        rows = self.rows
        self.rows = []
        return rows


class FakeTransaction:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def cursor(self, **_: Any) -> FakeCursor:
        return self.cursor_obj


def state_with_children() -> WorkflowState:
    state = WorkflowState(product_goal="build a safe agent platform", current_stage=Stage.RISK)
    state.agent_tasks.append(
        AgentTask(role=AgentRole.RESEARCHER, objective="research", stage=Stage.RESEARCH)
    )
    state.research_artifacts.append(
        Artifact(kind="research_report", producer=AgentRole.RESEARCHER, content={"result": "ok"})
    )
    state.strategy_candidates.append(
        Artifact(kind="strategy", producer=AgentRole.STRATEGY, content={"signal": "test"})
    )
    state.implementation_artifacts.append(
        Artifact(kind="implementation", producer=AgentRole.ENGINEER, content={"status": "ready"})
    )
    state.validation_results.append(
        Artifact(kind="validation", producer=AgentRole.ENGINEER, content={"passed": True})
    )
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    state.decisions.append({"decision": "approve", "actor": "risk"})
    state.approvals.append({"decision": "approve", "actor": "human"})
    state.record("test", AgentRole.CEO, "persistence test")
    state.record("test", "system", "string actor")
    return state


def test_create_persists_workflow_children_and_checkpoint() -> None:
    cursor = FakeCursor()
    repository = PostgresWorkflowRepository(lambda: FakeConnection(cursor))
    assert repository.create(state_with_children()) == 1
    assert len(cursor.executed) >= 10
    assert any("workflow_checkpoints" in sql for sql, _ in cursor.executed)
    assert any("audit_events" in sql for sql, _ in cursor.executed)


def test_save_persists_incremented_version_and_children() -> None:
    cursor = FakeCursor(rows=[(1,), (1,)])
    repository = PostgresWorkflowRepository(lambda: FakeConnection(cursor))
    state = state_with_children()
    assert repository.save(state, 1) == 2
    assert any("UPDATE public.workflows" in sql for sql, _ in cursor.executed)


def test_save_rejects_non_positive_expected_version() -> None:
    repository = PostgresWorkflowRepository(lambda: FakeConnection(FakeCursor()))
    with pytest.raises(ValueError, match="expected_version"):
        repository.save(WorkflowState(product_goal="test"), 0)


def test_save_detects_optimistic_concurrency_conflict() -> None:
    cursor = FakeCursor()
    cursor.rowcount = 0
    repository = PostgresWorkflowRepository(lambda: FakeConnection(cursor))
    with pytest.raises(ConcurrentWorkflowUpdate):
        repository.save(WorkflowState(product_goal="test"), 1)


def test_load_reconstructs_complete_state() -> None:
    workflow_id = uuid4()
    created = datetime.now(UTC)
    task_id = uuid4()
    artifact_id = uuid4()
    assessment_id = uuid4()
    event_id = uuid4()
    workflow = {
        "workflow_id": workflow_id,
        "schema_version": "1.0",
        "product_goal": "test",
        "product_brief": {"scope": "x"},
        "roadmap": ["one"],
        "current_stage": "risk",
        "iteration_count": 2,
        "budgets": {"tokens": 100},
        "final_package": {"done": True},
        "version": 4,
    }
    rows = [
        workflow,
        {"task_id": task_id, "role": "quant_researcher", "objective": "research", "stage": "research", "status": "done"},
        {"artifact_id": artifact_id, "kind": "report", "version": 1, "producer": "quant_researcher", "content": {"x": 1}, "created_at": created, "collection": "research"},
        {"assessment_id": assessment_id, "decision": "approve", "findings": [], "controls": ["limit"], "assessor": "risk_compliance"},
        {"decision": {"decision": "approve"}},
        {"approval": {"decision": "approve"}},
        {"event_id": event_id, "event_type": "created", "stage": "risk", "actor": "system", "message": "ok", "at": created},
    ]
    cursor = FakeCursor(rows)
    repository = PostgresWorkflowRepository(lambda: FakeConnection(cursor))
    loaded, version = repository.load(workflow_id)
    assert version == 4
    assert loaded.product_goal == "test"
    assert len(loaded.agent_tasks) == 1
    assert len(loaded.research_artifacts) == 1
    assert loaded.risk_assessments[0].decision == Decision.APPROVE
    assert loaded.decisions == [{"decision": "approve"}]
    assert loaded.approvals == [{"decision": "approve"}]
    assert loaded.audit_events[0].actor == "system"


def test_load_missing_workflow_raises() -> None:
    repository = PostgresWorkflowRepository(lambda: FakeConnection(FakeCursor([None])))
    with pytest.raises(WorkflowNotFound):
        repository.load(uuid4())


def test_save_fails_if_decision_offset_row_is_missing() -> None:
    cursor = FakeCursor(rows=[(1,)])
    repository = PostgresWorkflowRepository(lambda: FakeConnection(cursor))
    with pytest.raises(PersistenceError, match="decision offset"):
        repository.save(WorkflowState(product_goal="test"), 1)


def test_connection_factory_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        connection_factory_from_dsn("  ")


def test_connection_factory_returns_callable() -> None:
    factory = connection_factory_from_dsn("postgresql://example")
    assert callable(factory)
