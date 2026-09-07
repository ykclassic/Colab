"""Central safety and execution policies."""

from __future__ import annotations

from .contracts import AgentRole, Decision, Stage, WorkflowState


class PolicyViolation(ValueError):
    """Raised when a requested operation violates a platform invariant."""


def validate_state_for_persistence(state: WorkflowState) -> None:
    """Reject states that violate non-negotiable workflow boundaries."""
    if (
        state.current_stage in {
            Stage.IMPLEMENTATION,
            Stage.VALIDATION,
            Stage.SYNTHESIS,
            Stage.HUMAN_REVIEW,
            Stage.COMPLETE,
        }
        and (not state.risk_assessments or state.risk_assessments[-1].decision != Decision.APPROVE)
    ):
        raise PolicyViolation("Approved independent risk assessment is required")


def validate_agent_separation(actor: AgentRole, risk_assessor: AgentRole) -> None:
    """Require an independent Risk Officer for risk assessment."""
    if actor == AgentRole.RISK or risk_assessor != AgentRole.RISK:
        raise PolicyViolation("Risk assessment must be performed by the independent Risk Officer")
