"""HTTP routes for production validation and release governance."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .release_governance import GateResult, ReleaseGovernance, StrategyVersion
from .security import Permission, require_workspace_membership


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    artifact_digest: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gate: str = Field(min_length=1, max_length=100)
    passed: bool
    score: float = Field(ge=0, le=100)
    required: bool = True
    evidence: str = ""


class PromotionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    from_stage: str = Field(min_length=1, max_length=50)
    to_stage: str = Field(min_length=1, max_length=50)
    gates: list[GateInput] = Field(min_length=1)


_GOVERNANCE = ReleaseGovernance()


def register_release_governance_routes(app: FastAPI) -> None:
    @app.post("/api/governance/versions", response_model=StrategyVersion, status_code=201)
    def register_version(payload: VersionCreate, request: Request) -> StrategyVersion:
        require_workspace_membership(request, payload.workspace_id, Permission.STRATEGY_WRITE)
        try:
            return _GOVERNANCE.register_version(StrategyVersion(**payload.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/governance/versions", response_model=list[StrategyVersion])
    def list_versions(request: Request, workspace_id: UUID) -> list[StrategyVersion]:
        require_workspace_membership(request, workspace_id, Permission.WORKSPACE_READ)
        return list(_GOVERNANCE.versions(workspace_id))

    @app.post("/api/governance/versions/{version_id}/promote")
    def promote(version_id: UUID, payload: PromotionInput, request: Request) -> dict[str, Any]:
        require_workspace_membership(request, payload.workspace_id, Permission.APPROVE)
        try:
            version = _GOVERNANCE.get_version(version_id)
            if version.workspace_id != payload.workspace_id:
                raise HTTPException(status_code=404, detail="strategy version not found")
            gates = tuple(GateResult(**gate.model_dump()) for gate in payload.gates)
            decision = _GOVERNANCE.promote(version_id, payload.from_stage, payload.to_stage, gates)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return decision.model_dump(mode="json")

    @app.get("/api/governance/decisions")
    def decisions(request: Request, workspace_id: UUID) -> list[dict[str, Any]]:
        require_workspace_membership(request, workspace_id, Permission.AUDIT_READ)
        return [decision.model_dump(mode="json") for decision in _GOVERNANCE.decisions(workspace_id)]
