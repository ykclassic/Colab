"""LangGraph adapter for the canonical Colab workflow state machine.

The graph is intentionally thin: ``WorkflowState`` remains the source of truth and
``Orchestrator`` remains the authority for safety-critical stage transitions. The
LangGraph layer supplies durable graph execution, resumability, and a human-review
interrupt without moving policy decisions into an LLM.
"""

from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .contracts import Decision, Stage, WorkflowState
from .orchestrator import Orchestrator, WorkflowError


class WorkflowGraphState(TypedDict):
    """State carried by the LangGraph execution layer."""

    workflow: WorkflowState


class WorkflowGraph:
    """Compile the canonical workflow as an explicit LangGraph state machine."""

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
    def _complete(state: WorkflowGraphState) -> WorkflowGraphState:
        workflow = state["workflow"]
        workflow.current_stage = Stage.COMPLETE
        workflow.record("workflow_completed", "orchestrator", "human approval accepted")
        return {"workflow": workflow}

    @staticmethod
    def _reject(state: WorkflowGraphState) -> WorkflowGraphState:
        workflow = state["workflow"]
        workflow.current_stage = Stage.REJECTED
        workflow.record("workflow_rejected", "human", "human approval rejected")
        return {"workflow": workflow}

    @staticmethod
    def _route_after_human_review(state: WorkflowGraphState) -> str:
        workflow = state["workflow"]
        return (
            "complete"
            if workflow.approvals[-1]["decision"] == Decision.APPROVE.value
            else "rejected"
        )

    def compile(self, *, checkpointer: object | None = None):
        """Compile the graph; pass a durable checkpointer for production execution."""
        builder = StateGraph(WorkflowGraphState)
        nodes: dict[str, Callable[[WorkflowGraphState], WorkflowGraphState]] = {}
        for stage in (
            Stage.INTAKE,
            Stage.DECOMPOSITION,
            Stage.RESEARCH,
            Stage.STRATEGY,
            Stage.RISK,
            Stage.IMPLEMENTATION,
            Stage.VALIDATION,
            Stage.SYNTHESIS,
        ):
            name = stage.value
            nodes[name] = self._advance
            builder.add_node(name, self._advance)

        builder.add_node(Stage.HUMAN_REVIEW.value, self._human_review)
        builder.add_node(Stage.COMPLETE.value, self._complete)
        builder.add_node(Stage.REJECTED.value, self._reject)
        builder.add_edge(START, Stage.INTAKE.value)

        ordered = [
            Stage.INTAKE,
            Stage.DECOMPOSITION,
            Stage.RESEARCH,
            Stage.STRATEGY,
            Stage.RISK,
            Stage.IMPLEMENTATION,
            Stage.VALIDATION,
            Stage.SYNTHESIS,
        ]
        for current, following in zip(ordered, ordered[1:]):
            builder.add_edge(current.value, following.value)
        builder.add_edge(Stage.SYNTHESIS.value, Stage.HUMAN_REVIEW.value)
        builder.add_conditional_edges(
            Stage.HUMAN_REVIEW.value,
            self._route_after_human_review,
            {"complete": Stage.COMPLETE.value, "rejected": Stage.REJECTED.value},
        )
        builder.add_edge(Stage.COMPLETE.value, END)
        builder.add_edge(Stage.REJECTED.value, END)
        if checkpointer is None:
            return builder.compile()
        return builder.compile(checkpointer=checkpointer)
