"""Deterministic workflow state machine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from .contracts import AgentRole, Decision, Stage, WorkflowState


class WorkflowError(RuntimeError):
    """Raised when a workflow transition violates a safety invariant."""


@dataclass(frozen=True)
class Transition:
    source: Stage
    target: Stage
    guard: Callable[[WorkflowState], bool]


class Orchestrator:
    """Owns stage transitions and enforces the independent risk gate."""

    _linear: ClassVar[dict[Stage, Stage]] = {
        Stage.INTAKE: Stage.DECOMPOSITION,
        Stage.DECOMPOSITION: Stage.RESEARCH,
        Stage.RESEARCH: Stage.STRATEGY,
        Stage.STRATEGY: Stage.RISK,
        Stage.IMPLEMENTATION: Stage.VALIDATION,
        Stage.VALIDATION: Stage.SYNTHESIS,
        Stage.SYNTHESIS: Stage.HUMAN_REVIEW,
    }

    def advance(self, state: WorkflowState) -> WorkflowState:
        current = state.current_stage
        if current == Stage.RISK:
            if not state.risk_assessments:
                raise WorkflowError("Risk review is mandatory before implementation")
            assessment = state.risk_assessments[-1]
            if assessment.decision in {Decision.REJECT, Decision.REVISE}:
                state.record("risk_gate_blocked", AgentRole.RISK, assessment.decision.value)
                state.current_stage = Stage.REJECTED if assessment.decision == Decision.REJECT else Stage.STRATEGY
                if assessment.decision == Decision.REVISE:
                    state.iteration_count += 1
                return state
            if assessment.decision != Decision.APPROVE:
                raise WorkflowError("Risk gate must explicitly approve implementation")
            state.current_stage = Stage.IMPLEMENTATION
        elif current in self._linear:
            state.current_stage = self._linear[current]
        elif current == Stage.HUMAN_REVIEW:
            if not state.approvals:
                raise WorkflowError("Human approval is mandatory before completion")
            if state.approvals[-1].get("decision") != Decision.APPROVE:
                raise WorkflowError("Final package requires explicit human approval")
            state.current_stage = Stage.COMPLETE
        else:
            raise WorkflowError(f"No forward transition is defined from {current.value}")
        state.record("stage_advanced", "orchestrator", f"{current.value} -> {state.current_stage.value}")
        return state
