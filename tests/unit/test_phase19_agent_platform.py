from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from colab.agent_platform import (
    AgentPlatformError,
    AgentRecord,
    ArbitrationCandidate,
    CostRecord,
    EvaluationResult,
    EvidenceItem,
    InMemoryAgentRegistry,
    MemoryRecord,
    arbitrate,
    evaluate_results,
    historical_performance,
    retrieve_memory,
    summarize_costs,
)


def test_registry_is_workspace_scoped_and_versions_increase() -> None:
    registry = InMemoryAgentRegistry()
    workspace = uuid4()
    agent = AgentRecord(workspace_id=workspace, name="researcher", role="research", code_revision="a", model="test")
    registry.register(agent)
    assert registry.list(workspace) == [agent]
    with pytest.raises(AgentPlatformError):
        registry.register(agent.model_copy(update={"agent_id": uuid4()}))
    assert registry.list(uuid4()) == []


def _results(agent_id, workspace_id):
    now = datetime.now(UTC)
    return [
        EvaluationResult(case_id=uuid4(), agent_id=agent_id, workspace_id=workspace_id, score=.9, correctness=.9, evidence_quality=.8, latency_ms=100, tokens_in=100, tokens_out=50, cost_usd=.01, passed=True, rationale="correct", created_at=now),
        EvaluationResult(case_id=uuid4(), agent_id=agent_id, workspace_id=workspace_id, score=.7, correctness=.7, evidence_quality=.6, latency_ms=200, tokens_in=100, tokens_out=50, cost_usd=.02, passed=False, rationale="miss", created_at=now + timedelta(seconds=1)),
    ]


def test_evaluation_and_history_are_deterministic() -> None:
    agent, workspace = uuid4(), uuid4()
    results = _results(agent, workspace)
    summary = evaluate_results(results, agent)
    history = historical_performance(results, agent)
    assert summary.cases == 2
    assert summary.pass_rate == .5
    assert summary.p95_latency_ms == 200
    assert history.observations == 2
    assert history.score_trend == 0


def test_evidence_based_arbitration_penalizes_weak_evidence() -> None:
    weak = ArbitrationCandidate(agent_id=uuid4(), answer="A", confidence=.99, evidence=[])
    strong = ArbitrationCandidate(agent_id=uuid4(), answer="B", confidence=.8, evidence=[EvidenceItem(source_id="source-1", claim="claim", strength=.95)])
    decision = arbitrate([weak, strong])
    assert decision.winner_agent_id == strong.agent_id
    assert decision.evidence_score == .95


def test_memory_is_workspace_scoped_and_expiry_aware() -> None:
    workspace, other = uuid4(), uuid4()
    memories = [
        MemoryRecord(workspace_id=workspace, key="alpha", value="important research", source="test", confidence=.9),
        MemoryRecord(workspace_id=workspace, key="expired", value="alpha", source="test", expires_at=datetime.now(UTC) - timedelta(minutes=1)),
        MemoryRecord(workspace_id=other, key="alpha", value="secret", source="test"),
    ]
    found = retrieve_memory(memories, workspace, "alpha")
    assert len(found) == 1
    assert found[0].key == "alpha"


def test_cost_summary() -> None:
    agent, workspace = uuid4(), uuid4()
    records = [CostRecord(workspace_id=workspace, agent_id=agent, model="test", tokens_in=100, tokens_out=50, cost_usd=.01, latency_ms=100), CostRecord(workspace_id=workspace, agent_id=agent, model="test", tokens_in=200, tokens_out=100, cost_usd=.02, latency_ms=200)]
    summary = summarize_costs(records, agent)
    assert summary.calls == 2
    assert summary.tokens_in == 300
    assert summary.total_cost_usd == .03
    assert summary.cost_per_1k_tokens == pytest.approx(.0666667)
