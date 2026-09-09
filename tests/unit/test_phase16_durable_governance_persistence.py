from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Self
from uuid import uuid4

from colab.durable_governance import DurableGovernance
from colab.release_governance import GateResult, StrategyVersion
from colab.security import Permission, PlatformRole, Principal


class FakeCursor:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.rowcount = 0
        self.row: dict[str, object] | tuple[object, ...] | None = None
        self.rows: list[dict[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0
        if normalized.startswith("insert into public.governance_strategy_versions"):
            self.rowcount = 1
        elif "select * from public.governance_strategy_versions where version_id" in normalized:
            self.row = self.state["version"]  # type: ignore[assignment]
        elif "select * from public.governance_strategy_versions" in normalized and "order by" in normalized:
            self.rows = [self.state["version"]]  # type: ignore[list-item]
        elif normalized.startswith(("insert into public.governance_readiness_reports", "insert into public.governance_gate_results", "insert into public.governance_promotion_decisions")):
            self.rowcount = 1
        elif "select * from public.governance_promotion_decisions" in normalized and "order by" in normalized:
            self.rows = [self.state["decision"]]  # type: ignore[list-item]
        elif "select * from public.governance_approvals where approval_id" in normalized:
            self.row = self.state["approval"]  # type: ignore[assignment]
        elif "select 1 from public.governance_approval_invalidations" in normalized:
            self.row = None
        elif normalized.startswith("insert into public.governance_approvals"):
            self.rowcount = 1
            if isinstance(params, tuple) and len(params) > 9 and params[9] in {"approve", "reject"}:
                updated = dict(self.state["approval"])  # type: ignore[arg-type]
                updated.update({"decision": params[9], "decided_by": params[10], "rationale": params[11], "decided_at": params[14]})
                self.state["approval"] = updated
            self.state["approval_inserted"] = True
        elif "select workspace_id from public.governance_approvals" in normalized:
            approval = self.state["approval"]  # type: ignore[assignment]
            self.row = (approval["workspace_id"],)  # type: ignore[index]
        elif "select distinct on" in normalized and "governance_approvals" in normalized:
            self.rows = [self.state["approval"]]  # type: ignore[list-item]

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeConnection:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    @contextmanager
    def transaction(self):
        yield self

    def cursor(self, **kwargs: object) -> FakeCursor:
        del kwargs
        return FakeCursor(self.state)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_durable_governance_round_trip_contract() -> None:
    workspace_id = uuid4()
    version_id = uuid4()
    owner_id = uuid4()
    decision_id = uuid4()
    approval_id = uuid4()
    now = datetime.now(UTC)
    version = StrategyVersion(
        version_id=version_id, workspace_id=workspace_id, name="strategy", version="1.0.0",
        artifact_digest="a" * 64, manifest_hash="b" * 64, created_at=now,
    )
    gate = GateResult(gate="reproducibility", passed=True, score=100, checked_at=now)
    decision_row = {
        "decision_id": decision_id, "version_id": version_id, "workspace_id": workspace_id,
        "from_stage": "candidate", "to_stage": "staging", "approved": True,
        "readiness_score": 100.0, "gates": [gate.model_dump(mode="json")], "reasons": [], "decided_at": now,
    }
    approval_row = {
        "approval_id": approval_id, "workspace_id": workspace_id, "workflow_id": None,
        "artifact_id": None, "strategy_version_id": version_id, "artifact_digest": "a" * 64,
        "risk_assessment_id": None, "risk_assessment_digest": "r" * 64, "requested_by": owner_id,
        "decision": "pending", "decided_by": None, "rationale": None, "required_reviewers": 1,
        "requested_at": now, "decided_at": None,
    }
    state: dict[str, object] = {"version": version.model_dump(mode="json"), "decision": decision_row, "approval": approval_row}

    def factory() -> FakeConnection:
        return FakeConnection(state)

    governance = DurableGovernance(factory)  # type: ignore[arg-type]
    assert governance.register_version(version) == version
    assert governance.get_version(version_id).version == "1.0.0"
    assert governance.versions(workspace_id)[0].version_id == version_id
    report = governance.readiness(version_id, (gate,))
    assert report.score == 100
    promoted = governance.promote(version_id, "candidate", "staging", (gate,))
    assert promoted.approved is False
    assert governance.decisions(workspace_id)[0].decision_id == decision_id

    principal = Principal(str(owner_id), PlatformRole.OWNER)
    approval = governance.request_approval(
        workspace_id, "", "", version_id, "a" * 64, "", "r" * 64, 1, principal,
    )
    assert approval.workspace_id == str(workspace_id)
    assert principal.can(Permission.APPROVE)

    reviewer = Principal(str(uuid4()), PlatformRole.REVIEWER)
    decided = governance.decide_approval(approval_id, reviewer, "approve", "reviewed")
    assert decided.decision == "approve"
    assert governance.approvals(workspace_id)[0].decision == "approve"
