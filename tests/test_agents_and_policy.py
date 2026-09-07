import pytest

from colab.agents import DeterministicAgent
from colab.contracts import AgentRole, Decision, RiskAssessment, Stage, WorkflowState
from colab.policy import PolicyViolation, validate_agent_separation, validate_state_for_persistence


def test_deterministic_agent_is_bounded_and_typed() -> None:
    state = WorkflowState(product_goal="research")
    result = DeterministicAgent(AgentRole.RESEARCHER).run(state, "collect evidence")
    assert len(result.artifacts) == 1
    assert result.artifacts[0].producer == AgentRole.RESEARCHER
    assert result.artifacts[0].content["task"] == "collect evidence"


def test_persistence_rejects_post_risk_state_without_approval() -> None:
    state = WorkflowState(product_goal="test", current_stage=Stage.IMPLEMENTATION)
    with pytest.raises(PolicyViolation, match="Approved independent risk"):
        validate_state_for_persistence(state)


def test_persistence_accepts_approved_risk_state() -> None:
    state = WorkflowState(product_goal="test", current_stage=Stage.IMPLEMENTATION)
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    validate_state_for_persistence(state)


def test_strategy_author_cannot_be_risk_assessor() -> None:
    with pytest.raises(PolicyViolation):
        validate_agent_separation(AgentRole.STRATEGY, AgentRole.STRATEGY)


def test_strategy_author_can_be_reviewed_by_risk_officer() -> None:
    validate_agent_separation(AgentRole.STRATEGY, AgentRole.RISK)
