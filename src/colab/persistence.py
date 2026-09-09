"""PostgreSQL persistence for canonical workflow state and integrity records."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

from .contracts import AgentTask, Artifact, AuditEvent, RiskAssessment, Stage, WorkflowState
from .policy import validate_state_for_persistence
from .workflow_integrity import (
    WorkflowIntegrityError,
    state_hash,
    validate_event_chain,
    validate_snapshot_hash,
    validate_stage_transition,
)


class PersistenceError(RuntimeError):
    """Base error for workflow persistence failures."""


class WorkflowNotFound(PersistenceError):
    """Raised when a workflow does not exist."""


class ConcurrentWorkflowUpdate(PersistenceError):
    """Raised when optimistic concurrency detects a stale workflow version."""


ConnectionFactory = Callable[[], Connection[Any]]


class PostgresWorkflowRepository:
    """Persist and recover complete workflow state with an integrity ledger."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @contextmanager
    def _connection(self) -> Iterator[Connection[Any]]:
        with self._connection_factory() as connection:
            yield connection

    def create(self, state: WorkflowState) -> int:
        validate_state_for_persistence(state)
        payload = state.model_dump(mode="json")
        digest = state_hash(state)
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.workflows
                (workflow_id,workspace_id,schema_version,product_goal,product_brief,roadmap,
                 current_stage,iteration_count,budgets,final_package,version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (state.workflow_id, state.workspace_id, state.schema_version, state.product_goal,
                 state.product_brief, state.roadmap, state.current_stage.value, state.iteration_count,
                 state.budgets, state.final_package),
            )
            self._write_children(cur, state, 0, 0)
            self._write_checkpoint(cur, state, 1, payload, digest)
            self._append_event(
                cur, state, 1, None, state.current_stage.value, state.current_stage.value,
                digest, 1, "workflow_created", "system", "Workflow created at intake stage.",
            )
        return 1

    def load(self, workflow_id: UUID) -> tuple[WorkflowState, int]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.workflows WHERE workflow_id=%s", (workflow_id,))
            workflow = cur.fetchone()
            if workflow is None:
                raise WorkflowNotFound(str(workflow_id))
            return self._load_state(cur, workflow), int(workflow["version"])

    def save(self, state: WorkflowState, expected_version: int) -> int:
        validate_state_for_persistence(state)
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        new_version = expected_version + 1
        payload = state.model_dump(mode="json")
        digest = state_hash(state)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT current_stage FROM public.workflows WHERE workflow_id=%s AND version=%s FOR UPDATE",
                (state.workflow_id, expected_version),
            )
            previous = cur.fetchone()
            if previous is None:
                raise ConcurrentWorkflowUpdate(
                    f"workflow {state.workflow_id} changed since version {expected_version}"
                )
            source_stage = Stage(previous["current_stage"])
            validate_stage_transition(source_stage, state.current_stage, state)
            cur.execute(
                """UPDATE public.workflows
                   SET workspace_id=%s,schema_version=%s,product_goal=%s,product_brief=%s,roadmap=%s,
                       current_stage=%s,iteration_count=%s,budgets=%s,final_package=%s,version=%s
                 WHERE workflow_id=%s AND version=%s""",
                (state.workspace_id, state.schema_version, state.product_goal, state.product_brief, state.roadmap,
                 state.current_stage.value, state.iteration_count, state.budgets, state.final_package,
                 new_version, state.workflow_id, expected_version),
            )
            if cur.rowcount != 1:
                raise ConcurrentWorkflowUpdate(
                    f"workflow {state.workflow_id} changed since version {expected_version}"
                )
            cur.execute("SELECT count(*) AS count FROM public.workflow_decisions WHERE workflow_id=%s", (state.workflow_id,))
            decision_offset = int(cur.fetchone()["count"])
            cur.execute("SELECT count(*) AS count FROM public.workflow_approvals WHERE workflow_id=%s", (state.workflow_id,))
            approval_offset = int(cur.fetchone()["count"])
            self._write_children(cur, state, decision_offset, approval_offset)
            self._write_checkpoint(cur, state, new_version, payload, digest)
            cur.execute(
                "SELECT sequence_no,resulting_state_hash FROM public.workflow_events WHERE workflow_id=%s ORDER BY sequence_no DESC LIMIT 1",
                (state.workflow_id,),
            )
            last_event = cur.fetchone()
            sequence = int(last_event["sequence_no"]) + 1 if last_event else 1
            previous_hash = last_event["resulting_state_hash"] if last_event else None
            event_type = "stage_advanced" if source_stage != state.current_stage else "workflow_snapshot_saved"
            self._append_event(
                cur, state, sequence, previous_hash, source_stage.value, state.current_stage.value,
                digest, new_version, event_type, "orchestrator", f"{source_stage.value} -> {state.current_stage.value}",
            )
        return new_version

    def validate_integrity(self, workflow_id: UUID) -> None:
        """Replay the durable event/snapshot chain and raise on any tampering."""
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT sequence_no,event_type,from_stage,to_stage,previous_state_hash,resulting_state_hash,
                          snapshot_version,actor,message,occurred_at
                   FROM public.workflow_events WHERE workflow_id=%s ORDER BY sequence_no""",
                (workflow_id,),
            )
            events = cur.fetchall()
            if not events:
                raise WorkflowIntegrityError("workflow has no integrity events")
            validate_event_chain(events)
            cur.execute(
                "SELECT version,state,state_hash FROM public.workflow_checkpoints WHERE workflow_id=%s ORDER BY version",
                (workflow_id,),
            )
            snapshots = cur.fetchall()
            snapshot_by_version = {int(row["version"]): row for row in snapshots}
            for event in events:
                snapshot = snapshot_by_version.get(int(event["snapshot_version"]))
                if snapshot is None:
                    raise WorkflowIntegrityError(
                        f"event {event['sequence_no']} references missing snapshot {event['snapshot_version']}"
                    )
                if snapshot["state_hash"] is None:
                    raise WorkflowIntegrityError(
                        f"snapshot {event['snapshot_version']} is a legacy un-hashed snapshot"
                    )
                validate_snapshot_hash(snapshot)
                if snapshot["state_hash"] != event["resulting_state_hash"]:
                    raise WorkflowIntegrityError(
                        f"event {event['sequence_no']} does not match its durable snapshot"
                    )

    @staticmethod
    def _write_checkpoint(cur: Any, state: WorkflowState, version: int, payload: dict[str, Any], digest: str) -> None:
        cur.execute(
            """INSERT INTO public.workflow_checkpoints (workflow_id,version,state,state_hash)
               VALUES (%s,%s,%s,%s)""",
            (state.workflow_id, version, payload, digest),
        )

    @staticmethod
    def _append_event(
        cur: Any, state: WorkflowState, sequence: int, previous_hash: str | None,
        from_stage: str, to_stage: str, resulting_hash: str, snapshot_version: int,
        event_type: str, actor: str, message: str,
    ) -> None:
        cur.execute(
            """INSERT INTO public.workflow_events
            (workflow_id,sequence_no,event_type,from_stage,to_stage,previous_state_hash,
             resulting_state_hash,snapshot_version,actor,message)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (state.workflow_id, sequence, event_type, from_stage, to_stage, previous_hash,
             resulting_hash, snapshot_version, actor, message),
        )

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
        for collection, artifacts in (("research", state.research_artifacts), ("strategy", state.strategy_candidates),
                                       ("implementation", state.implementation_artifacts), ("validation", state.validation_results)):
            for artifact in artifacts:
                cur.execute(
                    """INSERT INTO public.artifacts
                    (artifact_id,workflow_id,collection,kind,version,producer,content)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (artifact_id) DO NOTHING""",
                    (artifact.artifact_id, state.workflow_id, collection, artifact.kind, artifact.version,
                     artifact.producer.value, artifact.content),
                )
        for assessment in state.risk_assessments:
            cur.execute(
                """INSERT INTO public.risk_assessments
                (assessment_id,workflow_id,decision,findings,controls,assessor)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (assessment_id) DO NOTHING""",
                (assessment.assessment_id, state.workflow_id, assessment.decision.value,
                 assessment.findings, assessment.controls, assessment.assessor.value),
            )
        for decision in state.decisions[decision_offset:]:
            cur.execute("INSERT INTO public.workflow_decisions (workflow_id,decision) VALUES (%s,%s)", (state.workflow_id, decision))
        for approval in state.approvals[approval_offset:]:
            cur.execute("INSERT INTO public.workflow_approvals (workflow_id,approval) VALUES (%s,%s)", (state.workflow_id, approval))
        for event in state.audit_events:
            actor = event.actor.value if hasattr(event.actor, "value") else event.actor
            cur.execute(
                """INSERT INTO public.audit_events
                (event_id,workflow_id,event_type,stage,actor,message,at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (event_id) DO NOTHING""",
                (event.event_id, state.workflow_id, event.event_type, event.stage.value, actor, event.message, event.at),
            )

    @staticmethod
    def _load_state(cur: Any, workflow: dict[str, Any]) -> WorkflowState:
        workflow_id = workflow["workflow_id"]
        cur.execute("SELECT task_id,role,objective,stage,status FROM public.agent_tasks WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        tasks = [AgentTask.model_validate(row) for row in cur.fetchall()]
        cur.execute("SELECT artifact_id,kind,version,producer,content,created_at,collection FROM public.artifacts WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        artifacts = cur.fetchall()
        cur.execute("SELECT assessment_id,decision,findings,controls,assessor FROM public.risk_assessments WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        risks = [RiskAssessment.model_validate(row) for row in cur.fetchall()]
        cur.execute("SELECT decision FROM public.workflow_decisions WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        decisions = [row["decision"] for row in cur.fetchall()]
        cur.execute("SELECT approval FROM public.workflow_approvals WHERE workflow_id=%s ORDER BY created_at", (workflow_id,))
        approvals = [row["approval"] for row in cur.fetchall()]
        cur.execute("SELECT event_id,event_type,stage,actor,message,at FROM public.audit_events WHERE workflow_id=%s ORDER BY at", (workflow_id,))
        events = [AuditEvent.model_validate(row) for row in cur.fetchall()]
        return WorkflowState(
            workflow_id=workflow_id, workspace_id=workflow.get("workspace_id"), schema_version=workflow["schema_version"],
            product_goal=workflow["product_goal"], product_brief=workflow["product_brief"], roadmap=workflow["roadmap"],
            current_stage=workflow["current_stage"], agent_tasks=tasks,
            research_artifacts=[Artifact.model_validate({k: v for k, v in row.items() if k != "collection"}) for row in artifacts if row["collection"] == "research"],
            strategy_candidates=[Artifact.model_validate({k: v for k, v in row.items() if k != "collection"}) for row in artifacts if row["collection"] == "strategy"],
            implementation_artifacts=[Artifact.model_validate({k: v for k, v in row.items() if k != "collection"}) for row in artifacts if row["collection"] == "implementation"],
            validation_results=[Artifact.model_validate({k: v for k, v in row.items() if k != "collection"}) for row in artifacts if row["collection"] == "validation"],
            risk_assessments=risks, decisions=decisions, approvals=approvals,
            iteration_count=workflow["iteration_count"], budgets=workflow["budgets"], final_package=workflow["final_package"], audit_events=events,
        )


def connection_factory_from_dsn(dsn: str) -> ConnectionFactory:
    """Build a PostgreSQL connection factory from a secure DSN."""
    if not dsn.strip():
        raise ValueError("dsn must not be empty")

    def factory() -> Connection[Any]:
        from psycopg import connect
        return connect(dsn, row_factory=dict_row)

    return factory
