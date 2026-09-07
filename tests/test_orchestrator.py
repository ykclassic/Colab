from colab.contracts import Decision, RiskAssessment, Stage, WorkflowState
from colab.orchestrator import Orchestrator, WorkflowError


def test_happy_path_requires_risk_and_human_approval() -> None:
    state = WorkflowState(product_goal="Build a research strategy platform")
    orchestrator = Orchestrator()
    for expected in [Stage.DECOMPOSITION, Stage.RESEARCH, Stage.STRATEGY, Stage.RISK]:
        orchestrator.advance(state)
        assert state.current_stage == expected

    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    orchestrator.advance(state)
    assert state.current_stage == Stage.IMPLEMENTATION
    orchestrator.advance(state)
    orchestrator.advance(state)
    assert state.current_stage == Stage.SYNTHESIS
    orchestrator.advance(state)
    assert state.current_stage == Stage.HUMAN_REVIEW

    state.approvals.append({"decision": Decision.APPROVE, "actor": "human"})
    orchestrator.advance(state)
    assert state.current_stage == Stage.COMPLETE


def test_implementation_cannot_bypass_risk() -> None:
    state = WorkflowState(product_goal="test")
    state.current_stage = Stage.RISK
    with __import__("pytest").raises(WorkflowError):
        Orchestrator().advance(state)


def test_rejected_risk_stops_workflow() -> None:
    state = WorkflowState(product_goal="test", current_stage=Stage.RISK)
    state.risk_assessments.append(RiskAssessment(decision=Decision.REJECT, findings=["unsafe"]))
    Orchestrator().advance(state)
    assert state.current_stage == Stage.REJECTED


def test_revision_returns_to_strategy_and_increments_iteration() -> None:
    state = WorkflowState(product_goal="test", current_stage=Stage.RISK)
    state.risk_assessments.append(RiskAssessment(decision=Decision.REVISE))
    Orchestrator().advance(state)
    assert state.current_stage == Stage.STRATEGY
    assert state.iteration_count == 1
