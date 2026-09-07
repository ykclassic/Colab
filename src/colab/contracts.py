"""Versioned, provider-neutral workflow contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Stage(StrEnum):
    INTAKE = "intake"
    DECOMPOSITION = "decomposition"
    RESEARCH = "research"
    STRATEGY = "strategy"
    RISK = "risk"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    SYNTHESIS = "synthesis"
    HUMAN_REVIEW = "human_review"
    COMPLETE = "complete"
    REJECTED = "rejected"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"
    PENDING = "pending"


class AgentRole(StrEnum):
    CEO = "ceo"
    RESEARCHER = "quant_researcher"
    STRATEGY = "strategy_developer"
    RISK = "risk_compliance"
    ENGINEER = "software_engineer_qa"


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID = Field(default_factory=uuid4)
    kind: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    producer: AgentRole
    content: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID = Field(default_factory=uuid4)
    role: AgentRole
    objective: str = Field(min_length=1)
    stage: Stage
    status: str = "pending"


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID = Field(default_factory=uuid4)
    decision: Decision
    findings: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    assessor: AgentRole = AgentRole.RISK


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    stage: Stage
    actor: AgentRole | str
    message: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowState(BaseModel):
    """Canonical workflow state; mutations should occur through orchestration methods."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    workflow_id: UUID = Field(default_factory=uuid4)
    schema_version: str = "1.0"
    product_goal: str = Field(min_length=1)
    product_brief: dict[str, Any] = Field(default_factory=dict)
    roadmap: list[str] = Field(default_factory=list)
    current_stage: Stage = Stage.INTAKE
    agent_tasks: list[AgentTask] = Field(default_factory=list)
    research_artifacts: list[Artifact] = Field(default_factory=list)
    strategy_candidates: list[Artifact] = Field(default_factory=list)
    risk_assessments: list[RiskAssessment] = Field(default_factory=list)
    implementation_artifacts: list[Artifact] = Field(default_factory=list)
    validation_results: list[Artifact] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
    iteration_count: int = Field(default=0, ge=0)
    budgets: dict[str, int | float] = Field(default_factory=dict)
    final_package: dict[str, Any] | None = None

    def record(self, event_type: str, actor: AgentRole | str, message: str) -> None:
        self.audit_events.append(
            AuditEvent(event_type=event_type, stage=self.current_stage, actor=actor, message=message)
        )
