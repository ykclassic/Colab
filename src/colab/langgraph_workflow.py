"""LangGraph orchestration with durable checkpointing and human approval interrupts."""

from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .contracts import Decision, Stage, WorkflowState
from .orchestrator import Orchestrator, WorkflowError


class GraphState(TypedDict):
    """JSON-safe graph state; canonical domain state remains WorkflowState."""

    workflow: dict[str, Any]


def _decode(payload: dict[str, Any]) -> WorkflowState:
    return WorkflowState.model_validate(payload)


def _encode(state: WorkflowState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _advance(state: GraphState) -> GraphState:
    workflow = _decode(state["workflow"])
    Orchestrator().advance(workflow)
    return {"workflow": _encode(workflow)}


def _approval_gate(state: GraphState) -> GraphState:
    workflow = _decode(state["workflow"])
    if workflow.current_stage != Stage.HUMAN_REVIEW:
        raise WorkflowError("approval gate entered outside human review")
    response = interrupt(
        {
            "type": "human_approval_required",
            "workflow_id": str(workflow.workflow_id),
            "message": "Approve or reject the final package.",
        }
    )
    decision = response.get("decision") if isinstance(response, dict) else response
    if decision not in {Decision.APPROVE.value, Decision.REJECT.value}:
        raise WorkflowError("human approval must be approve or reject")
    workflow.approvals.append({"decision": decision, "actor": "human"})
    if decision == Decision.REJECT.value:
        workflow.current_stage = Stage.REJECTED
        workflow.record("human_review_rejected", "human", "Final package rejected")
    else:
        Orchestrator().advance(workflow)
    return {"workflow": _encode(workflow)}


def _route_after_advance(state: GraphState) -> str:
    stage = state["workflow"]["current_stage"]
    if stage == Stage.HUMAN_REVIEW.value:
        return "human_approval"
    if stage in {Stage.COMPLETE.value, Stage.REJECTED.value}:
        return END
    return "advance"


def build_workflow_graph(checkpointer: Any | None = None) -> Any:
    """Build the production workflow graph with a pluggable checkpointer."""
    builder = StateGraph(GraphState)
    builder.add_node("advance", _advance)
    builder.add_node("human_approval", _approval_gate)
    builder.add_edge(START, "advance")
    builder.add_conditional_edges(
        "advance",
        _route_after_advance,
        {"human_approval": "human_approval", "advance": "advance", END: END},
    )
    builder.add_edge("human_approval", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def create_postgres_checkpointer(dsn: str) -> Any:
    """Create a production PostgresSaver and initialize its checkpoint tables."""
    if not dsn.strip():
        raise ValueError("dsn must not be empty")
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    from langgraph.checkpoint.postgres import PostgresSaver

    checkpointer = PostgresSaver.from_conn_string(dsn)
    checkpointer.setup()
    return checkpointer


def invoke_workflow(graph: Any, state: WorkflowState, thread_id: str) -> dict[str, Any]:
    """Start a workflow using a stable LangGraph thread identifier."""
    if not thread_id or len(thread_id) > 255:
        raise ValueError("thread_id must be between 1 and 255 characters")
    return graph.invoke(
        {"workflow": _encode(state)},
        {"configurable": {"thread_id": thread_id}},
    )


def recover_workflow(graph: Any, thread_id: str) -> WorkflowState:
    """Recover the latest checkpointed canonical workflow state."""
    if not thread_id or len(thread_id) > 255:
        raise ValueError("thread_id must be between 1 and 255 characters")
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    if not snapshot.values:
        raise WorkflowError("no checkpoint exists for workflow thread")
    return _decode(snapshot.values["workflow"])


def resume_with_human_decision(graph: Any, thread_id: str, decision: Decision) -> dict[str, Any]:
    """Resume an interrupted workflow with an explicit human decision."""
    if decision not in {Decision.APPROVE, Decision.REJECT}:
        raise ValueError("human decision must be approve or reject")
    return graph.invoke(
        Command(resume={"decision": decision.value}),
        {"configurable": {"thread_id": thread_id}},
    )
