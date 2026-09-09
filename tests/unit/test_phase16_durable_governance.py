from __future__ import annotations

from uuid import uuid4

import pytest

from colab.release_governance import GateResult, ReleaseGovernance, StrategyVersion
from colab.security import ApprovalService, Permission, PlatformRole, Principal


def owner(user_id: str = "owner") -> Principal:
    return Principal(user_id=user_id, role=PlatformRole.OWNER)


def reviewer(user_id: str = "reviewer") -> Principal:
    return Principal(user_id=user_id, role=PlatformRole.REVIEWER)


def test_strategy_versions_are_immutable_domain_objects() -> None:
    version = StrategyVersion(
        workspace_id=uuid4(), name="mean-reversion", version="1.0.0",
        artifact_digest="a" * 64, manifest_hash="b" * 64,
    )
    with pytest.raises(Exception):
        version.version = "1.0.1"  # type: ignore[misc]


def test_promotion_binds_workspace_and_persists_gate_decision_in_service_contract() -> None:
    workspace_id = uuid4()
    governance = ReleaseGovernance()
    version = governance.register_version(StrategyVersion(
        workspace_id=workspace_id, name="strategy", version="1.0.0",
        artifact_digest="a" * 64, manifest_hash="b" * 64,
    ))
    gates = tuple(GateResult(gate=name, passed=True, score=100) for name in (
        "reproducibility", "version_integrity", "regression", "operational_readiness", "risk",
    ))
    decision = governance.promote(version.version_id, "staging", "production", gates)
    assert decision.approved is True
    assert decision.workspace_id == workspace_id
    assert {gate.gate for gate in decision.gates} == {gate.gate for gate in gates}


def test_failed_required_gate_is_a_deterministic_promotion_blocker() -> None:
    governance = ReleaseGovernance()
    version = governance.register_version(StrategyVersion(
        workspace_id=uuid4(), name="strategy", version="1.0.0",
        artifact_digest="a" * 64, manifest_hash="b" * 64,
    ))
    gates = tuple(GateResult(gate=name, passed=name != "risk", score=100 if name != "risk" else 0) for name in (
        "reproducibility", "version_integrity", "regression", "operational_readiness", "risk",
    ))
    decision = governance.promote(version.version_id, "staging", "production", gates)
    assert decision.approved is False
    assert "required gate failed: risk" in decision.reasons


def test_legacy_approval_service_keeps_human_separation() -> None:
    service = ApprovalService()
    requester = owner("requester")
    approver = reviewer("approver")
    record = service.request("approval-1", "workflow-1", "artifact-1", 1, "risk-1", requester)
    with pytest.raises(Exception):
        service.decide(record.approval_id, requester, "approve", "self approval")
    decided = service.decide(record.approval_id, approver, "approve", "independent review")
    assert decided.decision == "approve"
    assert decided.decided_by == "approver"


def test_approval_permission_remains_explicit() -> None:
    principal = Principal("researcher", PlatformRole.RESEARCHER)
    assert principal.can(Permission.APPROVE) is False
