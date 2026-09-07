"""Durable PostgreSQL storage for Phase 3 platform metadata and artifacts."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .productization import ArtifactRecord, KnowledgeDocument, ToolDefinition, Workspace

ConnectionFactory = Callable[[], Connection[Any]]


class PlatformRepository:
    """Persist product workspaces and productization metadata transactionally."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @contextmanager
    def _connection(self) -> Iterator[Connection[Any]]:
        with self._connection_factory() as connection:
            yield connection

    def create_workspace(self, workspace: Workspace) -> Workspace:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.product_workspaces
                (workspace_id,name,product_goal,status,priority,strategies,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (workspace.workspace_id, workspace.name, workspace.product_goal, workspace.status,
                 workspace.priority, Jsonb([item.model_dump(mode="json") for item in workspace.strategies]),
                 workspace.created_at, workspace.updated_at),
            )
        return workspace

    def list_workspaces(self) -> list[Workspace]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.product_workspaces ORDER BY priority DESC, created_at")
            return [Workspace.model_validate(row) for row in cur.fetchall()]

    def put_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT COALESCE(MAX(version),0) AS version FROM public.product_artifacts
                   WHERE workspace_id=%s AND kind=%s""",
                (artifact.workspace_id, artifact.kind),
            )
            version = int(cur.fetchone()["version"]) + 1
            artifact.version = version
            cur.execute(
                """INSERT INTO public.product_artifacts
                (artifact_id,workspace_id,kind,version,producer,content,content_hash,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (artifact.artifact_id, artifact.workspace_id, artifact.kind, artifact.version,
                 artifact.producer, Jsonb(artifact.content), artifact.content_hash, artifact.created_at),
            )
        return artifact

    def list_artifacts(self, workspace_id: UUID) -> list[ArtifactRecord]:
        with self._connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.product_artifacts WHERE workspace_id=%s ORDER BY created_at",
                        (workspace_id,))
            return [ArtifactRecord.model_validate(row) for row in cur.fetchall()]

    def upsert_knowledge(self, document: KnowledgeDocument) -> KnowledgeDocument:
        with self._connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.knowledge_documents
                (document_id,title,text,source,tags,version,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET title=EXCLUDED.title,text=EXCLUDED.text,
                source=EXCLUDED.source,tags=EXCLUDED.tags,version=public.knowledge_documents.version+1
                RETURNING version""",
                (document.document_id, document.title, document.text, document.source, document.tags,
                 document.version, document.created_at),
            )
            document.version = int(cur.fetchone()["version"])
        return document

    def register_tool(self, tool: ToolDefinition) -> ToolDefinition:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.platform_tools
                (name,description,allowed,input_schema,output_schema)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (name) DO UPDATE SET description=EXCLUDED.description,
                allowed=EXCLUDED.allowed,input_schema=EXCLUDED.input_schema,output_schema=EXCLUDED.output_schema""",
                (tool.name, tool.description, tool.allowed, Jsonb(tool.input_schema), Jsonb(tool.output_schema)),
            )
        return tool


def connection_factory_from_dsn(dsn: str) -> ConnectionFactory:
    """Build a connection factory without storing credentials in application code."""
    if not dsn.strip():
        raise ValueError("dsn must not be empty")

    def factory() -> Connection[Any]:
        from psycopg import connect

        return connect(dsn, row_factory=dict_row)

    return factory
