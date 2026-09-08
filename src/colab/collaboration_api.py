"""HTTP endpoints for Phase 9 multi-agent collaboration."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .agents import DeterministicAgent
from .collaboration import CollaborationEngine, MessageType, TaskSpec
from .contracts import AgentRole, WorkflowState


class CollaborationTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: AgentRole
    objective: str = Field(min_length=1, max_length=10000)
    stage: str = Field(min_length=1, max_length=100)
    priority: int = Field(default=100, ge=0, le=1000)
    dependencies: tuple[UUID, ...] = ()
    budget: int = Field(default=1, ge=1, le=1000)


class CollaborationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_goal: str = Field(min_length=1, max_length=10000)
    tasks: list[CollaborationTaskCreate] = Field(min_length=1, max_length=100)


class CollaborationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: AgentRole
    recipient: AgentRole
    task_id: UUID
    content: str = Field(min_length=1, max_length=20000)
    message_type: MessageType = MessageType.REQUEST
    conversation_id: UUID | None = None


def register_collaboration_routes(app: Any) -> None:
    router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

    @router.post("/run")
    def run_collaboration(payload: CollaborationRunRequest) -> dict[str, Any]:
        roles = {task.role for task in payload.tasks}
        agents = {role: DeterministicAgent(role) for role in roles}
        engine = CollaborationEngine(agents, max_workers=min(8, len(roles)))
        tasks = [TaskSpec(**task.model_dump()) for task in payload.tasks]
        try:
            result = engine.collaborate(tasks, WorkflowState(product_goal=payload.product_goal))
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "results": [item.model_dump(mode="json") for item in result.results],
            "messages": [item.model_dump(mode="json") for item in result.messages],
            "decisions": [item.model_dump(mode="json") for item in result.decisions],
        }

    @router.post("/messages")
    def send_message(payload: CollaborationMessageRequest) -> dict[str, Any]:
        agents = {payload.sender: DeterministicAgent(payload.sender), payload.recipient: DeterministicAgent(payload.recipient)}
        engine = CollaborationEngine(agents)
        message = engine.send(**payload.model_dump())
        return message.model_dump(mode="json")

    app.include_router(router)
