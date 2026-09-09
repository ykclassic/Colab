"""Phase 21F database integrity: immutable evaluations and workspace-bound agent state."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from .agent_platform import AgentRecord
from .agent_platform_vertical_slice import AgentBenchmark, AgentGovernanceDecision


class PostgresAgentPlatformVerticalSliceStore:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def save_agent_version(self, agent: AgentRecord) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("""INSERT INTO public.agent_versions (agent_id,workspace_id,name,version,role,code_revision,model,tools,configuration,enabled,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (agent_id,version) DO NOTHING""", (agent.agent_id, agent.workspace_id, agent.name, agent.version, agent.role, agent.code_revision, agent.model, agent.tools, agent.configuration, agent.enabled, agent.created_at))

    def save_benchmark(self, benchmark: AgentBenchmark) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("""INSERT INTO public.agent_benchmarks (agent_id,version,evaluation_ids,score,pass_rate,evidence_quality,regression,baseline_score,benchmark_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (benchmark.agent_id, benchmark.version, list(benchmark.evaluation_ids), benchmark.score, benchmark.pass_rate, benchmark.evidence_quality, benchmark.regression, benchmark.baseline_score, benchmark.benchmark_hash))

    def save_governance(self, decision: AgentGovernanceDecision) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("""INSERT INTO public.agent_version_governance (agent_id,version,approved,reason,benchmark_hash,decided_at) VALUES (%s,%s,%s,%s,%s,%s)""", (decision.agent_id, decision.version, decision.approved, decision.reason, decision.benchmark_hash, decision.decided_at))

    def list_agent_versions(self, workspace_id: UUID, name: str) -> list[AgentRecord]:
        with self._connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT agent_id,workspace_id,name,version,role,code_revision,model,tools,configuration,enabled,created_at FROM public.agent_versions WHERE workspace_id=%s AND name=%s ORDER BY version""", (workspace_id, name))
            rows = cur.fetchall()
        return [AgentRecord(agent_id=r[0], workspace_id=r[1], name=r[2], version=r[3], role=r[4], code_revision=r[5], model=r[6], tools=list(r[7] or []), configuration=dict(r[8] or {}), enabled=r[9], created_at=r[10]) for r in rows]
