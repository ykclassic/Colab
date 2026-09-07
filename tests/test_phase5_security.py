import os

import pytest

from colab.security import (
    ApprovalService,
    AuthorizationError,
    Permission,
    PlatformRole,
    Principal,
    ROLE_PERMISSIONS,
    principal_from_test_header,
    require_permission,
)


def test_role_permissions_keep_risk_and_approval_independent() -> None:
    assert Permission.RISK_ASSESS in ROLE_PERMISSIONS[PlatformRole.RISK]
    assert Permission.APPROVE not in ROLE_PERMISSIONS[PlatformRole.RISK]
    assert Permission.APPROVE in ROLE_PERMISSIONS[PlatformRole.REVIEWER]
    assert Permission.STRATEGY_WRITE not in ROLE_PERMISSIONS[PlatformRole.REVIEWER]


def test_principal_permission_check_and_denial() -> None:
    principal = Principal(user_id="risk-user", role=PlatformRole.RISK)
    assert principal.can(Permission.RISK_ASSESS)
    assert not principal.can(Permission.APPROVE)
    with pytest.raises(AuthorizationError):
        require_permission(principal, Permission.APPROVE)


def test_approval_requires_independent_approver_and_rationale() -> None:
    service = ApprovalService()
    requester = Principal(user_id="manager", role=PlatformRole.PROJECT_MANAGER)
    reviewer = Principal(user_id="reviewer", role=PlatformRole.REVIEWER)
    request = service.request(
        "approval-1", "workflow-1", "artifact-1", 3, "risk-1", requester
    )
    assert request.decision == "pending"

    with pytest.raises(AuthorizationError):
        service.decide("approval-1", requester, "approve", "self approval")
    with pytest.raises(ValueError, match="rationale"):
        service.decide("approval-1", reviewer, "approve", " ")

    decided = service.decide("approval-1", reviewer, "approve", "Risk gate passed.")
    assert decided.decision == "approve"
    assert decided.decided_by == "reviewer"
    assert service.get("approval-1") == decided

    with pytest.raises(ValueError, match="already decided"):
        service.decide("approval-1", reviewer, "reject", "Too late.")


def test_approval_request_requires_permission_and_valid_decision() -> None:
    service = ApprovalService()
    researcher = Principal(user_id="researcher", role=PlatformRole.RESEARCHER)
    with pytest.raises(AuthorizationError):
        service.request("approval-2", "workflow-2", "artifact-2", 1, "risk-2", researcher)

    manager = Principal(user_id="manager", role=PlatformRole.PROJECT_MANAGER)
    service.request("approval-3", "workflow-3", "artifact-3", 1, "risk-3", manager)
    reviewer = Principal(user_id="reviewer", role=PlatformRole.REVIEWER)
    with pytest.raises(ValueError, match="approve or reject"):
        service.decide("approval-3", reviewer, "revise", "Need more evidence.")


def test_test_auth_mode_is_explicitly_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLAB_ALLOW_TEST_AUTH", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        principal_from_test_header("user", "reviewer")

    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")
    principal = principal_from_test_header("user", "reviewer")
    assert principal.role is PlatformRole.REVIEWER


def test_invalid_test_role_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")
    with pytest.raises(ValueError, match="invalid test role"):
        principal_from_test_header("user", "not-a-role")
