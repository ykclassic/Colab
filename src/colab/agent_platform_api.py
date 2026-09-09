"""Phase 19 Agent Platform API."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .agent_platform import (
    AgentRecord,
    ArbitrationCandidate,
    CostRecord,
    EvaluationResult,
    InMemoryAgentRegistry,
    MemoryRecord,
    arbitrate,
    evaluate_results,
    historical_performance,
    retrieve_memory,
    summarize_costs,
)
from .security import Permission, require_workspace_membership

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    name: str
    version: int = Field(default=1, ge=1)
    role: str
    code_revision: str
    model: str
    tools: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class EvaluationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    results: list[EvaluationResult]
    agent_id: UUID


class ArbitrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    candidates: list[ArbitrationCandidate] = Field(min_length=1)
    minimum_evidence: float = Field(default=.5, ge=0, le=1)


class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    memories: list[MemoryRecord] = Field(default_factory=list)
    query: str = Field(min_length=1)
    agent_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=100)


class CostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    records: list[CostRecord]
    agent_id: UUID


def register_agent_routes(app: Any) -> None:
    registry = InMemoryAgentRegistry()
    app.state.agent_registry = registry
    app.include_router(router)

    @app.post("/api/agents/registry", response_model=AgentRecord, status_code=201)  # type: ignore[untyped-decorator]
    def register_agent(payload: AgentCreate, request: Request) -> AgentRecord:
        require_workspace_membership(request, payload.workspace_id, Permission.WORKSPACE_WRITE)
        return registry.register(AgentRecord(**payload.model_dump()))

    @app.get("/api/agents/registry/{workspace_id}", response_model=list[AgentRecord])  # type: ignore[untyped-decorator]
    def list_agents(workspace_id: UUID, request: Request) -> list[AgentRecord]:
        require_workspace_membership(request, workspace_id, Permission.WORKSPACE_READ)
        return registry.list(workspace_id)

    @app.post("/api/agents/evaluate", response_model=dict[str, Any])  # type: ignore[untyped-decorator]
    def evaluate(payload: EvaluationQuery, request: Request) -> dict[str, Any]:
        require_workspace_membership(request, payload.workspace_id, Permission.VALIDATE)
        summary = evaluate_results(payload.results, payload.agent_id)
        history = historical_performance(payload.results, payload.agent_id)
        return {"summary": summary, "historical_performance": history}

    @app.post("/api/agents/arbitrate", response_model=dict[str, Any])  # type: ignore[untyped-decorator]
    def arbitration(payload: ArbitrationRequest, request: Request) -> dict[str, Any]:
        require_workspace_membership(request, payload.workspace_id, Permission.RESEARCH_WRITE)
        return arbitrate(payload.candidates, payload.minimum_evidence).model_dump(mode="json")

    @app.post("/api/agents/memory/search", response_model=list[MemoryRecord])  # type: ignore[untyped-decorator]
    def memory_search(payload: MemoryRequest, request: Request) -> list[MemoryRecord]:
        require_workspace_membership(request, payload.workspace_id, Permission.WORKSPACE_READ)
        return retrieve_memory(payload.memories, payload.workspace_id, payload.query, payload.agent_id, payload.limit)

    @app.post("/api/agents/costs", response_model=dict[str, Any])  # type: ignore[untyped-decorator]
    def costs(payload: CostRequest, request: Request) -> dict[str, Any]:
        require_workspace_membership(request, payload.workspace_id, Permission.AUDIT_READ)
        return summarize_costs(payload.records, payload.agent_id).model_dump(mode="json")
