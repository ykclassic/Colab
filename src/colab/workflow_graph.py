"""LangGraph adapter for the canonical Colab workflow state machine.

The graph is intentionally thin: ``WorkflowState`` remains the source of truth and
``Orchestrator`` remains the authority for safety-critical stage transitions. The
LangGraph layer supplies durable graph execution, resumability, and a human-review
interrupt without moving policy decisions into an LLM.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .contracts import Decision, WorkflowState
from .orchestrator import Orchestrator, WorkflowError


class WorkflowGraphState(TypedDict):
    """State carried by the LangGraph execution layer."""

    workflow: WorkflowState


class WorkflowGraph:
    """Compile and run the deterministic workflow as a LangGraph graph.

    The graph advances one policy-controlled stage at a time. Human review is an
    explicit interrupt and therefore cannot be bypassed by a model response.
    """

    def __init__(self, orchestrator: Orchestrator | None = None) -> None:
        self._orchestrator = orchestrator or Orchestrator()

    def _advance(self, state: WorkflowGraphState) -> WorkflowGraphState:
        workflow = state["workflow"]
        self._orchestrator.advance(workflow)
        return {"workflow": workflow}

    @staticmethod
    def _human_review(state: WorkflowGraphState) -> WorkflowGraphState:
        workflow = state["workflow"]
        if not workflow.final_package:
            raise WorkflowError("Human review requires a final package")
        decision = interrupt(
            {
                "workflow_id": str(workflow.workflow_id),
                "stage": workflow.current_stage.value,
                "message": "Approve the final package to complete the workflow.",
            }
        )
        if not isinstance(decision, dict):
            raise WorkflowError("Human review response must be an object")
        value = decision.get("decision")
        if value not in {Decision.APPROVE.value, Decision.REJECT.value}:
            raise WorkflowError("Human review decision must be approve or reject")
        workflow.approvals.append({"decision": value, "source": "human"})
        workflow.record("human_approval", "human", value)
        return {"workflow": workflow}

    @staticmethod
    def _route_after_human_review(state: WorkflowGraphState) -> str:
        workflow = state["workflow"]
        if workflow.approvals[-1]["decision"] == Decision.APPROVE.value:
            return "complete"
        return "rejected"

    @staticmethod
    def _complete(state: WorkflowGraphState) -> WorkflowGraphState:
        workflow = state["workflow"]
        workflow.current_stage = workflow.current_stage.COMPLETE
        workflow.record("workflow_completed", "orchestrator", "human approval accepted")
        return {"workflow": workflow}

    @staticmethod
    def _reject(state: WorkflowGraphState) -> WorkflowGraphState:
        workflow = state["workflow"]
        workflow.current_stage = workflow.current_stage.REJECTED
        workflow.record("workflow_rejected", "human", "human approval rejected")
        return {"workflow": workflow}

    def compile(self, *, checkpointer: object | None = None):
        """Compile the graph; callers should supply a durable checkpointer in production."""
        builder = StateGraph(WorkflowGraphState)
        builder.add_node("advance", self._advance)
        builder.add_node("human_review", self._human_review)
        builder.add_node("complete", self._complete)
        builder.add_node("rejected", self._reject)
        builder.add_edge(START, "advance")
        builder.add_conditional_edges(
            "advance",
            lambda state: state["workflow"].current_stage.value,
            {
                "human_review": "human_review",
                "complete": "complete",
                "rejected": "rejected",
                "intake": "advance",
                "decomposition": "advance",
                "research": "advance",
                "strategy": "advance",
                "risk": "advance",
                "implementation": "advance",
                "validation": "advance",
                "synthesis": "advance",
            },
        )
        builder.add_conditional_edges(
            "human_review",
            self._route_after_human_review,
            {"complete": "complete", "rejected": "rejected"},
        )
        builder.add_edge("complete", END)
        builder.add_edge("rejected", END)
        if checkpointer is None:
            return builder.compile()
        return builder.compile(checkpointer=checkpointer)
