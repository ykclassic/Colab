"""Production PostgreSQL-backed service implementations for the FastAPI platform."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import Connection, OperationalError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .operations import ExecutionJob, MetricsSnapshot, OperationalEvent
from .productization import (
    ArtifactRecord,
    KnowledgeDocument,
    ToolDefinition,
    Workspace,
    WorkspaceStatus,
)

ConnectionFactory = Callable[[], Connection[Any]]


class PostgresPlatformStore:
    """Durable Phase 3/4 storage using one short-lived transaction per operation."""

    def __init__(self, connection_factory: ConnectionFactory, max_concurrent: int = 2) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self._connection_factory = connection_factory
        self.max_concurrent = max_concurrent

    @contextmanager
    def _connection(self) -> Iterator[Connection[Any]]:
        with self._connection_factory() as connection:
            yield connection

    def check_ready(self) -> None:
        """Raise OperationalError when PostgreSQL is not reachable."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone() != (1,):
                raise OperationalError("database readiness query returned an unexpected result")

    def submit_workspace(self, workspace: Workspace) -> Workspace:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.product_workspaces
                (workspace_id,name,product_goal,status,priority,strategies,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    workspace.workspace_id,
                    workspace.name,
                    workspace.product_goal,
                    workspace.status,
                    workspace.priority,
                    Jsonb([strategy.model_dump(mode="json") for strategy in workspace.strategies]),
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
            self._schedule_workspaces(cur)
        return workspace

    def get_workspace(self, workspace_id: UUID) -> Workspace:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM public.product_workspaces WHERE workspace_id=%s",
                (workspace_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise KeyError(str(workspace_id))
        return Workspace.model_validate(row)

    def list_workspaces(self) -> list[Workspace]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM public.product_workspaces ORDER BY priority DESC, created_at"
            )
            return [Workspace.model_validate(row) for row in cur.fetchall()]

    def _schedule_workspaces(self, cur: Any) -> None:
        """Serialize admission decisions so multiple API instances share one scheduler."""
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('colab:workspace:scheduler'))")
        cur.execute(
            "SELECT count(*) AS running FROM public.product_workspaces WHERE status=%s",
            (WorkspaceStatus.RUNNING,),
        )
        row = cur.fetchone()
        running = int(row[0] if not isinstance(row, dict) else row["running"])
        slots = max(0, self.max_concurrent - running)
        if slots <= 0:
            return
        cur.execute(
            """UPDATE public.product_workspaces
               SET status=%s, updated_at=now()
             WHERE workspace_id IN (
                 SELECT workspace_id FROM public.product_workspaces
                  WHERE status=%s
                  ORDER BY priority DESC, created_at, workspace_id
                  LIMIT %s
             )""",
            (WorkspaceStatus.RUNNING, WorkspaceStatus.QUEUED, slots),
        )

    def put_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            lock_key = f"colab:artifact:{artifact.workspace_id}:{artifact.kind}"
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
            cur.execute(
                """SELECT artifact_id, version FROM public.product_artifacts
                   WHERE workspace_id=%s AND kind=%s AND content_hash=%s
                   ORDER BY version LIMIT 1""",
                (artifact.workspace_id, artifact.kind, artifact.content_hash),
            )
            existing = cur.fetchone()
            if existing is not None:
                cur.execute(
                    "SELECT * FROM public.product_artifacts WHERE artifact_id=%s",
                    (existing["artifact_id"],),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("artifact disappeared during idempotent lookup")
                return ArtifactRecord.model_validate(row)

            cur.execute(
                """SELECT COALESCE(MAX(version),0) AS version
                     FROM public.product_artifacts
                    WHERE workspace_id=%s AND kind=%s""",
                (artifact.workspace_id, artifact.kind),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("artifact version query returned no row")
            artifact.version = int(row["version"]) + 1
            cur.execute(
                """INSERT INTO public.product_artifacts
                (artifact_id,workspace_id,kind,version,producer,content,content_hash,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    artifact.artifact_id,
                    artifact.workspace_id,
                    artifact.kind,
                    artifact.version,
                    artifact.producer,
                    Jsonb(artifact.content),
                    artifact.content_hash,
                    artifact.created_at,
                ),
            )
        return artifact

    def list_artifacts(self, workspace_id: UUID) -> list[ArtifactRecord]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT * FROM public.product_artifacts
                    WHERE workspace_id=%s ORDER BY created_at, version""",
                (workspace_id,),
            )
            return [ArtifactRecord.model_validate(row) for row in cur.fetchall()]

    def upsert_knowledge(self, document: KnowledgeDocument) -> KnowledgeDocument:
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.knowledge_documents
                (document_id,title,text,source,tags,version,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET
                    title=EXCLUDED.title,
                    text=EXCLUDED.text,
                    source=EXCLUDED.source,
                    tags=EXCLUDED.tags,
                    version=public.knowledge_documents.version+1
                RETURNING *""",
                (
                    document.document_id,
                    document.title,
                    document.text,
                    document.source,
                    document.tags,
                    document.version,
                    document.created_at,
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("knowledge upsert returned no row")
        return KnowledgeDocument.model_validate(row)

    def search_knowledge(self, query: str, limit: int = 10) -> list[KnowledgeDocument]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        terms = {term.lower() for term in query.split() if term.strip()}
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.knowledge_documents")
            documents = [KnowledgeDocument.model_validate(row) for row in cur.fetchall()]
        scored: list[tuple[int, KnowledgeDocument]] = []
        for document in documents:
            haystack = f"{document.title} {document.text} {' '.join(document.tags)}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].created_at, str(item[1].document_id)))
        return [document for _, document in scored[:limit]]

    def register_tool(self, tool: ToolDefinition) -> ToolDefinition:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.platform_tools
                (name,description,allowed,input_schema,output_schema)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (name) DO UPDATE SET
                    description=EXCLUDED.description,
                    allowed=EXCLUDED.allowed,
                    input_schema=EXCLUDED.input_schema,
                    output_schema=EXCLUDED.output_schema""",
                (
                    tool.name,
                    tool.description,
                    tool.allowed,
                    Jsonb(tool.input_schema),
                    Jsonb(tool.output_schema),
                ),
            )
        return tool

    def list_tools(self) -> list[ToolDefinition]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.platform_tools ORDER BY name")
            return [ToolDefinition.model_validate(row) for row in cur.fetchall()]

    def enqueue_execution(
        self,
        workflow_id: UUID,
        workspace_id: UUID,
        stage: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.workflow_execution_jobs
                (job_id,workflow_id,workspace_id,stage,idempotency_key,status,attempt,max_attempts,
                 created_at,updated_at)
                VALUES (gen_random_uuid(),%s,%s,%s,%s,'pending',0,%s,%s,%s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING *""",
                (workflow_id, workspace_id, stage, idempotency_key, max_attempts, now, now),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT * FROM public.workflow_execution_jobs WHERE idempotency_key=%s",
                    (idempotency_key,),
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError("execution enqueue returned no row")
        return ExecutionJob.model_validate(row)

    def claim_execution(self, worker_id: str, lease_seconds: int) -> ExecutionJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            self._requeue_expired(cur, now)
            cur.execute(
                """WITH candidate AS (
                    SELECT job_id FROM public.workflow_execution_jobs
                     WHERE status='pending'
                     ORDER BY created_at, job_id
                     FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE public.workflow_execution_jobs AS job
                   SET status='running', attempt=job.attempt+1,
                       lease_owner=%s, lease_expires_at=%s, updated_at=%s
                 WHERE job.job_id=(SELECT job_id FROM candidate)
                RETURNING job.*""",
                (worker_id, expires, now),
            )
            row = cur.fetchone()
        return ExecutionJob.model_validate(row) if row is not None else None

    def heartbeat_execution(self, job_id: UUID, worker_id: str, lease_seconds: int) -> ExecutionJob:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.workflow_execution_jobs
                      SET lease_expires_at=%s, updated_at=%s
                    WHERE job_id=%s AND status='running' AND lease_owner=%s
                      AND lease_expires_at > %s
                RETURNING *""",
                (expires, now, job_id, worker_id, now),
            )
            row = cur.fetchone()
        return self._require_owned_job(row, "job is not running or lease is not owned")

    def complete_execution(self, job_id: UUID, worker_id: str) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.workflow_execution_jobs
                      SET status='succeeded', lease_owner=NULL, lease_expires_at=NULL,
                          completed_at=%s, updated_at=%s
                    WHERE job_id=%s AND status='running' AND lease_owner=%s
                      AND lease_expires_at > %s
                RETURNING *""",
                (now, now, job_id, worker_id, now),
            )
            row = cur.fetchone()
        return self._require_owned_job(row, "job is not running or lease is not owned")

    def fail_execution(self, job_id: UUID, worker_id: str, error: str) -> ExecutionJob:
        if not error.strip():
            raise ValueError("error must not be empty")
        now = datetime.now(UTC)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.workflow_execution_jobs
                      SET status=CASE WHEN attempt < max_attempts THEN 'pending' ELSE 'failed' END,
                          lease_owner=NULL, lease_expires_at=NULL, error=%s,
                          completed_at=CASE WHEN attempt < max_attempts THEN NULL ELSE %s END,
                          updated_at=%s
                    WHERE job_id=%s AND status='running' AND lease_owner=%s
                      AND lease_expires_at > %s
                RETURNING *""",
                (error[:5000], now, now, job_id, worker_id, now),
            )
            row = cur.fetchone()
        return self._require_owned_job(row, "job is not running or lease is not owned")

    def cancel_execution(self, job_id: UUID) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.workflow_execution_jobs
                      SET status='cancelled', lease_owner=NULL, lease_expires_at=NULL,
                          completed_at=%s, updated_at=%s
                    WHERE job_id=%s AND status NOT IN ('succeeded','failed','cancelled')
                RETURNING *""",
                (now, now, job_id),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT * FROM public.workflow_execution_jobs WHERE job_id=%s",
                    (job_id,),
                )
                row = cur.fetchone()
        return self._require_existing_job(row, job_id)

    def _requeue_expired(self, cur: Any, now: datetime) -> None:
        cur.execute(
            """UPDATE public.workflow_execution_jobs
                  SET status=CASE WHEN attempt < max_attempts THEN 'pending' ELSE 'failed' END,
                      lease_owner=NULL, lease_expires_at=NULL,
                      error=CASE WHEN attempt < max_attempts THEN error ELSE 'execution lease expired' END,
                      completed_at=CASE WHEN attempt < max_attempts THEN NULL ELSE %s END,
                      updated_at=%s
                WHERE status='running' AND lease_expires_at <= %s""",
            (now, now, now),
        )

    @staticmethod
    def _require_existing_job(row: Any, job_id: UUID) -> ExecutionJob:
        if row is None:
            raise KeyError(str(job_id))
        return ExecutionJob.model_validate(row)

    @staticmethod
    def _require_owned_job(row: Any, message: str) -> ExecutionJob:
        if row is None:
            raise RuntimeError(message)
        return ExecutionJob.model_validate(row)

    def record_event(self, event: OperationalEvent) -> OperationalEvent:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.workflow_operational_events
                (event_id,workflow_id,workspace_id,job_id,event_type,level,actor,message,metadata,occurred_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    event.event_id,
                    event.workflow_id,
                    event.workspace_id,
                    event.job_id,
                    event.event_type,
                    event.level,
                    event.actor,
                    event.message,
                    Jsonb(event.metadata),
                    event.occurred_at,
                ),
            )
        return event

    def query_events(
        self,
        workflow_id: UUID | None = None,
        workspace_id: UUID | None = None,
        job_id: UUID | None = None,
        limit: int = 100,
    ) -> list[OperationalEvent]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        filters: list[str] = []
        values: list[Any] = []
        if workflow_id is not None:
            filters.append("workflow_id=%s")
            values.append(workflow_id)
        if workspace_id is not None:
            filters.append("workspace_id=%s")
            values.append(workspace_id)
        if job_id is not None:
            filters.append("job_id=%s")
            values.append(job_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        values.append(limit)
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""SELECT * FROM public.workflow_operational_events
                    {where} ORDER BY occurred_at DESC LIMIT %s""",
                values,
            )
            return [OperationalEvent.model_validate(row) for row in cur.fetchall()]

    def metrics(self) -> MetricsSnapshot:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT status, count(*)::int AS count
                     FROM public.workflow_execution_jobs GROUP BY status"""
            )
            counts = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}
            cur.execute(
                """SELECT COALESCE(sum(GREATEST(attempt - 1, 0)), 0)::int AS retries
                     FROM public.workflow_execution_jobs"""
            )
            retries_row = cur.fetchone()
            cur.execute(
                """SELECT count(*) FILTER (WHERE event_type='execution_lease_expired')::int AS expired_leases
                     FROM public.workflow_operational_events"""
            )
            lease_row = cur.fetchone()
        return MetricsSnapshot(
            pending=counts.get("pending", 0),
            running=counts.get("running", 0),
            succeeded=counts.get("succeeded", 0),
            failed=counts.get("failed", 0),
            cancelled=counts.get("cancelled", 0),
            retries=int(retries_row["retries"] if retries_row else 0),
            expired_leases=int(lease_row["expired_leases"] if lease_row else 0),
        )


def connection_factory_from_dsn(dsn: str) -> ConnectionFactory:
    """Create a fresh psycopg connection for each unit of work without logging the DSN."""
    if not dsn.strip():
        raise ValueError("dsn must not be empty")

    def factory() -> Connection[Any]:
        from psycopg import connect

        return connect(dsn, row_factory=dict_row)

    return factory
