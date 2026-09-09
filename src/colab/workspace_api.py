"""HTTP routes for workspace lifecycle management."""
from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .external_integration import ExternalIntegrationRegistry
from .external_integration_api import register_external_integration_routes
from .productization import StrategySpec, Workspace
from .research_api import router as research_router
from .research_intelligence import ResearchIntelligence
from .research_persistence import PostgresResearchIntelligenceStore
from .security import SecurityMiddleware, current_principal

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    product_goal: str = Field(min_length=1, max_length=10000)
    priority: int = Field(default=100, ge=0, le=1000)
    strategies: list[StrategySpec] = Field(default_factory=list)


class WorkspaceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


def _services(request: Request) -> Any:
    return request.app.state.services


@router.patch("/{workspace_id}", response_model=Workspace)
def update_workspace(workspace_id: UUID, payload: WorkspaceUpdate, request: Request) -> Workspace:
    try:
        result = _services(request).workspaces.update(workspace_id, payload.version, name=payload.name, product_goal=payload.product_goal, priority=payload.priority, strategies=payload.strategies)
        return cast(Workspace, result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workspace_id}/archive", response_model=Workspace)
def archive_workspace(workspace_id: UUID, payload: WorkspaceVersion, request: Request) -> Workspace:
    try:
        result = _services(request).workspaces.archive(workspace_id, payload.version)
        return cast(Workspace, result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workspace_id}/restore", response_model=Workspace)
def restore_workspace(workspace_id: UUID, payload: WorkspaceVersion, request: Request) -> Workspace:
    try:
        result = _services(request).workspaces.restore(workspace_id, payload.version)
        return cast(Workspace, result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: UUID, payload: WorkspaceVersion, request: Request) -> Response:
    try:
        _services(request).workspaces.delete(workspace_id, payload.version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def register_workspace_routes(app: Any) -> None:
    """Register lifecycle/research routes and Phase 13 security boundaries."""
    app.include_router(router)
    if not hasattr(app.state, "research_intelligence"):
        services = getattr(app.state, "services", None)
        database = getattr(services, "database", None)
        store = PostgresResearchIntelligenceStore(database._connection_factory) if database is not None else None
        app.state.research_intelligence = ResearchIntelligence(store=store)
    app.include_router(research_router)
    if not hasattr(app.state, "external_integrations"):
        app.state.external_integrations = ExternalIntegrationRegistry()
        register_external_integration_routes(app, app.state.external_integrations)
    if not any(middleware.cls is SecurityMiddleware for middleware in app.user_middleware):
        app.add_middleware(SecurityMiddleware, requests_per_minute=int(os.getenv("COLAB_RATE_LIMIT_PER_MINUTE", "120")))

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, str | None]:
        principal = current_principal(request)
        return {"user_id": principal.user_id, "role": principal.role.value, "email": principal.email, "session_id": principal.session_id}
