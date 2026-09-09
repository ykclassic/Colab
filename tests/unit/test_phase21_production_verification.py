"""Phase 21 production verification: authentication and tenant-bound API boundaries."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from colab.api import create_app
from colab.collaboration_api import CollaborationRunRequest
from colab.quant_api import QuantRunRequest


@pytest.fixture(autouse=True)
def _test_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_REQUIRE_AUTH", "true")
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")


def _client() -> TestClient:
    return TestClient(create_app())


def test_api_requires_authentication() -> None:
    client = _client()
    response = client.get("/api/agents/registry/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 401


def test_authenticated_user_cannot_access_unknown_workspace() -> None:
    client = _client()
    response = client.get(
        "/api/agents/registry/00000000-0000-0000-0000-000000000001",
        headers={"X-Test-User": str(uuid4()), "X-Test-Role": "reviewer"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_collaboration_request_is_workspace_bound() -> None:
    fields = {
        "product_goal": "test",
        "tasks": [],
    }
    with pytest.raises(Exception):
        CollaborationRunRequest.model_validate(fields)


def test_quant_request_is_workspace_bound() -> None:
    fields = {
        "symbol": "TEST",
        "bars": [],
    }
    with pytest.raises(Exception):
        QuantRunRequest.model_validate(fields)


def test_authentication_headers_are_not_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_REQUIRE_AUTH", "true")
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "false")
    client = _client()
    response = client.get("/api/auth/me")
    assert response.status_code == 401
