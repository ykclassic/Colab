"""Phase 21F end-to-end tests."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from colab.agent_platform import AgentRecord, ArbitrationCandidate, EvaluationCase, EvaluationResult, EvidenceItem, MemoryRecord, CostRecord
from colab.agent_platform_vertical_slice import InMemoryAgentPlatformStore, run_agent_vertical_slice, version_transition_allowed


def make_agent(workspace_id, version=1, revision="rev-a"):
    return AgentRecord(workspace_id=workspace_id, name="researcher", version=version, role="research", code_revision=revision, model="test-model")


def test_agent_vertical_slice_registration_to_governance() -> None:
    workspace = uuid4()
    agent = make_agent(workspace)
    case = EvaluationCase(workspace_id=workspace, task="find evidence")
    result = EvaluationResult(case_id=case.case_id, agent_id=agent.agent_id, workspace_id=workspace, score=.92, correctness=.95, evidence_quality=.9, latency_ms=120, tokens_in=100, tokens_out=50, cost_usd=.02, passed=True, rationale="supported")
    memory = MemoryRecord(workspace_id=workspace, agent_id=agent.agent_id, key="source preference", value="primary evidence", source="evaluation", confidence=.9)
    cost = CostRecord(workspace_id=workspace, agent_id=agent.agent_id, model=agent.model, tokens_in=100, tokens_out=50, cost_usd=.02, latency_ms=120)
    candidate = ArbitrationCandidate(agent_id=agent.agent_id, answer="supported", confidence=.9, evidence=[EvidenceItem(source_id="source-1", claim="claim", strength=.95)])
    store = InMemoryAgentPlatformStore()
    run = run_agent_vertical_slice(workspace_id=workspace, agent=agent, cases=[case], results=[result], arbitration_candidates=[candidate], memories=[memory], costs=[cost], store=store)
    assert run.governance.approved
    assert run.benchmark.pass_rate == 1
    assert run.arbitration.winner_agent_id == agent.agent_id
    assert run.memories[0].key == "source preference"
    assert run.costs.total_cost_usd == .02
    assert len(run.evaluation_hashes[0]) == 64


def test_regression_blocks_governance() -> None:
    workspace = uuid4()
    agent = make_agent(workspace)
    case = EvaluationCase(workspace_id=workspace, task="benchmark")
    result = EvaluationResult(case_id=case.case_id, agent_id=agent.agent_id, workspace_id=workspace, score=.7, correctness=.7, evidence_quality=.8, latency_ms=100, passed=True, rationale="partial")
    candidate = ArbitrationCandidate(agent_id=agent.agent_id, answer="answer", confidence=.8, evidence=[EvidenceItem(source_id="s", claim="c", strength=.8)])
    run = run_agent_vertical_slice(workspace_id=workspace, agent=agent, cases=[case], results=[result], arbitration_candidates=[candidate], memories=[], costs=[], store=InMemoryAgentPlatformStore(), baseline_score=.9)
    assert run.benchmark.regression
    assert not run.governance.approved


def test_memory_lifecycle_expiry_and_workspace_isolation() -> None:
    workspace = uuid4()
    other = uuid4()
    now = datetime.now(UTC)
    memories = [
        MemoryRecord(workspace_id=workspace, key="live", value="usable", source="test", expires_at=now + timedelta(hours=1)),
        MemoryRecord(workspace_id=workspace, key="expired", value="ignore", source="test", expires_at=now - timedelta(seconds=1)),
        MemoryRecord(workspace_id=other, key="foreign", value="do not leak", source="test"),
    ]
    from colab.agent_platform import retrieve_memory
    found = retrieve_memory(memories, workspace, "live")
    assert [m.key for m in found] == ["live"]


def test_agent_version_governance_requires_sequential_revision() -> None:
    workspace = uuid4()
    v1 = make_agent(workspace, 1, "rev-a")
    v2 = make_agent(workspace, 2, "rev-b")
    gap = make_agent(workspace, 4, "rev-c")
    assert version_transition_allowed(v1, v2)
    assert not version_transition_allowed(v1, gap)
    assert not version_transition_allowed(v1, make_agent(uuid4(), 2, "rev-b"))
