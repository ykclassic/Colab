"""Phase 19 agent platform: registry, evaluation, memory, arbitration and cost analytics."""
from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

class AgentPlatformError(RuntimeError):
    pass

class AgentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    role: str = Field(min_length=1, max_length=100)
    code_revision: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    tools: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    task: str = Field(min_length=1, max_length=20000)
    expected: str | None = None
    evidence_required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    agent_id: UUID
    workspace_id: UUID
    score: float = Field(ge=0, le=1)
    correctness: float = Field(ge=0, le=1)
    evidence_quality: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)
    passed: bool
    rationale: str = Field(min_length=1, max_length=10000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class EvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    cases: int
    pass_rate: float
    mean_score: float
    p95_latency_ms: float
    total_cost_usd: float
    cost_per_pass: float

class HistoricalPerformance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    observations: int
    pass_rate: float
    mean_score: float
    score_trend: float
    cost_per_pass: float

class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1, max_length=5000)
    strength: float = Field(ge=0, le=1)

class ArbitrationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    answer: str = Field(min_length=1, max_length=20000)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)

class ArbitrationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    winner_agent_id: UUID
    score: float
    evidence_score: float
    rationale: str
    tied: bool = False

class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    agent_id: UUID | None = None
    key: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=20000)
    source: str = Field(min_length=1, max_length=500)
    confidence: float = Field(default=1, ge=0, le=1)
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class CostRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    agent_id: UUID
    model: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class CostSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    calls: int
    total_cost_usd: float
    tokens_in: int
    tokens_out: int
    mean_latency_ms: float
    cost_per_1k_tokens: float

class AgentRegistry(Protocol):
    def register(self, agent: AgentRecord) -> AgentRecord: ...
    def list(self, workspace_id: UUID) -> list[AgentRecord]: ...

class InMemoryAgentRegistry:
    def __init__(self) -> None:
        self._items: dict[UUID, AgentRecord] = {}
    def register(self, agent: AgentRecord) -> AgentRecord:
        existing = [x for x in self._items.values() if x.workspace_id == agent.workspace_id and x.name == agent.name]
        if existing and agent.version <= max(x.version for x in existing):
            raise AgentPlatformError("agent version must increase")
        self._items[agent.agent_id] = agent
        return agent
    def list(self, workspace_id: UUID) -> list[AgentRecord]:
        return sorted((x for x in self._items.values() if x.workspace_id == workspace_id), key=lambda x: (x.name, x.version))

def evaluate_results(results: list[EvaluationResult], agent_id: UUID) -> EvaluationSummary:
    items = [x for x in results if x.agent_id == agent_id]
    if not items: raise AgentPlatformError("no evaluation results for agent")
    latencies = sorted(x.latency_ms for x in items); p95 = latencies[min(len(latencies)-1, math.ceil(len(latencies)*.95)-1)]
    passed = sum(x.passed for x in items); cost = sum(x.cost_usd for x in items)
    return EvaluationSummary(agent_id=agent_id,cases=len(items),pass_rate=passed/len(items),mean_score=statistics.fmean(x.score for x in items),p95_latency_ms=p95,total_cost_usd=cost,cost_per_pass=cost/passed if passed else float("inf"))

def historical_performance(results: list[EvaluationResult], agent_id: UUID) -> HistoricalPerformance:
    items=sorted((x for x in results if x.agent_id==agent_id),key=lambda x:x.created_at)
    if not items: raise AgentPlatformError("no historical results for agent")
    scores=[x.score for x in items]; n=min(10,len(scores)); trend=statistics.fmean(scores[-n:])-statistics.fmean(scores[:n]) if len(scores)>1 else 0.0; passed=sum(x.passed for x in items); cost=sum(x.cost_usd for x in items)
    return HistoricalPerformance(agent_id=agent_id,observations=len(items),pass_rate=passed/len(items),mean_score=statistics.fmean(scores),score_trend=trend,cost_per_pass=cost/passed if passed else float("inf"))

def arbitrate(candidates: list[ArbitrationCandidate], minimum_evidence: float=.5) -> ArbitrationDecision:
    if not candidates: raise AgentPlatformError("candidates cannot be empty")
    scored=[]
    for candidate in candidates:
        evidence=statistics.fmean(x.strength for x in candidate.evidence) if candidate.evidence else 0.0; score=candidate.confidence*(.5+.5*evidence); score*=.5 if evidence<minimum_evidence else 1.0; scored.append((candidate,score,evidence))
    scored.sort(key=lambda x:x[1],reverse=True); winner,score,evidence=scored[0]; tied=len(scored)>1 and math.isclose(score,scored[1][1],rel_tol=1e-9,abs_tol=1e-9)
    return ArbitrationDecision(winner_agent_id=winner.agent_id,score=score,evidence_score=evidence,rationale="Selected highest confidence weighted by independent evidence strength; weakly evidenced candidates are penalized.",tied=tied)

def retrieve_memory(memories:list[MemoryRecord],workspace_id:UUID,query:str,agent_id:UUID|None=None,limit:int=10)->list[MemoryRecord]:
    now=datetime.now(UTC); terms=set(query.lower().split()); eligible=[m for m in memories if m.workspace_id==workspace_id and (agent_id is None or m.agent_id in (None,agent_id)) and (m.expires_at is None or m.expires_at>now)]; ranked=sorted(eligible,key=lambda m:(len(terms & set((m.key+" "+m.value).lower().split())),m.confidence),reverse=True); return ranked[:limit]

def summarize_costs(records:list[CostRecord],agent_id:UUID)->CostSummary:
    items=[x for x in records if x.agent_id==agent_id]
    if not items: raise AgentPlatformError("no cost records for agent")
    tokens=sum(x.tokens_in+x.tokens_out for x in items); cost=sum(x.cost_usd for x in items)
    return CostSummary(agent_id=agent_id,calls=len(items),total_cost_usd=cost,tokens_in=sum(x.tokens_in for x in items),tokens_out=sum(x.tokens_out for x in items),mean_latency_ms=statistics.fmean(x.latency_ms for x in items),cost_per_1k_tokens=cost/tokens*1000 if tokens else 0.0)

def evaluation_hash(result:EvaluationResult)->str: return sha256(result.model_dump_json().encode()).hexdigest()
