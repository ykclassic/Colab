from uuid import uuid4

import pytest

from colab.agents import DeterministicAgent
from colab.collaboration import CollaborationEngine, CollaborationError, MessageType, TaskStatus
from colab.contracts import AgentRole, WorkflowState


def engine() -> CollaborationEngine:
    return CollaborationEngine({
        role: DeterministicAgent(role)
        for role in (AgentRole.RESEARCHER, AgentRole.STRATEGY, AgentRole.RISK)
    }, max_workers=3)


def state() -> WorkflowState:
    return WorkflowState(product_goal="build a reliable research platform")


def test_parallel_execution_runs_dependency_waves_and_preserves_results() -> None:
    e = engine()
    first = e.delegate(AgentRole.RESEARCHER, "research", "research", priority=200)
    second = e.delegate(AgentRole.STRATEGY, "design", "strategy", dependencies=(first.task_id,))
    third = e.delegate(AgentRole.RISK, "review", "risk")
    results = e.execute_parallel([first, second, third], state())
    assert [result.status for result in results] == [TaskStatus.SUCCEEDED] * 3
    assert results[0].task_id == first.task_id
    assert results[1].task_id in {second.task_id, third.task_id}


def test_delegation_rejects_unknown_agent() -> None:
    with pytest.raises(CollaborationError):
        engine().delegate(AgentRole.CEO, "arbitrate", "review")


def test_dependency_cycle_is_rejected() -> None:
    e = engine()
    a = e.delegate(AgentRole.RESEARCHER, "a", "research")
    b = e.delegate(AgentRole.STRATEGY, "b", "strategy", dependencies=(a.task_id,))
    a = a.model_copy(update={"dependencies": (b.task_id,)})
    with pytest.raises(CollaborationError, match="cycle"):
        e.execute_parallel([a, b], state())


def test_agent_to_agent_message_is_typed_and_auditable() -> None:
    e = engine()
    task_id = uuid4()
    message = e.send(AgentRole.RESEARCHER, AgentRole.RISK, task_id, "challenge the evidence",
                     MessageType.CHALLENGE)
    assert message.sender == AgentRole.RESEARCHER
    assert message.recipient == AgentRole.RISK
    assert e.messages() == (message,)


def test_conflict_arbitration_uses_explicit_scorer_and_confidence() -> None:
    e = engine()
    task_id = uuid4()
    conflict = e.detect_conflict(task_id, {
        AgentRole.RESEARCHER: "weak position",
        AgentRole.STRATEGY: "strong position",
    }, "agents disagree")
    decision = e.arbitrate(conflict, lambda role, _: 10.0 if role == AgentRole.STRATEGY else 2.0)
    assert decision.winner == AgentRole.STRATEGY
    assert decision.arbitrator == AgentRole.CEO
    assert decision.confidence > 0.8


def test_duplicate_task_ids_are_rejected() -> None:
    e = engine()
    task = e.delegate(AgentRole.RESEARCHER, "research", "research")
    duplicate = task.model_copy()
    with pytest.raises(CollaborationError, match="unique"):
        e.execute_parallel([task, duplicate], state())


def test_unknown_dependency_is_rejected() -> None:
    e = engine()
    task = e.delegate(AgentRole.RESEARCHER, "research", "research", dependencies=(uuid4(),))
    with pytest.raises(CollaborationError, match="unknown"):
        e.execute_parallel([task], state())
