"""Agent contracts and bounded model-backed adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contracts import AgentRole, Artifact, WorkflowState
from .llm_runtime import ModelPolicy, ModelRequest, ModelRuntime


@dataclass(frozen=True)
class AgentResult:
    artifacts: tuple[Artifact, ...] = ()
    notes: tuple[str, ...] = ()


class Agent(ABC):
    role: AgentRole

    @abstractmethod
    def run(self, state: WorkflowState, task: str) -> AgentResult:
        """Execute one bounded task against a snapshot of workflow state."""
        raise NotImplementedError


class DeterministicAgent(Agent):
    """Reference agent used for orchestration tests and local development."""

    def __init__(self, role: AgentRole) -> None:
        self.role = role

    def run(self, state: WorkflowState, task: str) -> AgentResult:
        artifact = Artifact(
            kind="agent_output",
            producer=self.role,
            content={"task": task, "workflow_id": str(state.workflow_id)},
        )
        return AgentResult(artifacts=(artifact,), notes=("deterministic adapter",))


class AgentModelOutput(BaseModel):
    """Strict envelope required from a model-backed agent."""

    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]
    notes: list[str] = Field(default_factory=list, max_length=20)


class ModelBackedAgent(Agent):
    """Agent adapter that can only emit a validated artifact envelope."""

    def __init__(self, role: AgentRole, runtime: ModelRuntime, policy: ModelPolicy) -> None:
        self.role = role
        self._runtime = runtime
        self._policy = policy

    def run(self, state: WorkflowState, task: str) -> AgentResult:
        request = ModelRequest(
            system=(
                "You are a bounded collaboration-platform agent. Return ONLY JSON matching "
                "the required schema. Do not claim to have performed external actions."
            ),
            prompt=(
                f"Workflow: {state.workflow_id}\n"
                f"Role: {self.role.value}\n"
                f"Task: {task}\n"
                "Required JSON schema: {\"content\": object, \"notes\": [string]}"
            ),
            temperature=0.0,
        )
        output = self._runtime.structured(request, self._policy, AgentModelOutput)
        artifact = Artifact(
            kind="agent_output",
            producer=self.role,
            content=output.content,
        )
        return AgentResult(artifacts=(artifact,), notes=tuple(output.notes))
