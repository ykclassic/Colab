"""Phase 21 production verification: authentication and tenant-bound API boundaries."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from colab.api import app
from colab.collaboration_api import CollaborationRunRequest
from colab.quant_api import QuantRunRequest


@pytest.fixture(autouse=True)
def _test_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_REQUIRE_AUTH", "true")
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")


def _client() -> TestClient:
    return TestClient(app)


def test_api_requires_authentication() -> None:
    client = _client()
    response = client.get("/api/agents/registry/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 401


def test_workspace_mutation_requires_write_permission() -> None:
    client = _client()
    workspace_id = uuid4()
    response = client.patch(
        f"/api/workspaces/{workspace_id}",
        headers={"X-Test-User": str(uuid4()), "X-Test-Role": "reviewer"},
        json={"version": 1, "name": "x", "product_goal": "y"},
    )
    assert response.status_code == 403


def test_collaboration_request_is_workspace_bound() -> None:
    fields = {"product_goal": "test", "tasks": []}
    with pytest.raises(ValidationError):
        CollaborationRunRequest.model_validate(fields)


def test_quant_request_is_workspace_bound() -> None:
    fields = {"symbol": "TEST", "bars": []}
    with pytest.raises(ValidationError):
        QuantRunRequest.model_validate(fields)


def test_test_auth_header_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_REQUIRE_AUTH", "true")
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "false")
    client = _client()
    response = client.get(
        "/api/auth/me",
        headers={"X-Test-User": str(uuid4()), "X-Test-Role": "owner"},
    )
    assert response.status_code == 401
