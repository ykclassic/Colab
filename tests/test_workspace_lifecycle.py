from __future__ import annotations

from collections import deque

import pytest

from colab.productization import Workspace, WorkspaceStatus
from colab.workspace_lifecycle import WorkspaceLifecycleStore


class FakeCursor:
    def __init__(self, results: list[object] | None = None, rows: list[dict] | None = None) -> None:
        self.results = deque(results or [])
        self.rows = rows or []
        self.executed: list[str] = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.executed.append(sql)
    def fetchone(self): return self.results.popleft() if self.results else None
    def fetchall(self): return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def transaction(self): return self
    def cursor(self, row_factory=None): return self._cursor


def workspace_row(workspace: Workspace, *, status: str | None = None, version: int | None = None) -> dict:
    row = workspace.model_dump(mode="python")
    row["status"] = status or workspace.status
    row["version"] = version or workspace.version
    row["strategies"] = []
    return row


def make_store(results: list[object] | None = None, rows: list[dict] | None = None) -> tuple[WorkspaceLifecycleStore, FakeCursor]:
    cursor = FakeCursor(results, rows)
    store = WorkspaceLifecycleStore(lambda: FakeConnection(cursor), max_concurrent=2)
    return store, cursor


def test_submit_get_and_list_paths() -> None:
    workspace = Workspace(name="Alpha", product_goal="Goal")
    row = workspace_row(workspace)

    store, _ = make_store([row, {"count": 0}])
    assert store.submit(workspace).workspace_id == workspace.workspace_id

    existing_store, existing_cursor = make_store([None, row])
    assert existing_store.submit(workspace, "same-key").workspace_id == workspace.workspace_id
    assert "ON CONFLICT (create_idempotency_key) WHERE create_idempotency_key IS NOT NULL DO NOTHING" in existing_cursor.executed[0]
    assert any("SELECT * FROM public.product_workspaces WHERE create_idempotency_key=%s" in sql for sql in existing_cursor.executed)

    inserted_store, inserted_cursor = make_store([row, {"count": 0}])
    assert inserted_store.submit(workspace, "new-key").workspace_id == workspace.workspace_id
    assert sum("pg_advisory_xact_lock" in sql for sql in inserted_cursor.executed) == 1

    get_store, _ = make_store([row])
    assert get_store.get(workspace.workspace_id).workspace_id == workspace.workspace_id

    missing_store, _ = make_store([None])
    with pytest.raises(KeyError):
        missing_store.get(workspace.workspace_id)

    list_store, _ = make_store(rows=[row])
    assert len(list_store.list()) == 1
    assert len(list_store.list(include_archived=True)) == 1


def test_idempotency_conflict_without_winner_is_an_error() -> None:
    workspace = Workspace(name="Alpha", product_goal="Goal")
    store, _ = make_store([None, None])
    with pytest.raises(RuntimeError, match="idempotency conflict"):
        store.submit(workspace, "same-key")


def test_update_archive_restore_and_delete_paths() -> None:
    workspace = Workspace(name="Alpha", product_goal="Goal")
    updated_row = workspace_row(workspace, status=WorkspaceStatus.RUNNING, version=2)

    store, _ = make_store([updated_row, {"count": 0}])
    assert store.update(workspace.workspace_id, 1, name="Edited", product_goal="New goal", priority=10, strategies=[]).version == 2

    archived_row = workspace_row(workspace, status=WorkspaceStatus.ARCHIVED, version=3)
    archive_store, _ = make_store([archived_row])
    assert archive_store.archive(workspace.workspace_id, 2).status == WorkspaceStatus.ARCHIVED

    restored_row = workspace_row(workspace, status=WorkspaceStatus.RUNNING, version=4)
    restore_store, _ = make_store([restored_row, {"count": 0}])
    assert restore_store.restore(workspace.workspace_id, 3).version == 4

    delete_row = workspace_row(workspace, status=WorkspaceStatus.ARCHIVED, version=5)
    delete_store, _ = make_store([delete_row])
    assert delete_store.delete(workspace.workspace_id, 5) is None


def test_version_and_state_conflicts() -> None:
    workspace = Workspace(name="Alpha", product_goal="Goal")
    row = workspace_row(workspace, version=2)

    for method, args in [
        ("update", {"name": "x", "product_goal": "y", "priority": 1, "strategies": []}),
        ("archive", {}),
        ("restore", {}),
    ]:
        store, _ = make_store([None, {"version": 2}])
        with pytest.raises(RuntimeError, match="version conflict"):
            getattr(store, method)(workspace.workspace_id, 1, **args)

    missing_store, _ = make_store([None, None])
    with pytest.raises(KeyError):
        missing_store.delete(workspace.workspace_id, 1)

    active_store, _ = make_store([row])
    with pytest.raises(ValueError, match="must be archived"):
        active_store.delete(workspace.workspace_id, 2)

    stale_store, _ = make_store([row])
    with pytest.raises(RuntimeError, match="version conflict"):
        stale_store.delete(workspace.workspace_id, 1)

    missing_insert_store, _ = make_store([None, {"count": 0}])
    with pytest.raises(RuntimeError, match="insert returned no row"):
        missing_insert_store.submit(workspace)


def test_scheduler_respects_concurrency() -> None:
    store, cursor = make_store([{"count": 0}])
    store._schedule(cursor)
    assert any("pg_advisory_xact_lock" in sql for sql in cursor.executed)


def test_invalid_concurrency_limit() -> None:
    with pytest.raises(ValueError, match="max_concurrent"):
        WorkspaceLifecycleStore(lambda: FakeConnection(FakeCursor()), max_concurrent=0)
