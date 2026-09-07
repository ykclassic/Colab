"""PostgreSQL persistence for canonical workflow state.

The repository is intentionally backend-only. Database credentials must be supplied through
runtime secret configuration; this module never embeds or returns them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

from .contracts import AgentTask, Artifact, AuditEvent, RiskAssessment, WorkflowState


class PersistenceError(RuntimeError):
    """Base error for workflow persistence failures."""


class WorkflowNotFound(PersistenceError):
    """Raised when a workflow does not exist."""


class ConcurrentWorkflowUpdate(PersistenceError):
    """Raised when optimistic concurrency detects a stale workflow version."""


ConnectionFactory = Callable[[], Connection[Any]]


class PostgresWorkflowRepository:
    """Persist and recover complete workflow snapshots transactionally.

    ``version`` is an optimistic-concurrency token. A save succeeds only when the caller's
    expected version still matches the database version. Checkpoints retain the exact state
    submitted with every successful save, enabling deterministic recovery/audit inspection.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @contextmanager
    def _connection(self) -> Iterator[Connection[Any]]:
        with self._connection_factory() as connection:
            yield connection

    def create(self, state: WorkflowState) -> int:
        """Create a workflow and its initial checkpoint, returning version 1."""
        payload = state.model_dump(mode="json")
        with self._connection() as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.workflows
                      (workflow_id, schema_version, product_goal, product_brief, roadmap,
                       current_stage, iteration_count, budgets, final_package, version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        state.workflow_id,
                        state.schema_version,
                        state.product_goal,
                        state.product_brief,
                        state.roadmap,
                        state.current_stage.value,
                        state.iteration_count,
                        state.budgets,
                        state.final_package,
                    ),
                )
                self._write_children(cur, state)
                self._write_checkpoint(cur, state, 1, payload)
        return 1

    def load(self, workflow_id: UUID) -> tuple[WorkflowState, int]:
        """Load the canonical state and current optimistic-concurrency version."""
        with self._connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM public.workflows WHERE workflow_id = %s", (workflow_id,))
                workflow = cur.fetchone()
                if workflow is None:
                    raise WorkflowNotFound(str(workflow_id))
                state = self._load_state(cur, workflow)
                return state, int(workflow["version"])

    def save(self, state: WorkflowState, expected_version: int) -> int:
        """Atomically persist state and return its new version."""
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        payload = state.model_dump(mode="json")
        new_version = expected_version + 1
        with self._connection() as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.workflows
                       SET schema_version = %s,
                           product_goal = %s,
                           product_brief = %s,
                           roadmap = %s,
                           current_stage = %s,
                           iteration_count = %s,
                           budgets = %s,
                           final_package = %s,
                           version = %s
                     WHERE workflow_id = %s AND version = %s
                    """,
                    (
                        state.schema_version,
                        state.product_goal,
                        state.product_brief,
                        state.roadmap,
                        state.current_stage.value,
                        state.iteration_count,
                        state.budgets,
                        state.final_package,
                        new_version,
                        state.workflow_id,
                        expected_version,
                    ),
                )
                if cur.rowcount != 1:
                    raise ConcurrentWorkflowUpdate(
                        f"workflow {state.workflow_id} changed since version {expected_version}"
                    )
                self._write_children(cur, state)
                self._write_checkpoint(cur, state, new_version, payload)
        return new_version

    @staticmethod
    def _write_checkpoint(cur: Any, state: WorkflowState, version: int, payload: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO public.workflow_checkpoints (workflow_id, version, state)
            VALUES (%s, %s, %s)
            """,
            (state.workflow_id, version, payload),
        )

    @staticmethod
    def _write_children(cur: Any, state: WorkflowState) -> None:
        for task in state.agent_tasks:
            cur.execute(
                """
                INSERT INTO public.agent_tasks
                  (task_id, workflow_id, role, objective, stage, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (task_id) DO UPDATE SET
                  role = EXCLUDED.role,
                  objective = EXCLUDED.objective,
                  stage = EXCLUDED.stage,
                  status = EXCLUDED.status
                """,
                (task.task_id, state.workflow_id, task.role.value, task.objective, task.stage.value, task.status),
            )
        for artifact in [*state.research_artifacts, *state.strategy_candidates, *state.implementation_artifacts, *state.validation_results]:
            cur.execute(
                """
                INSERT INTO public.artifacts
                  (artifact_id, workflow_id, kind, version, producer, content)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (artifact_id) DO NOTHING
                """,
                (artifact.artifact_id, state.workflow_id, artifact.kind, artifact.version, artifact.producer.value, artifact.content),
            )
        for assessment in state.risk_assessments:
            cur.execute(
                """
                INSERT INTO public.risk_assessments
                  (assessment_id, workflow_id, decision, findings, controls, assessor)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (assessment_id) DO NOTHING
                """,
                (
                    assessment.assessment_id,
                    state.workflow_id,
                    assessment.decision.value,
                    assessment.findings,
                    assessment.controls,
                    assessment.assessor.value,
                ),
            )
        for decision in state.decisions:
            if "_persistence_id" in decision:
                continue
            cur.execute(
                "INSERT INTO public.workflow_decisions (workflow_id, decision) VALUES (%s, %s)",
                (state.workflow_id, decision),
            )
        for approval in state.approvals:
            if "_persistence_id" in approval:
                continue
            cur.execute(
                "INSERT INTO public.workflow_approvals (workflow_id, approval) VALUES (%s, %s)",
                (state.workflow_id, approval),
            )
        for event in state.audit_events:
            cur.execute(
                """
                INSERT INTO public.audit_events
                  (event_id, workflow_id, event_type, stage, actor, message, at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    state.workflow_id,
                    event.event_type,
                    event.stage.value,
                    str(event.actor),
                    event.message,
                    event.at,
                ),
            )

    @staticmethod
    def _load_state(cur: Any, workflow: dict[str, Any]) -> WorkflowState:
        workflow_id = workflow["workflow_id"]
        cur.execute("SELECT * FROM public.agent_tasks WHERE workflow_id = %s ORDER BY created_at", (workflow_id,))
        tasks = [
            AgentTask(
                task_id=row["task_id"], role=row["role"], objective=row["objective"],
                stage=row["stage"], status=row["status"]
            )
            for row in cur.fetchall()
        ]
        cur.execute("SELECT * FROM public.artifacts WHERE workflow_id = %s ORDER BY created_at", (workflow_id,))
        artifacts = [
            Artifact(
                artifact_id=row["artifact_id"], kind=row["kind"], version=row["version"],
                producer=row["producer"], content=row["content"], created_at=row["created_at"]
            )
            for row in cur.fetchall()
        ]
        cur.execute("SELECT * FROM public.risk_assessments WHERE workflow_id = %s ORDER BY created_at", (workflow_id,))
        risks = [
            RiskAssessment(
                assessment_id=row["assessment_id"], decision=row["decision"], findings=row["findings"],
                controls=row["controls"], assessor=row["assessor"]
            )
            for row in cur.fetchall()
        ]
        cur.execute("SELECT * FROM public.audit_events WHERE workflow_id = %s ORDER BY at", (workflow_id,))
        events = [
            AuditEvent(
                event_id=row["event_id"], event_type=row["event_type"], stage=row["stage"],
                actor=row["actor"], message=row["message"], at=row["at"]
            )
            for row in cur.fetchall()
        ]
        cur.execute("SELECT decision FROM public.workflow_decisions WHERE workflow_id = %s ORDER BY created_at", (workflow_id,))
        decisions = [row["decision"] for row in cur.fetchall()]
        cur.execute("SELECT approval FROM public.workflow_approvals WHERE workflow_id = %s ORDER BY created_at", (workflow_id,))
        approvals = [row["approval"] for row in cur.fetchall()]
        research, strategy, implementation, validation = [], [], [], []
        for artifact in artifacts:
            # Artifact kind is the stable routing discriminator; callers may use any kind string.
            if artifact.kind.startswith("research"):
                research.append(artifact)
            elif artifact.kind.startswith("strategy"):
                strategy.append(artifact)
            elif artifact.kind.startswith("implementation"):
                implementation.append(artifact)
            elif artifact.kind.startswith("validation"):
                validation.append(artifact)

        return WorkflowState(
            workflow_id=workflow_id,
            schema_version=workflow["schema_version"],
            product_goal=workflow["product_goal"],
            product_brief=workflow["product_brief"],
            roadmap=workflow["roadmap"],
            current_stage=workflow["current_stage"],
            agent_tasks=tasks,
            research_artifacts=research,
            strategy_candidates=strategy,
            risk_assessments=risks,
            implementation_artifacts=implementation,
            validation_results=validation,
            decisions=decisions,
            approvals=approvals,
            audit_events=events,
            iteration_count=workflow["iteration_count"],
            budgets=workflow["budgets"],
            final_package=workflow["final_package"],
        )


def connection_factory_from_dsn(dsn: str) -> ConnectionFactory:
    """Create a connection factory from a secret DSN without persisting the DSN."""
    if not dsn.strip():
        raise ValueError("database DSN must not be empty")

    def factory() -> Connection[Any]:
        return Connection.connect(dsn, row_factory=dict_row)

    return factory
