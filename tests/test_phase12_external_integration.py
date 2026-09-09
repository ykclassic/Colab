from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from colab.external_integration import (
    ConnectorDefinition,
    ExternalIntegrationError,
    ExternalIntegrationRegistry,
)
from colab.external_integration_api import register_external_integration_routes


def test_connector_requires_https_and_scopes_paths() -> None:
    with pytest.raises(ValueError):
        ConnectorDefinition("data", "http://example.com", ("/v1",))
    registry = ExternalIntegrationRegistry(lambda *_args, **_kwargs: b'{}')
    registry.register(ConnectorDefinition("data", "https://example.com", ("/v1",)))
    with pytest.raises(ExternalIntegrationError):
        registry.fetch_json("data", "/admin")


def test_execution_capabilities_are_not_registerable() -> None:
    registry = ExternalIntegrationRegistry()
    with pytest.raises(ExternalIntegrationError):
        registry.register(ConnectorDefinition("trade-execution", "https://example.com"))
    with pytest.raises(ExternalIntegrationError):
        registry.register(ConnectorDefinition("orders", "https://example.com"))


def test_fetch_is_read_only_bounded_and_audited() -> None:
    calls: list[str] = []

    def transport(definition: ConnectorDefinition, target: str, query: dict[str, str]) -> bytes:
        calls.append(target)
        assert definition.secret_env is None
        assert query == {"symbol": "EURUSD"}
        return json.dumps({"value": 123}).encode()

    registry = ExternalIntegrationRegistry(transport)
    registry.register(ConnectorDefinition("market-data", "https://data.example.com", ("/v1",)))
    request_id, data = registry.fetch_json("market-data", "/v1/quote", {"symbol": "EURUSD"})
    assert data == {"value": 123}
    assert str(request_id)
    assert calls == ["https://data.example.com/v1/quote"]
    assert registry.audit()[0].success is True


def test_oversized_responses_are_rejected_without_leaking_payload() -> None:
    registry = ExternalIntegrationRegistry(lambda *_args, **_kwargs: b"x" * 2049)
    registry.register(ConnectorDefinition("data", "https://data.example.com", ("/",), max_response_bytes=2048))
    with pytest.raises(ExternalIntegrationError, match="exceeds configured size limit"):
        registry.fetch_json("data")
    assert registry.audit()[0].error == "external response exceeds configured size limit"


def test_http_api_exposes_only_read_operation() -> None:
    registry = ExternalIntegrationRegistry(lambda *_args, **_kwargs: b'{"ok":true}')
    registry.register(ConnectorDefinition("data", "https://data.example.com", ("/",)))
    app = FastAPI()
    register_external_integration_routes(app, registry)
    client = TestClient(app)
    response = client.post("/api/integrations/data/fetch", json={"path": "/"})
    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert client.post("/api/integrations/data/order", json={}).status_code == 404
