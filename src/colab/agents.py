"""Agent contracts. Concrete LLM adapters are intentionally kept behind this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .contracts import AgentRole, Artifact, WorkflowState


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
