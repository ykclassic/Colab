"""HTTP routes for production validation and durable release governance."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .durable_governance import DurableGovernance
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


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    workflow_id: str = Field(default="", max_length=100)
    artifact_id: str = Field(default="", max_length=100)
    strategy_version_id: UUID
    artifact_digest: str = Field(min_length=1)
    risk_assessment_id: str = Field(default="", max_length=100)
    risk_assessment_digest: str = Field(min_length=1)
    required_reviewers: int = Field(default=1, ge=1, le=20)


class ApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(approve|reject)$")
    rationale: str = Field(min_length=1, max_length=10000)


def register_release_governance_routes(app: FastAPI) -> None:
    database = getattr(getattr(app.state, "services", None), "database", None)
    governance: DurableGovernance | ReleaseGovernance
    if database is not None:
        governance = DurableGovernance(database._connection_factory)
    else:
        governance = ReleaseGovernance()
    app.state.release_governance = governance

    @app.post("/api/governance/versions", response_model=StrategyVersion, status_code=201)
    def register_version(payload: VersionCreate, request: Request) -> StrategyVersion:
        require_workspace_membership(request, payload.workspace_id, Permission.STRATEGY_WRITE)
        try:
            return governance.register_version(StrategyVersion(**payload.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/governance/versions", response_model=list[StrategyVersion])
    def list_versions(request: Request, workspace_id: UUID) -> list[StrategyVersion]:
        require_workspace_membership(request, workspace_id, Permission.WORKSPACE_READ)
        return list(governance.versions(workspace_id))

    @app.post("/api/governance/versions/{version_id}/promote")
    def promote(version_id: UUID, payload: PromotionInput, request: Request) -> dict[str, Any]:
        require_workspace_membership(request, payload.workspace_id, Permission.APPROVE)
        try:
            version = governance.get_version(version_id)
            if version.workspace_id != payload.workspace_id:
                raise HTTPException(status_code=404, detail="strategy version not found")
            gates = tuple(GateResult(**gate.model_dump()) for gate in payload.gates)
            decision = governance.promote(version_id, payload.from_stage, payload.to_stage, gates)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return decision.model_dump(mode="json")

    @app.get("/api/governance/decisions")
    def decisions(request: Request, workspace_id: UUID) -> list[dict[str, Any]]:
        require_workspace_membership(request, workspace_id, Permission.AUDIT_READ)
        return [decision.model_dump(mode="json") for decision in governance.decisions(workspace_id)]

    @app.post("/api/governance/approvals", status_code=201)
    def request_approval(payload: ApprovalInput, request: Request) -> dict[str, Any]:
        principal = require_workspace_membership(request, payload.workspace_id, Permission.APPROVE)
        if not isinstance(governance, DurableGovernance):
            raise HTTPException(status_code=503, detail="durable governance requires a configured database")
        try:
            version = governance.get_version(payload.strategy_version_id)
            if version.workspace_id != payload.workspace_id:
                raise HTTPException(status_code=404, detail="strategy version not found")
            if version.artifact_digest != payload.artifact_digest:
                raise HTTPException(status_code=409, detail="artifact digest does not match governed strategy version")
            record = governance.request_approval(
                payload.workspace_id, payload.workflow_id, payload.artifact_id, payload.strategy_version_id,
                payload.artifact_digest, payload.risk_assessment_id, payload.risk_assessment_digest,
                payload.required_reviewers, principal,
            )
            return record.__dict__
        except HTTPException:
            raise
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/governance/approvals/{approval_id}/decision")
    def decide_approval(approval_id: UUID, payload: ApprovalDecisionInput, request: Request) -> dict[str, Any]:
        if not isinstance(governance, DurableGovernance):
            raise HTTPException(status_code=503, detail="durable governance requires a configured database")
        workspace_id = _approval_workspace(governance, approval_id)
        principal = require_workspace_membership(request, workspace_id, Permission.APPROVE)
        try:
            record = governance.decide_approval(approval_id, principal, payload.decision, payload.rationale)
            return record.__dict__
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval not found") from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/governance/approvals")
    def approvals(request: Request, workspace_id: UUID) -> list[dict[str, Any]]:
        require_workspace_membership(request, workspace_id, Permission.AUDIT_READ)
        if not isinstance(governance, DurableGovernance):
            raise HTTPException(status_code=503, detail="durable governance requires a configured database")
        return [record.__dict__ for record in governance.approvals(workspace_id)]


def _approval_workspace(governance: DurableGovernance, approval_id: UUID) -> UUID:
    with governance._connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT workspace_id FROM public.governance_approvals WHERE approval_id=%s", (approval_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return UUID(str(row[0]))
