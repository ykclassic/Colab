"""HTTP routes for workspace lifecycle management."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .productization import StrategySpec, Workspace

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
        return _services(request).workspaces.update(workspace_id, payload.version, name=payload.name, product_goal=payload.product_goal, priority=payload.priority, strategies=payload.strategies)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workspace_id}/archive", response_model=Workspace)
def archive_workspace(workspace_id: UUID, payload: WorkspaceVersion, request: Request) -> Workspace:
    try:
        return _services(request).workspaces.archive(workspace_id, payload.version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workspace_id}/restore", response_model=Workspace)
def restore_workspace(workspace_id: UUID, payload: WorkspaceVersion, request: Request) -> Workspace:
    try:
        return _services(request).workspaces.restore(workspace_id, payload.version)
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
    """Register lifecycle routes without coupling service composition to the router."""
    app.include_router(router)
