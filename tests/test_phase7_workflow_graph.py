from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from colab.contracts import Decision, RiskAssessment, Stage, WorkflowState
from colab.orchestrator import WorkflowError
from colab.workflow_graph import WorkflowGraph, WorkflowGraphState


def _approved_state() -> WorkflowState:
    state = WorkflowState(product_goal="research")
    state.risk_assessments.append(
        RiskAssessment(
            decision=Decision.APPROVE,
            findings=["bounded"],
            controls=["human review"],
        )
    )
    state.final_package = {"summary": "validated"}
    return state


def _workflow(result: WorkflowGraphState) -> WorkflowState:
    return WorkflowState.model_validate(result["workflow"])


def test_graph_reaches_human_review_and_resumes_to_complete() -> None:
    graph = WorkflowGraph().compile(checkpointer=InMemorySaver())
    state = _approved_state()
    config = {"configurable": {"thread_id": str(state.workflow_id)}}

    paused = graph.invoke(WorkflowGraphState(workflow=state), config)
    assert _workflow(paused).current_stage is Stage.HUMAN_REVIEW
    assert "__interrupt__" in paused
    assert paused["__interrupt__"]

    completed = graph.invoke(Command(resume={"decision": "approve"}), config)
    final_state = _workflow(completed)
    assert final_state.current_stage is Stage.COMPLETE
    assert final_state.approvals[-1]["decision"] == Decision.APPROVE.value


def test_graph_preserves_risk_rejection() -> None:
    graph = WorkflowGraph().compile()
    state = WorkflowState(product_goal="research")
    state.risk_assessments.append(RiskAssessment(decision=Decision.REJECT))

    result = graph.invoke(WorkflowGraphState(workflow=state))
    workflow = _workflow(result)
    assert workflow.current_stage is Stage.REJECTED
    assert any(event.event_type == "risk_gate_blocked" for event in workflow.audit_events)


def test_graph_requires_final_package_before_human_review() -> None:
    graph = WorkflowGraph().compile()
    state = WorkflowState(product_goal="research")
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    state.current_stage = Stage.SYNTHESIS

    try:
        graph.invoke(WorkflowGraphState(workflow=state))
    except WorkflowError as exc:
        assert str(exc) == "Human review requires a final package"
    else:
        raise AssertionError("human review proceeded without a final package")
