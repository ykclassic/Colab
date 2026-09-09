from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from colab.release_governance import GateResult, GovernanceError, ReleaseGovernance, StrategyVersion
from colab.security import ApprovalService, AuthorizationError, Permission, PlatformRole, Principal


def owner(user_id: str = "owner") -> Principal:
    return Principal(user_id=user_id, role=PlatformRole.OWNER)


def reviewer(user_id: str = "reviewer") -> Principal:
    return Principal(user_id=user_id, role=PlatformRole.REVIEWER)


def make_version(governance: ReleaseGovernance | None = None) -> StrategyVersion:
    version = StrategyVersion(
        workspace_id=uuid4(), name="mean-reversion", version=str(uuid4()),
        artifact_digest="a" * 64, manifest_hash="b" * 64,
    )
    if governance is not None:
        governance.register_version(version)
    return version


def test_strategy_versions_are_immutable_domain_objects() -> None:
    version = make_version()
    with pytest.raises(ValidationError):
        version.version = "1.0.1"  # type: ignore[misc]


def test_release_governance_rejects_duplicate_and_unknown_versions() -> None:
    governance = ReleaseGovernance()
    version = make_version(governance)
    with pytest.raises(GovernanceError, match="ID already exists"):
        governance.register_version(version)
    with pytest.raises(GovernanceError, match="not found"):
        governance.get_version(uuid4())


def test_release_governance_requires_gates_and_distinct_stages() -> None:
    governance = ReleaseGovernance()
    version = make_version(governance)
    with pytest.raises(GovernanceError, match="at least one"):
        governance.readiness(version.version_id, ())
    gate = GateResult(gate="reproducibility", passed=True, score=100)
    with pytest.raises(GovernanceError, match="unsupported"):
        governance.promote(version.version_id, "candidate", "invalid", (gate,))
    with pytest.raises(GovernanceError, match="must differ"):
        governance.promote(version.version_id, "candidate", "candidate", (gate,))


def test_promotion_binds_workspace_and_blocks_missing_gate_and_low_score() -> None:
    workspace_id = uuid4()
    governance = ReleaseGovernance()
    version = StrategyVersion(
        workspace_id=workspace_id, name="strategy", version="1.0.0",
        artifact_digest="a" * 64, manifest_hash="b" * 64,
    )
    governance.register_version(version)
    gate = GateResult(gate="reproducibility", passed=True, score=0)
    decision = governance.promote(version.version_id, "candidate", "staging", (gate,))
    assert decision.approved is False
    assert any("missing required gate" in reason for reason in decision.reasons)
    assert any("below" in reason for reason in decision.reasons)
    assert decision.workspace_id == workspace_id


def test_promotion_with_all_required_gates_is_approved() -> None:
    governance = ReleaseGovernance()
    version = make_version(governance)
    gates = tuple(GateResult(gate=name, passed=True, score=100) for name in (
        "reproducibility", "version_integrity", "regression", "operational_readiness", "risk",
    ))
    decision = governance.promote(version.version_id, "staging", "production", gates)
    assert decision.approved is True


def test_legacy_approval_service_keeps_human_separation() -> None:
    service = ApprovalService()
    requester = owner("requester")
    approver = reviewer("approver")
    record = service.request("approval-1", "workflow-1", "artifact-1", 1, "risk-1", requester)
    with pytest.raises(AuthorizationError):
        service.decide(record.approval_id, requester, "approve", "self approval")
    decided = service.decide(record.approval_id, approver, "approve", "independent review")
    assert decided.decision == "approve"
    assert decided.decided_by == "approver"


def test_approval_permission_remains_explicit() -> None:
    principal = Principal("researcher", PlatformRole.RESEARCHER)
    assert principal.can(Permission.APPROVE) is False
