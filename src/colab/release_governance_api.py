"""HTTP routes for production validation and release governance."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .release_governance import GateResult, ReleaseGovernance, StrategyVersion


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    from_stage: str = Field(min_length=1, max_length=50)
    to_stage: str = Field(min_length=1, max_length=50)
    gates: list[GateInput] = Field(min_length=1)


_GOVERNANCE = ReleaseGovernance()


def register_release_governance_routes(app: FastAPI) -> None:
    @app.post("/api/governance/versions", response_model=StrategyVersion, status_code=201)
    def register_version(payload: VersionCreate) -> StrategyVersion:
        try:
            return _GOVERNANCE.register_version(StrategyVersion(**payload.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/governance/versions", response_model=list[StrategyVersion])
    def list_versions() -> list[StrategyVersion]:
        return list(_GOVERNANCE.versions())

    @app.post("/api/governance/versions/{version_id}/promote")
    def promote(version_id: UUID, payload: PromotionInput) -> dict[str, Any]:
        gates = tuple(GateResult(**gate.model_dump()) for gate in payload.gates)
        try:
            decision = _GOVERNANCE.promote(version_id, payload.from_stage, payload.to_stage, gates)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return decision.model_dump(mode="json")

    @app.get("/api/governance/decisions")
    def decisions() -> list[dict[str, Any]]:
        return [decision.model_dump(mode="json") for decision in _GOVERNANCE.decisions()]
