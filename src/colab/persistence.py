"""PostgreSQL persistence for canonical workflow state."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
    """Persist and recover complete workflow state with transactional checkpoints."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @contextmanager
    def _connection(self) -> Iterator[Connection[Any]]:
        with self._connection_factory() as connection:
            yield connection

    def create(self, state: WorkflowState) -> int:
        payload = state.model_dump(mode="json")
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.workflows
                (workflow_id, schema_version, product_goal, product_brief, roadmap,
                 current_stage, iteration_count, budgets, final_package, version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (state.workflow_id, state.schema_version, state.product_goal, state.product_brief,
                 state.roadmap, state.current_stage.value, state.iteration_count, state.budgets,
                 state.final_package),
            )
            self._write_children(cur, state, 0, 0)
            self._write_checkpoint(cur, state, 1, payload)
        return 1

    def load(self, workflow_id: UUID) -> tuple[WorkflowState, int]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.workflows WHERE workflow_id=%s", (workflow_id,))
            workflow = cur.fetchone()
            if workflow is None:
                raise WorkflowNotFound(str(workflow_id))
            return self._load_state(cur, workflow), int(workflow["version"])

    def save(self, state: WorkflowState, expected_version: int) -> int:
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        new_version = expected_version + 1
        payload = state.model_dump(mode="json")
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """UPDATE public.workflows
                   SET schema_version=%s, product_goal=%s, product_brief=%s, roadmap=%s,
                       current_stage=%s, iteration_count=%s, budgets=%s, final_package=%s, version=%s
                 WHERE workflow_id=%s AND version=%s""",
                (state.schema_version, state.product_goal, state.product_brief, state.roadmap,
                 state.current_stage.value, state.iteration_count, state.budgets, state.final_package,
                 new_version, state.workflow_id, expected_version),
            )
            if cur.rowcount != 1:
                raise ConcurrentWorkflowUpdate(
                    f"workflow {state.workflow_id} changed since version {expected_version}"
                )
            cur.execute("SELECT count(*) FROM public.workflow_decisions WHERE workflow_id=%s", (state.workflow_id,))
            decision_offset = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM public.workflow_approvals WHERE workflow_id=%s", (state.workflow_id,))
            approval_offset = int(cur.fetchone()[0])
            self._write_children(cur, state, decision_offset, approval_offset)
            self._write_checkpoint(cur, state, new_version, payload)
        return new_version

    @staticmethod
    def _write_checkpoint(cur: Any, state: WorkflowState, version: int, payload: dict[str, Any]) -> None:
        cur.execute("INSERT INTO public.workflow_checkpoints (workflow_id,version,state) VALUES (%s,%s,%s)",
                    (state.workflow_id, version, payload))

    @staticmethod
    def _write_children(cur: Any, state: WorkflowState, decision_offset: int, approval_offset: int) -> None:
        for task in state.agent_tasks:
            cur.execute(
                """INSERT INTO public.agent_tasks (task_id,workflow_id,role,objective,stage,status)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (task_id) DO UPDATE SET role=EXCLUDED.role, objective=EXCLUDED.objective,
                  stage=EXCLUDED.stage, status=EXCLUDED.status""",
                (task.task_id, state.workflow_id, task.role.value, task.objective, task.stage.value, task.status),
            )
        collections = (("research", state.research_artifacts), ("strategy", state.strategy_candidates),
                       ("implementation", state.implementation_artifacts), ("validation", state.validation_results))
        for collection, artifacts in collections:
            for artifact in artifacts:
                cur.execute(
                    """INSERT INTO public.artifacts
                    (artifact_id,workflow_id,collection,kind,version,producer,content)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (artifact_id) DO NOTHING""",
                    (artifact.artifact_id, state.workflow_id, collection, artifact.kind, artifact.version,
                     artifact.producer.value, artifact.content),
                )
        for assessment in state.risk_assessments:
            cur.execute(
                """INSERT INTO public.risk_assessments
                (assessment_id,workflow_id,decision,findings,controls,assessor)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (assessment_id) DO NOTHING""",
                (assessment.assessment_id, state.workflow_id, assessment.decision.value,
                 assessment.findings, assessment.controls, assessment.assessor.value),
            )
        for decision in state.decisions[decision_offset:]:
            cur.execute("INSERT INTO public.workflow_decisions (workflow_id,decision) VALUES (%s,%s)",
                        (state.workflow_id, decision))
        for approval in state.approvals[approval_offset:]:
            cur.execute("INSERT INTO public.workflow_approvals (workflow_id,approval) VALUES (%s,%s)",
                        (state.workflow_id, approval))
        for event in state.audit_events:
            cur.execute(
                """INSERT INTO public.audit_events
                (event_id,workflow_id,event_type,stage,actor,message,at)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING""",
                (event.event_id, state.workflow_id, event.event_type, event.stage.value,
                 str(event.actor), event.message, event.at),
            )

    @staticmethod
    def _load_state(cur: Any, workflow: dict[str, Any]) -> WorkflowState:
        workflow_id = workflow["workflow_id"]
        cur.execute("SELECT * FROM public.agent_tasks WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        tasks = [AgentTask(task_id=r["task_id"], role=r["role"], objective=r["objective"], stage=r["stage"], status=r["status"])
                 for r in cur.fetchall()]
        cur.execute("SELECT * FROM public.artifacts WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        rows = cur.fetchall()
        artifacts = [Artifact(artifact_id=r["artifact_id"], kind=r["kind"], version=r["version"], producer=r["producer"],
                              content=r["content"], created_at=r["created_at"]) for r in rows]
        by_collection: dict[str, list[Artifact]] = {"research": [], "strategy": [], "implementation": [], "validation": []}
        for artifact, row in zip(artifacts, rows, strict=True):
            by_collection[str(row["collection"])].append(artifact)
        cur.execute("SELECT * FROM public.risk_assessments WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        risks = [RiskAssessment(assessment_id=r["assessment_id"], decision=r["decision"], findings=r["findings"],
                                controls=r["controls"], assessor=r["assessor"]) for r in cur.fetchall()]
        cur.execute("SELECT * FROM public.audit_events WHERE workflow_id=%s ORDER BY at", (workflow_id,))
        events = [AuditEvent(event_id=r["event_id"], event_type=r["event_type"], stage=r["stage"], actor=r["actor"],
                             message=r["message"], at=r["at"]) for r in cur.fetchall()]
        cur.execute("SELECT decision FROM public.workflow_decisions WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        decisions = [r["decision"] for r in cur.fetchall()]
        cur.execute("SELECT approval FROM public.workflow_approvals WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        approvals = [r["approval"] for r in cur.fetchall()]
        return WorkflowState(workflow_id=workflow_id, schema_version=workflow["schema_version"], product_goal=workflow["product_goal"],
            product_brief=workflow["product_brief"], roadmap=workflow["roadmap"], current_stage=workflow["current_stage"],
            agent_tasks=tasks, research_artifacts=by_collection["research"], strategy_candidates=by_collection["strategy"],
            risk_assessments=risks, implementation_artifacts=by_collection["implementation"], validation_results=by_collection["validation"],
            decisions=decisions, approvals=approvals, audit_events=events, iteration_count=workflow["iteration_count"],
            budgets=workflow["budgets"], final_package=workflow["final_package"])


def connection_factory_from_dsn(dsn: str) -> ConnectionFactory:
    """Create a connection factory from a secret DSN without persisting the DSN."""
    if not dsn.strip():
        raise ValueError("database DSN must not be empty")

    def factory() -> Connection[Any]:
        return Connection.connect(dsn, row_factory=dict_row)

    return factory
