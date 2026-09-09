"""PostgreSQL-backed durable release governance and approval persistence."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .release_governance import GateResult, PromotionDecision, ReadinessReport, StrategyVersion
from .security import ApprovalRecord, Permission, Principal, require_permission

ConnectionFactory = Callable[[], Connection[Any]]


class DurableGovernance:
    """Append-only PostgreSQL governance store with the same policy as ReleaseGovernance."""

    POLICIES = {
        "candidate": (70.0, ("reproducibility", "version_integrity", "regression")),
        "staging": (80.0, ("reproducibility", "version_integrity", "regression", "operational_readiness")),
        "production": (90.0, ("reproducibility", "version_integrity", "regression", "operational_readiness", "risk")),
    }

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def register_version(self, version: StrategyVersion) -> StrategyVersion:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.governance_strategy_versions
                   (version_id,workspace_id,name,version,artifact_digest,manifest_hash,created_at,metadata)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (version.version_id, version.workspace_id, version.name, version.version,
                 version.artifact_digest, version.manifest_hash, version.created_at, Jsonb(version.metadata)),
            )
            if cur.rowcount != 1:
                raise ValueError("strategy version already registered")
        return version

    def get_version(self, version_id: UUID) -> StrategyVersion:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.governance_strategy_versions WHERE version_id=%s", (version_id,))
            row = cur.fetchone()
        if row is None:
            raise ValueError("strategy version not found")
        return StrategyVersion.model_validate(row)

    def versions(self, workspace_id: UUID | None = None) -> tuple[StrategyVersion, ...]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            if workspace_id is None:
                cur.execute("SELECT * FROM public.governance_strategy_versions ORDER BY created_at, version_id")
            else:
                cur.execute("SELECT * FROM public.governance_strategy_versions WHERE workspace_id=%s ORDER BY created_at, version_id", (workspace_id,))
            return tuple(StrategyVersion.model_validate(row) for row in cur.fetchall())

    @staticmethod
    def _readiness(version_id: UUID, workspace_id: UUID, gates: tuple[GateResult, ...]) -> ReadinessReport:
        if not gates:
            raise ValueError("at least one gate result is required")
        dimensions = {gate.gate: gate.score for gate in gates}
        score = sum(dimensions.values()) / len(dimensions)
        blocking = tuple(gate.gate for gate in gates if gate.required and not gate.passed)
        rating = "production-ready" if score >= 90 and not blocking else "staging-ready" if score >= 80 and not blocking else "candidate-ready" if score >= 70 and not blocking else "not-ready"
        return ReadinessReport(version_id=version_id, workspace_id=workspace_id, score=score, rating=rating, dimensions=dimensions, blocking_gates=blocking)

    def readiness(self, version_id: UUID, gates: tuple[GateResult, ...]) -> ReadinessReport:
        version = self.get_version(version_id)
        report = self._readiness(version_id, version.workspace_id, gates)
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.governance_readiness_reports
                   (workspace_id,version_id,score,rating,dimensions,blocking_gates,generated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (report.workspace_id, report.version_id, report.score, report.rating,
                 Jsonb(report.dimensions), Jsonb(list(report.blocking_gates)), report.generated_at),
            )
        return report

    def promote(self, version_id: UUID, from_stage: str, to_stage: str, gates: tuple[GateResult, ...]) -> PromotionDecision:
        policy = self.POLICIES.get(to_stage)
        if policy is None:
            raise ValueError(f"unsupported promotion stage: {to_stage}")
        if from_stage == to_stage:
            raise ValueError("source and target stages must differ")
        version = self.get_version(version_id)
        report = self._readiness(version_id, version.workspace_id, gates)
        by_name = {gate.gate: gate for gate in gates}
        reasons: list[str] = []
        for required in policy[1]:
            gate = by_name.get(required)
            if gate is None:
                reasons.append(f"missing required gate: {required}")
            elif not gate.passed:
                reasons.append(f"required gate failed: {required}")
        if report.score < policy[0]:
            reasons.append(f"readiness score {report.score:.2f} is below {policy[0]:.2f}")
        decision = PromotionDecision(version_id=version_id, workspace_id=version.workspace_id, from_stage=from_stage,
                                     to_stage=to_stage, approved=not reasons, readiness_score=report.score,
                                     gates=gates, reasons=tuple(reasons))
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            for gate in gates:
                cur.execute(
                    """INSERT INTO public.governance_gate_results
                       (workspace_id,version_id,gate,passed,score,required,evidence,checked_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (version.workspace_id, version_id, gate.gate, gate.passed, gate.score, gate.required, gate.evidence, gate.checked_at),
                )
            cur.execute(
                """INSERT INTO public.governance_readiness_reports
                   (workspace_id,version_id,score,rating,dimensions,blocking_gates,generated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (report.workspace_id, report.version_id, report.score, report.rating,
                 Jsonb(report.dimensions), Jsonb(list(report.blocking_gates)), report.generated_at),
            )
            cur.execute(
                """INSERT INTO public.governance_promotion_decisions
                   (decision_id,workspace_id,version_id,from_stage,to_stage,approved,readiness_score,gates,reasons,decided_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (decision.decision_id, decision.workspace_id, decision.version_id, decision.from_stage,
                 decision.to_stage, decision.approved, decision.readiness_score,
                 Jsonb([gate.model_dump(mode="json") for gate in gates]), Jsonb(list(decision.reasons)), decision.decided_at),
            )
        return decision

    def decisions(self, workspace_id: UUID | None = None) -> tuple[PromotionDecision, ...]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            if workspace_id is None:
                cur.execute("SELECT * FROM public.governance_promotion_decisions ORDER BY decided_at, decision_id")
            else:
                cur.execute("SELECT * FROM public.governance_promotion_decisions WHERE workspace_id=%s ORDER BY decided_at, decision_id", (workspace_id,))
            return tuple(PromotionDecision.model_validate({**row, "gates": tuple(row["gates"]), "reasons": tuple(row["reasons"])} ) for row in cur.fetchall())

    def request_approval(
        self, workspace_id: UUID, workflow_id: str, artifact_id: str, strategy_version_id: UUID,
        artifact_digest: str, risk_assessment_id: str, risk_assessment_digest: str,
        required_reviewers: int, principal: Principal,
    ) -> ApprovalRecord:
        require_permission(principal, Permission.APPROVE)
        if required_reviewers < 1:
            raise ValueError("required reviewers must be at least one")
        approval_id = uuid4()
        workflow_uuid = UUID(workflow_id) if workflow_id else None
        artifact_uuid = UUID(artifact_id) if artifact_id else None
        risk_uuid = UUID(risk_assessment_id) if risk_assessment_id else None
        record = ApprovalRecord(
            approval_id=str(approval_id), workflow_id=workflow_id, artifact_id=artifact_id,
            risk_assessment_id=risk_assessment_id, requested_by=principal.user_id, decision="pending",
            decided_by=None, rationale=None, required_reviewers=required_reviewers,
            workspace_id=str(workspace_id), strategy_version_id=str(strategy_version_id),
            artifact_digest=artifact_digest, risk_assessment_digest=risk_assessment_digest,
        )
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.governance_approvals
                   (approval_id,workspace_id,workflow_id,artifact_id,strategy_version_id,artifact_digest,
                    risk_assessment_id,risk_assessment_digest,requested_by,decision,required_reviewers,requested_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)""",
                (approval_id, workspace_id, workflow_uuid, artifact_uuid, strategy_version_id, artifact_digest,
                 risk_uuid, risk_assessment_digest, UUID(principal.user_id), required_reviewers, datetime.now(UTC)),
            )
        return record

    def decide_approval(self, approval_id: UUID, principal: Principal, decision: str, rationale: str) -> ApprovalRecord:
        require_permission(principal, Permission.APPROVE)
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not rationale.strip():
            raise ValueError("rationale is required")
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.governance_approvals WHERE approval_id=%s", (approval_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError("approval not found")
            if row["decision"] != "pending":
                raise ValueError("approval already decided")
            if str(row["requested_by"]) == principal.user_id:
                raise PermissionError("requester cannot approve their own request")
            cur.execute("SELECT 1 FROM public.governance_approval_invalidations WHERE approval_id=%s LIMIT 1", (approval_id,))
            if cur.fetchone() is not None:
                raise ValueError("approval has been invalidated by a governed artifact change")
            now = datetime.now(UTC)
            # The base approval is immutable. Record the decision as a new append-only approval event
            # with the same binding, and expose the latest effective decision through get_approval().
            cur.execute(
                """INSERT INTO public.governance_approvals
                   (approval_id,workspace_id,workflow_id,artifact_id,strategy_version_id,artifact_digest,
                    risk_assessment_id,risk_assessment_digest,requested_by,decision,decided_by,rationale,required_reviewers,requested_at,decided_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uuid4(), row["workspace_id"], row["workflow_id"], row["artifact_id"], row["strategy_version_id"],
                 row["artifact_digest"], row["risk_assessment_id"], row["risk_assessment_digest"], row["requested_by"],
                 decision, UUID(principal.user_id), rationale.strip(), row["required_reviewers"], row["requested_at"], now),
            )
            return self._approval_from_row(row | {"decision": decision, "decided_by": UUID(principal.user_id), "rationale": rationale.strip(), "decided_at": now})

    @staticmethod
    def _approval_from_row(row: dict[str, Any]) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=str(row["approval_id"]), workflow_id=str(row["workflow_id"] or ""), artifact_id=str(row["artifact_id"] or ""),
            risk_assessment_id=str(row["risk_assessment_id"] or ""), requested_by=str(row["requested_by"]), decision=str(row["decision"]),
            decided_by=str(row["decided_by"]) if row.get("decided_by") else None, rationale=row.get("rationale"),
            required_reviewers=int(row["required_reviewers"]), workspace_id=str(row["workspace_id"]),
            strategy_version_id=str(row["strategy_version_id"]), artifact_digest=str(row["artifact_digest"]),
            risk_assessment_digest=str(row["risk_assessment_digest"]),
        )

    def approvals(self, workspace_id: UUID) -> tuple[ApprovalRecord, ...]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT DISTINCT ON (COALESCE(workflow_id::text,'') , strategy_version_id)
                    * FROM public.governance_approvals
                   WHERE workspace_id=%s
                   ORDER BY COALESCE(workflow_id::text,''), strategy_version_id, requested_at DESC, approval_id DESC""",
                (workspace_id,),
            )
            return tuple(self._approval_from_row(row) for row in cur.fetchall())
