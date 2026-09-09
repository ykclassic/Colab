"""Phase 21F: durable, evidence-weighted agent platform vertical slice."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4


class AgentGovernanceError(ValueError):
    pass


@dataclass(frozen=True)
class AgentVersion:
    agent_id: UUID
    version: int
    config_hash: str
    status: str = "DRAFT"


@dataclass(frozen=True)
class Evaluation:
    evaluation_id: UUID
    agent_id: UUID
    version: int
    task_type: str
    score: float
    benchmark_id: str
    evidence: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class PerformanceRecord:
    agent_id: UUID
    version: int
    task_type: str
    score: float
    sample_count: int
    window_hash: str


@dataclass(frozen=True)
class ArbitrationDecision:
    task_type: str
    winner_agent_id: UUID
    winner_version: int
    confidence: float
    evidence: tuple[UUID, ...]
    decision_hash: str


@dataclass(frozen=True)
class AgentMemoryRecord:
    memory_id: UUID
    agent_id: UUID
    task_type: str
    content: str
    evidence_ids: tuple[UUID, ...]
    content_hash: str
    active: bool = True


@dataclass(frozen=True)
class CostRecord:
    agent_id: UUID
    version: int
    task_type: str
    input_tokens: int
    output_tokens: int
    cost: float


@dataclass(frozen=True)
class AgentPlatformRun:
    agent_version: AgentVersion
    evaluation: Evaluation
    benchmark_id: str
    performance: PerformanceRecord
    arbitration: ArbitrationDecision
    memory: AgentMemoryRecord
    cost: CostRecord
    regression: bool
    governance_hash: str


class AgentPlatformStore:
    def __init__(self) -> None:
        self.versions: dict[tuple[UUID, int], AgentVersion] = {}
        self.evaluations: list[Evaluation] = []
        self.performance: list[PerformanceRecord] = []
        self.memories: dict[UUID, AgentMemoryRecord] = {}
        self.costs: list[CostRecord] = []
        self.decisions: list[ArbitrationDecision] = []

    def save_evaluation(self, value: Evaluation) -> None:
        self.evaluations.append(value)

    def list_evaluations(self, agent_id: UUID, task_type: str | None = None) -> list[Evaluation]:
        return [x for x in self.evaluations if x.agent_id == agent_id and (task_type is None or x.task_type == task_type)]


class AgentPlatformVerticalSlice:
    """Registration → version → evaluation → benchmark → performance → arbitration → memory → cost → governance."""

    def __init__(self, store: AgentPlatformStore | None = None) -> None:
        self.store = store or AgentPlatformStore()

    def register(self, agent_id: UUID | None = None, config: dict[str, Any] | None = None) -> AgentVersion:
        agent_id = agent_id or uuid4()
        config_hash = _hash(config or {})
        version = AgentVersion(agent_id, 1, config_hash)
        self.store.versions[(agent_id, 1)] = version
        return version

    def evaluate(self, agent_version: AgentVersion, *, task_type: str, benchmark_id: str,
                 score: float, evidence: list[str] | None = None) -> Evaluation:
        if not 0 <= score <= 1:
            raise ValueError("score must be between 0 and 1")
        if self.store.versions.get((agent_version.agent_id, agent_version.version)) is None:
            raise AgentGovernanceError("agent version is not registered")
        value = Evaluation(uuid4(), agent_version.agent_id, agent_version.version, task_type, score,
                            benchmark_id, tuple(evidence or ()))
        self.store.save_evaluation(value)
        return value

    def record_performance(self, evaluation: Evaluation, *, window: str = "evaluation") -> PerformanceRecord:
        prior = self.store.list_evaluations(evaluation.agent_id, evaluation.task_type)
        window_hash = _hash({"window": window, "evaluations": [str(x.evaluation_id) for x in prior]})
        record = PerformanceRecord(evaluation.agent_id, evaluation.version, evaluation.task_type,
                                   evaluation.score, len(prior), window_hash)
        self.store.performance.append(record)
        return record

    def arbitrate(self, evaluations: list[Evaluation], *, task_type: str) -> ArbitrationDecision:
        candidates = [x for x in evaluations if x.task_type == task_type and x.evidence]
        if not candidates:
            raise AgentGovernanceError("arbitration requires task-matched evaluations with evidence")
        candidates.sort(key=lambda x: (-x.score, str(x.agent_id), -x.version))
        winner = candidates[0]
        confidence = winner.score / max(sum(x.score for x in candidates), 1e-12)
        evidence = tuple(x.evaluation_id for x in candidates if x.agent_id == winner.agent_id)
        decision_hash = _hash({"task": task_type, "winner": str(winner.agent_id), "version": winner.version,
                               "evidence": [str(x) for x in evidence], "scores": [x.score for x in candidates]})
        decision = ArbitrationDecision(task_type, winner.agent_id, winner.version, confidence, evidence, decision_hash)
        self.store.decisions.append(decision)
        return decision

    def write_memory(self, agent_id: UUID, *, task_type: str, content: str,
                     evidence_ids: tuple[UUID, ...]) -> AgentMemoryRecord:
        if not content.strip() or not evidence_ids:
            raise AgentGovernanceError("agent memory must contain content and evidence references")
        record = AgentMemoryRecord(uuid4(), agent_id, task_type, content, evidence_ids, sha256(content.encode()).hexdigest())
        self.store.memories[record.memory_id] = record
        return record

    def deactivate_memory(self, memory_id: UUID) -> AgentMemoryRecord:
        record = self.store.memories[memory_id]
        updated = AgentMemoryRecord(record.memory_id, record.agent_id, record.task_type, record.content,
                                     record.evidence_ids, record.content_hash, False)
        self.store.memories[memory_id] = updated
        return updated

    def cost(self, agent_version: AgentVersion, *, task_type: str, input_tokens: int,
             output_tokens: int, unit_cost: float = 0.00001) -> CostRecord:
        if min(input_tokens, output_tokens) < 0 or unit_cost < 0:
            raise ValueError("token counts and unit cost must be non-negative")
        record = CostRecord(agent_version.agent_id, agent_version.version, task_type,
                            input_tokens, output_tokens, (input_tokens + output_tokens) * unit_cost)
        self.store.costs.append(record)
        return record

    def run(self, *, config: dict[str, Any], task_type: str, benchmark_id: str,
            score: float, evidence: list[str], baseline_score: float | None = None,
            memory_content: str = "validated task result", input_tokens: int = 100,
            output_tokens: int = 50) -> AgentPlatformRun:
        version = self.register(config=config)
        evaluation = self.evaluate(version, task_type=task_type, benchmark_id=benchmark_id,
                                   score=score, evidence=evidence)
        performance = self.record_performance(evaluation)
        arbitration = self.arbitrate([evaluation], task_type=task_type)
        memory = self.write_memory(version.agent_id, task_type=task_type, content=memory_content,
                                   evidence_ids=(evaluation.evaluation_id,))
        cost = self.cost(version, task_type=task_type, input_tokens=input_tokens, output_tokens=output_tokens)
        regression = baseline_score is not None and score < baseline_score
        if regression:
            raise AgentGovernanceError("agent regression detected; version cannot be promoted")
        governance_hash = _hash({"agent": str(version.agent_id), "version": version.version,
                                 "evaluation": str(evaluation.evaluation_id), "decision": arbitration.decision_hash,
                                 "memory": str(memory.memory_id), "cost": cost.cost, "regression": regression})
        promoted = AgentVersion(version.agent_id, version.version, version.config_hash, "PROMOTED")
        self.store.versions[(promoted.agent_id, promoted.version)] = promoted
        return AgentPlatformRun(promoted, evaluation, benchmark_id, performance, arbitration,
                                memory, cost, regression, governance_hash)


def _hash(value: Any) -> str:
    import json
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
