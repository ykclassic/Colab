from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from colab.api import PlatformServices, create_app
from colab.productization import Workspace, WorkspaceManager


def test_in_memory_workspace_idempotency_and_lifecycle() -> None:
    manager = WorkspaceManager(max_concurrent=2)
    key = "retry-safe-create"
    first = manager.submit(Workspace(name="Alpha", product_goal="Build Alpha"), key)
    second = manager.submit(Workspace(name="Alpha duplicate", product_goal="Should not create"), key)
    assert second.workspace_id == first.workspace_id
    assert len(manager.list()) == 1

    updated = manager.update(
        first.workspace_id, first.version, name="Alpha 2", product_goal="Updated goal",
        priority=50, strategies=[],
    )
    assert updated.version == 2
    assert updated.name == "Alpha 2"

    with pytest.raises(RuntimeError, match="version conflict"):
        manager.update(first.workspace_id, 1, name="stale", product_goal="stale", priority=1, strategies=[])

    archived = manager.archive(first.workspace_id, updated.version)
    assert archived.status == "archived"
    assert manager.list() == []
    assert manager.list(include_archived=True)[0].status == "archived"

    restored = manager.restore(first.workspace_id, archived.version)
    assert restored.status == "running"
    manager.archive(first.workspace_id, restored.version)
    manager.delete(first.workspace_id, restored.version + 1)
    assert manager.list(include_archived=True) == []


def test_workspace_http_management_and_duplicate_post() -> None:
    app = create_app(PlatformServices(max_concurrent=2))
    client = TestClient(app)
    key = str(uuid4())
    payload = {"name": "HTTP workspace", "product_goal": "Test management"}

    first = client.post("/api/workspaces", json=payload, headers={"Idempotency-Key": key})
    duplicate = client.post("/api/workspaces", json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    assert duplicate.status_code == 201
    assert first.json()["workspace_id"] == duplicate.json()["workspace_id"]

    workspace = first.json()
    workspace_id = workspace["workspace_id"]
    update = client.patch(
        f"/api/workspaces/{workspace_id}",
        json={"version": workspace["version"], "name": "Edited", "product_goal": "Edited goal", "priority": 10, "strategies": []},
    )
    assert update.status_code == 200
    assert update.json()["version"] == workspace["version"] + 1

    archive = client.post(f"/api/workspaces/{workspace_id}/archive", json={"version": update.json()["version"]})
    assert archive.status_code == 200
    assert archive.json()["status"] == "archived"

    deleted = client.delete(f"/api/workspaces/{workspace_id}", json={"version": archive.json()["version"]})
    assert deleted.status_code == 204
    assert client.get(f"/api/workspaces/{workspace_id}").status_code == 404
