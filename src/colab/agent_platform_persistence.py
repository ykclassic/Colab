"""PostgreSQL persistence for Phase 19 agent records, evaluations, memory and costs."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from .agent_platform import AgentRecord, CostRecord, EvaluationResult, MemoryRecord


class PostgresAgentPlatformStore:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def register_agent(self, agent: AgentRecord) -> AgentRecord:
        with self._connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO public.agents (agent_id, workspace_id, name, version, role, code_revision, model, tools, configuration, enabled, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING agent_id""", (agent.agent_id, agent.workspace_id, agent.name, agent.version, agent.role, agent.code_revision, agent.model, agent.tools, agent.configuration, agent.enabled, agent.created_at))
        return agent

    def list_agents(self, workspace_id: UUID) -> list[AgentRecord]:
        with self._connection_factory() as conn, conn.cursor() as cur:
            cur.execute("SELECT agent_id,workspace_id,name,version,role,code_revision,model,tools,configuration,enabled,created_at FROM public.agents WHERE workspace_id=%s ORDER BY name,version", (workspace_id,))
            rows = cur.fetchall()
        return [AgentRecord(agent_id=r[0], workspace_id=r[1], name=r[2], version=r[3], role=r[4], code_revision=r[5], model=r[6], tools=list(r[7] or []), configuration=dict(r[8] or {}), enabled=r[9], created_at=r[10]) for r in rows]

    def save_evaluations(self, results: list[EvaluationResult]) -> None:
        if not results:
            return
        with self._connection_factory() as conn, conn.cursor() as cur:
            for r in results:
                cur.execute("INSERT INTO public.agent_evaluations (result_id,case_id,agent_id,workspace_id,score,correctness,evidence_quality,latency_ms,tokens_in,tokens_out,cost_usd,passed,rationale,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (r.result_id,r.case_id,r.agent_id,r.workspace_id,r.score,r.correctness,r.evidence_quality,r.latency_ms,r.tokens_in,r.tokens_out,r.cost_usd,r.passed,r.rationale,r.created_at))

    def save_memory(self, memory: MemoryRecord) -> MemoryRecord:
        with self._connection_factory() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO public.agent_memory (memory_id,workspace_id,agent_id,key,value,source,confidence,expires_at,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (memory.memory_id,memory.workspace_id,memory.agent_id,memory.key,memory.value,memory.source,memory.confidence,memory.expires_at,memory.created_at))
        return memory

    def list_memory(self, workspace_id: UUID, agent_id: UUID | None = None) -> list[MemoryRecord]:
        with self._connection_factory() as conn, conn.cursor() as cur:
            if agent_id:
                cur.execute("SELECT memory_id,workspace_id,agent_id,key,value,source,confidence,expires_at,created_at FROM public.agent_memory WHERE workspace_id=%s AND (agent_id IS NULL OR agent_id=%s) ORDER BY created_at DESC", (workspace_id,agent_id))
            else:
                cur.execute("SELECT memory_id,workspace_id,agent_id,key,value,source,confidence,expires_at,created_at FROM public.agent_memory WHERE workspace_id=%s ORDER BY created_at DESC", (workspace_id,))
            rows = cur.fetchall()
        return [MemoryRecord(memory_id=r[0],workspace_id=r[1],agent_id=r[2],key=r[3],value=r[4],source=r[5],confidence=r[6],expires_at=r[7],created_at=r[8]) for r in rows]

    def save_cost(self, record: CostRecord) -> CostRecord:
        with self._connection_factory() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO public.agent_costs (record_id,workspace_id,agent_id,model,tokens_in,tokens_out,cost_usd,latency_ms,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (record.record_id,record.workspace_id,record.agent_id,record.model,record.tokens_in,record.tokens_out,record.cost_usd,record.latency_ms,record.created_at))
        return record
