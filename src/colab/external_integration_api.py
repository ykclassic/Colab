"""HTTP endpoints for the controlled external integration boundary."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .external_integration import ExternalIntegrationError, ExternalIntegrationRegistry
from .security import Permission, Principal, authorize_endpoint, require_workspace_membership


class ExternalFetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default="/", min_length=1, max_length=500)
    query: dict[str, str] = Field(default_factory=dict, max_length=20)
    workspace_id: UUID | None = None


def register_external_integration_routes(app: Any, registry: ExternalIntegrationRegistry) -> None:
    router = APIRouter(prefix="/api/integrations", tags=["external-integrations"])

    @router.get("")
    def list_integrations(principal: Principal = Depends(lambda request: authorize_endpoint(request, Permission.INTEGRATION_READ))) -> list[dict[str, object]]:
        del principal
        records: list[dict[str, object]] = []
        for item in registry.list_connectors():
            records.append({"name": item.name, "base_url": item.base_url, "allowed_paths": list(item.allowed_paths), "description": item.description, "read_only": True})
        return records

    @router.post("/{connector}/fetch")
    def fetch_integration(connector: str, payload: ExternalFetchRequest, principal: Principal = Depends(lambda request: authorize_endpoint(request, Permission.INTEGRATION_READ))) -> dict[str, object]:
        if payload.workspace_id is not None:
            require_workspace_membership(RequestProxy(principal, app), payload.workspace_id, Permission.WORKSPACE_READ)
        try:
            request_id, data = registry.fetch_json(connector, payload.path, payload.query)
        except ExternalIntegrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"request_id": str(request_id), "connector": connector, "read_only": True, "data": data}

    @router.get("/{connector}/audit")
    def integration_audit(connector: str, limit: int = Query(default=100, ge=1, le=1000), principal: Principal = Depends(lambda request: authorize_endpoint(request, Permission.INTEGRATION_READ))) -> list[dict[str, object]]:
        del principal
        try:
            registry.get(connector)
        except ExternalIntegrationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        records: list[dict[str, object]] = []
        for item in registry.audit():
            if item.connector == connector:
                records.append({"request_id": str(item.request_id), "connector": item.connector, "path": item.path, "status_code": item.status_code, "success": item.success, "timestamp": item.timestamp.isoformat(), "error": item.error})
        return records[-limit:]

    app.include_router(router)


class RequestProxy:
    """Minimal request facade used only to reuse the workspace authorization helper."""

    def __init__(self, principal: Principal, app: Any) -> None:
        self.state = type("State", (), {"principal": principal})()
        self.app = app
