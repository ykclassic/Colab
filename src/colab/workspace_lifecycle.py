"""Durable workspace lifecycle operations with idempotency and optimistic concurrency."""
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .productization import StrategySpec, Workspace, WorkspaceStatus

ConnectionFactory = Callable[[], Connection[Any]]


class WorkspaceLifecycleStore:
    def __init__(self, connection_factory: ConnectionFactory, max_concurrent: int = 2) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self._connection_factory = connection_factory
        self.max_concurrent = max_concurrent

    def submit(self, workspace: Workspace, idempotency_key: str | None = None) -> Workspace:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            if idempotency_key:
                cur.execute("SELECT * FROM public.product_workspaces WHERE create_idempotency_key=%s", (idempotency_key,))
                existing = cur.fetchone()
                if existing is not None:
                    return Workspace.model_validate(existing)
            cur.execute(
                """INSERT INTO public.product_workspaces
                (workspace_id,name,product_goal,status,priority,strategies,created_by,version,archived_at,create_idempotency_key,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (workspace.workspace_id, workspace.name, workspace.product_goal, workspace.status, workspace.priority,
                 Jsonb([strategy.model_dump(mode="json") for strategy in workspace.strategies]), workspace.created_by,
                 workspace.version, workspace.archived_at, idempotency_key, workspace.created_at, workspace.updated_at),
            )
            row = cur.fetchone()
            self._schedule(cur)
            if row is None:
                raise RuntimeError("workspace insert returned no row")
            return Workspace.model_validate(row)

    def get(self, workspace_id: UUID) -> Workspace:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.product_workspaces WHERE workspace_id=%s", (workspace_id,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(str(workspace_id))
        return Workspace.model_validate(row)

    def list(self, include_archived: bool = False) -> builtins.list[Workspace]:
        sql = "SELECT * FROM public.product_workspaces"
        if not include_archived:
            sql += " WHERE status <> %s"
        sql += " ORDER BY priority DESC, created_at"
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, () if include_archived else (WorkspaceStatus.ARCHIVED,))
            return [Workspace.model_validate(row) for row in cur.fetchall()]

    def update(self, workspace_id: UUID, expected_version: int, *, name: str, product_goal: str, priority: int, strategies: list[StrategySpec]) -> Workspace:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.product_workspaces
                   SET name=%s, product_goal=%s, priority=%s, strategies=%s,
                       version=version+1, updated_at=now()
                 WHERE workspace_id=%s AND version=%s AND status <> %s RETURNING *""",
                (name, product_goal, priority, Jsonb([s.model_dump(mode="json") for s in strategies]), workspace_id, expected_version, WorkspaceStatus.ARCHIVED),
            )
            row = cur.fetchone()
            if row is None:
                self._raise_version_or_missing(cur, workspace_id, expected_version, "workspace cannot be edited")
            self._schedule(cur)
            return Workspace.model_validate(row)

    def archive(self, workspace_id: UUID, expected_version: int) -> Workspace:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.product_workspaces
                   SET status=%s, archived_at=now(), version=version+1, updated_at=now()
                 WHERE workspace_id=%s AND version=%s AND status <> %s RETURNING *""",
                (WorkspaceStatus.ARCHIVED, workspace_id, expected_version, WorkspaceStatus.ARCHIVED),
            )
            row = cur.fetchone()
            if row is None:
                self._raise_version_or_missing(cur, workspace_id, expected_version, "workspace cannot be archived")
            return Workspace.model_validate(row)

    def restore(self, workspace_id: UUID, expected_version: int) -> Workspace:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE public.product_workspaces
                   SET status=%s, archived_at=NULL, version=version+1, updated_at=now()
                 WHERE workspace_id=%s AND version=%s AND status=%s RETURNING *""",
                (WorkspaceStatus.QUEUED, workspace_id, expected_version, WorkspaceStatus.ARCHIVED),
            )
            row = cur.fetchone()
            if row is None:
                self._raise_version_or_missing(cur, workspace_id, expected_version, "workspace is not archived or version changed")
            self._schedule(cur)
            return Workspace.model_validate(row)

    def delete(self, workspace_id: UUID, expected_version: int) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.product_workspaces WHERE workspace_id=%s FOR UPDATE", (workspace_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(str(workspace_id))
            current = Workspace.model_validate(row)
            if current.version != expected_version:
                raise RuntimeError(f"workspace version conflict: expected {expected_version}, current {current.version}")
            if current.status != WorkspaceStatus.ARCHIVED:
                raise ValueError("workspace must be archived before permanent deletion")
            cur.execute("DELETE FROM public.product_workspaces WHERE workspace_id=%s", (workspace_id,))

    def _schedule(self, cur: Any) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('colab:workspace:scheduler'))")
        cur.execute("SELECT count(*) FROM public.product_workspaces WHERE status=%s", (WorkspaceStatus.RUNNING,))
        running = int(cur.fetchone()[0])
        slots = max(0, self.max_concurrent - running)
        if slots:
            cur.execute(
                """UPDATE public.product_workspaces SET status=%s, updated_at=now()
                   WHERE workspace_id IN (
                     SELECT workspace_id FROM public.product_workspaces
                     WHERE status=%s ORDER BY priority DESC, created_at, workspace_id LIMIT %s
                   )""",
                (WorkspaceStatus.RUNNING, WorkspaceStatus.QUEUED, slots),
            )

    @staticmethod
    def _raise_version_or_missing(cur: Any, workspace_id: UUID, expected_version: int, message: str) -> None:
        cur.execute("SELECT version FROM public.product_workspaces WHERE workspace_id=%s", (workspace_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(str(workspace_id))
        raise RuntimeError(f"workspace version conflict: expected {expected_version}, current {row[0]}")
