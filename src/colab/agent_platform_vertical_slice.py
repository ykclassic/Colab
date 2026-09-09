"""Phase 21F durable agent-platform vertical slice.

The orchestration here deliberately keeps agents advisory: governance records the
version/evaluation evidence required before an agent can be promoted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from .agent_platform import (
    AgentPlatformError,
    AgentRecord,
    ArbitrationCandidate,
    ArbitrationDecision,
    CostRecord,
    EvaluationCase,
    EvaluationResult,
    MemoryRecord,
    arbitrate,
    evaluation_hash,
    historical_performance,
    summarize_costs,
)


@dataclass(frozen=True)
class AgentBenchmark:
    agent_id: UUID
    version: int
    evaluation_ids: tuple[UUID, ...]
    score: float
    pass_rate: float
    evidence_quality: float
    regression: bool
    baseline_score: float | None
    benchmark_hash: str


@dataclass(frozen=True)
class AgentGovernanceDecision:
    agent_id: UUID
    version: int
    approved: bool
    reason: str
    benchmark_hash: str
    decided_at: datetime


@dataclass(frozen=True)
class AgentPlatformRun:
    agent: AgentRecord
    benchmark: AgentBenchmark
    performance: Any
    arbitration: ArbitrationDecision
    memories: tuple[MemoryRecord, ...]
    costs: Any
    governance: AgentGovernanceDecision
    evaluation_hashes: tuple[str, ...]


class InMemoryAgentPlatformStore:
    """Durable-shaped repository for unit/E2E verification."""

    def __init__(self) -> None:
        self.agents: dict[UUID, AgentRecord] = {}
        self.evaluations: list[EvaluationResult] = []
        self.memories: list[MemoryRecord] = []
        self.costs: list[CostRecord] = []
        self.governance: list[AgentGovernanceDecision] = []
        self.benchmarks: list[AgentBenchmark] = []

    def save_agent(self, agent: AgentRecord) -> AgentRecord:
        self.agents[agent.agent_id] = agent
        return agent

    def save_evaluations(self, results: list[EvaluationResult]) -> None:
        self.evaluations.extend(results)

    def save_memory(self, memory: MemoryRecord) -> MemoryRecord:
        self.memories.append(memory)
        return memory

    def save_cost(self, record: CostRecord) -> CostRecord:
        self.costs.append(record)
        return record

    def save_benchmark(self, benchmark: AgentBenchmark) -> AgentBenchmark:
        self.benchmarks.append(benchmark)
        return benchmark

    def save_governance(self, decision: AgentGovernanceDecision) -> AgentGovernanceDecision:
        self.governance.append(decision)
        return decision

    def get_agent(self, agent_id: UUID, workspace_id: UUID) -> AgentRecord:
        agent = self.agents.get(agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            raise KeyError(str(agent_id))
        return agent


def run_agent_vertical_slice(*, workspace_id: UUID, agent: AgentRecord, cases: list[EvaluationCase], results: list[EvaluationResult], arbitration_candidates: list[ArbitrationCandidate], memories: list[MemoryRecord], costs: list[CostRecord], store: InMemoryAgentPlatformStore, baseline_score: float | None = None, regression_threshold: float = 0.05, minimum_pass_rate: float = 0.8, minimum_evidence_quality: float = 0.6) -> AgentPlatformRun:
    if agent.workspace_id != workspace_id:
        raise AgentPlatformError("agent is outside workspace")
    if not cases:
        raise AgentPlatformError("benchmark requires evaluation cases")
    case_ids = {case.case_id for case in cases if case.workspace_id == workspace_id}
    scoped_results = [x for x in results if x.workspace_id == workspace_id and x.agent_id == agent.agent_id and x.case_id in case_ids]
    if len(scoped_results) != len(cases):
        raise AgentPlatformError("benchmark requires exactly one result per case")
    if len({x.case_id for x in scoped_results}) != len(scoped_results):
        raise AgentPlatformError("duplicate evaluation results are not allowed")
    store.save_agent(agent)
    store.save_evaluations(scoped_results)
    summary = historical_performance(scoped_results, agent.agent_id)
    evidence_quality = sum(x.evidence_quality for x in scoped_results) / len(scoped_results)
    regression = baseline_score is not None and summary.mean_score < baseline_score - regression_threshold
    benchmark_manifest = {"agent": {"id": str(agent.agent_id), "version": agent.version, "revision": agent.code_revision, "model": agent.model}, "cases": [str(x.case_id) for x in cases], "evaluations": [evaluation_hash(x) for x in scoped_results], "thresholds": {"regression": regression_threshold, "pass_rate": minimum_pass_rate, "evidence": minimum_evidence_quality}}
    benchmark_hash = sha256(repr(sorted(benchmark_manifest.items())).encode()).hexdigest()
    benchmark = AgentBenchmark(agent_id=agent.agent_id, version=agent.version, evaluation_ids=tuple(x.result_id for x in scoped_results), score=summary.mean_score, pass_rate=summary.pass_rate, evidence_quality=evidence_quality, regression=regression, baseline_score=baseline_score, benchmark_hash=benchmark_hash)
    store.save_benchmark(benchmark)
    scoped_memories = tuple(m for m in memories if m.workspace_id == workspace_id and (m.agent_id is None or m.agent_id == agent.agent_id))
    for memory in scoped_memories:
        store.save_memory(memory)
    scoped_costs = [x for x in costs if x.workspace_id == workspace_id and x.agent_id == agent.agent_id]
    for cost in scoped_costs:
        store.save_cost(cost)
    cost_summary = summarize_costs(scoped_costs, agent.agent_id) if scoped_costs else None
    decision = arbitrate(arbitration_candidates)
    approved = not regression and benchmark.pass_rate >= minimum_pass_rate and benchmark.evidence_quality >= minimum_evidence_quality
    governance = AgentGovernanceDecision(agent_id=agent.agent_id, version=agent.version, approved=approved, reason=("benchmark passed and no regression detected" if approved else "promotion blocked by benchmark, evidence, or regression gate"), benchmark_hash=benchmark_hash, decided_at=datetime.now(UTC))
    store.save_governance(governance)
    return AgentPlatformRun(agent=agent, benchmark=benchmark, performance=summary, arbitration=decision, memories=scoped_memories, costs=cost_summary, governance=governance, evaluation_hashes=tuple(evaluation_hash(x) for x in scoped_results))


def version_transition_allowed(previous: AgentRecord | None, candidate: AgentRecord) -> bool:
    if previous is None:
        return candidate.version == 1
    return previous.workspace_id == candidate.workspace_id and previous.name == candidate.name and candidate.version == previous.version + 1 and candidate.code_revision != previous.code_revision
