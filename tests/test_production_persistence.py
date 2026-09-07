from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from colab.api import PlatformServices, create_app
from colab.production_persistence import connection_factory_from_dsn


def test_connection_factory_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn must not be empty"):
        connection_factory_from_dsn("   ")


def test_production_requires_database_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_ENV", "production")
    monkeypatch.delenv("COLAB_DATABASE_DSN", raising=False)
    with pytest.raises(RuntimeError, match="COLAB_DATABASE_DSN"):
        PlatformServices()


def test_local_services_remain_in_memory_when_not_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_ENV", "development")
    monkeypatch.delenv("COLAB_DATABASE_DSN", raising=False)
    services = PlatformServices()
    client = TestClient(create_app(services))

    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "not_configured"

    created = client.post(
        "/api/workspaces",
        json={"name": "local-test", "product_goal": "exercise local composition"},
    )
    assert created.status_code == 201
    workspace_id = created.json()["workspace_id"]

    listed = client.get("/api/workspaces")
    assert listed.status_code == 200
    assert listed.json()[0]["workspace_id"] == workspace_id
