import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from colab.contracts import Decision, RiskAssessment, Stage, WorkflowState
from colab.workflow_graph import WorkflowGraph, WorkflowGraphState


def _approved_state() -> WorkflowState:
    state = WorkflowState(product_goal="research")
    state.risk_assessments.append(
        RiskAssessment(decision=Decision.APPROVE, findings=["bounded"], controls=["human review"])
    )
    state.final_package = {"summary": "validated"}
    return state


def test_graph_reaches_human_review_and_resumes_to_complete() -> None:
    graph = WorkflowGraph().compile(checkpointer=InMemorySaver())
    state = _approved_state()
    config = {"configurable": {"thread_id": str(state.workflow_id)}}

    paused = graph.invoke(WorkflowGraphState(workflow=state), config)
    assert paused["workflow"].current_stage is Stage.HUMAN_REVIEW
    assert "__interrupt__" in paused
    assert paused["__interrupt__"]

    completed = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert completed["workflow"].current_stage is Stage.COMPLETE
    assert completed["workflow"].approvals[-1]["decision"] == Decision.APPROVE.value


def test_graph_preserves_risk_rejection() -> None:
    graph = WorkflowGraph().compile()
    state = WorkflowState(product_goal="research")
    state.risk_assessments.append(RiskAssessment(decision=Decision.REJECT))

    result = graph.invoke(WorkflowGraphState(workflow=state))
    assert result["workflow"].current_stage is Stage.REJECTED
    assert any(event.event_type == "risk_gate_blocked" for event in result["workflow"].audit_events)


def test_graph_requires_final_package_before_human_review() -> None:
    graph = WorkflowGraph().compile()
    state = WorkflowState(product_goal="research")
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    state.current_stage = Stage.SYNTHESIS

    with pytest.raises(Exception):
        graph.invoke(WorkflowGraphState(workflow=state))
