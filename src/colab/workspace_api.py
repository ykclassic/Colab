"""HTTP routes for workspace lifecycle management."""
from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .external_integration import ExternalIntegrationRegistry
from .external_integration_api import register_external_integration_routes
from .productization import StrategySpec, Workspace
from .research_api import router as research_router
from .research_intelligence import ResearchIntelligence
from .research_persistence import PostgresResearchIntelligenceStore
from .security import (
    Permission,
    RateLimiter,
    SecurityMiddleware,
    authorize_endpoint,
    current_principal,
)

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


class SecureWorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    product_goal: str = Field(min_length=1, max_length=10000)
    priority: int = Field(default=100, ge=0, le=1000)
    strategies: list[StrategySpec] = Field(default_factory=list)


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


def _secure_workspace_create(request: Request, payload: SecureWorkspaceCreate, idempotency_key: str | None) -> Workspace:
    principal = authorize_endpoint(request, Permission.WORKSPACE_WRITE)
    try:
        creator = UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="authenticated user id is invalid") from exc
    workspace = Workspace(name=payload.name, product_goal=payload.product_goal, priority=payload.priority, strategies=payload.strategies, created_by=creator)
    result = _services(request).workspaces.submit(workspace, idempotency_key)
    database = getattr(_services(request), "database", None)
    if database is not None:
        with database._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("""INSERT INTO public.workspace_memberships (workspace_id,user_id,role)
                           VALUES (%s,%s,'owner') ON CONFLICT (workspace_id,user_id) DO NOTHING""", (result.workspace_id, creator))
    return cast(Workspace, result)


def _secure_workspace_list(request: Request, include_archived: bool) -> list[Workspace]:
    principal = authorize_endpoint(request, Permission.WORKSPACE_READ)
    services = _services(request)
    database = getattr(services, "database", None)
    if database is None:
        items = services.workspaces.list(include_archived)
        if principal.user_id == "development":
            return list(items)
        return [item for item in items if item.created_by is not None and str(item.created_by) == principal.user_id]
    try:
        user_id = UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="authenticated user id is invalid") from exc
    with database._connection_factory() as conn, conn.cursor() as cur:
        sql = """SELECT w.workspace_id FROM public.product_workspaces w
                 INNER JOIN public.workspace_memberships m ON m.workspace_id=w.workspace_id
                 WHERE m.user_id=%s"""
        params: list[Any] = [user_id]
        if not include_archived:
            sql += " AND w.status <> %s"
            params.append("archived")
        sql += " ORDER BY w.priority DESC, w.created_at"
        cur.execute(sql, params)
        ids = [row[0] for row in cur.fetchall()]
    return [services.workspaces.get(workspace_id) for workspace_id in ids]


def register_workspace_routes(app: FastAPI) -> None:
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
    if not any(getattr(middleware, "cls", None) is SecurityMiddleware for middleware in app.user_middleware):
        rate_limit = int(os.getenv("COLAB_RATE_LIMIT_PER_MINUTE", "120"))
        app.add_middleware(SecurityMiddleware, rate_limiter=RateLimiter(limit=rate_limit))

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, str | None]:
        principal = current_principal(request)
        return {"user_id": principal.user_id, "role": principal.role.value, "email": principal.email, "session_id": principal.session_id}

    @app.post("/api/workspaces", response_model=Workspace, status_code=201, include_in_schema=False)
    def secure_create_workspace(payload: SecureWorkspaceCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> Workspace:
        return _secure_workspace_create(request, payload, idempotency_key)

    @app.get("/api/workspaces", response_model=list[Workspace], include_in_schema=False)
    def secure_list_workspaces(request: Request, include_archived: bool = False) -> list[Workspace]:
        return _secure_workspace_list(request, include_archived)

    routes = app.router.routes
    for endpoint in (secure_create_workspace, secure_list_workspaces):
        secure_route = next(route for route in routes if getattr(route, "endpoint", None) is endpoint)
        for route in list(routes):
            if route is secure_route:
                continue
            if getattr(route, "path", None) == "/api/workspaces" and getattr(route, "methods", set()) == getattr(secure_route, "methods", set()):
                routes.remove(route)
        routes.remove(secure_route)
        routes.insert(0, secure_route)
