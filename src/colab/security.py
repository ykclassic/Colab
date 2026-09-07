"""Phase 5 identity, authorization, and approval governance primitives."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient


class PlatformRole(StrEnum):
    OWNER = "owner"
    PROJECT_MANAGER = "project_manager"
    RESEARCHER = "quant_researcher"
    STRATEGY = "strategy_developer"
    RISK = "risk_compliance"
    ENGINEER = "software_engineer_qa"
    REVIEWER = "reviewer"


class Permission(StrEnum):
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    RESEARCH_WRITE = "research.write"
    STRATEGY_WRITE = "strategy.write"
    RISK_ASSESS = "risk.assess"
    IMPLEMENT = "implementation.execute"
    VALIDATE = "validation.execute"
    APPROVE = "human.approve"
    AUDIT_READ = "audit.read"


ROLE_PERMISSIONS: dict[PlatformRole, frozenset[Permission]] = {
    PlatformRole.OWNER: frozenset(Permission),
    PlatformRole.PROJECT_MANAGER: frozenset(
        {
            Permission.WORKSPACE_READ,
            Permission.WORKSPACE_WRITE,
            Permission.AUDIT_READ,
            Permission.APPROVE,
        }
    ),
    PlatformRole.RESEARCHER: frozenset(
        {Permission.WORKSPACE_READ, Permission.RESEARCH_WRITE}
    ),
    PlatformRole.STRATEGY: frozenset(
        {Permission.WORKSPACE_READ, Permission.STRATEGY_WRITE}
    ),
    PlatformRole.RISK: frozenset(
        {Permission.WORKSPACE_READ, Permission.RISK_ASSESS, Permission.AUDIT_READ}
    ),
    PlatformRole.ENGINEER: frozenset(
        {Permission.WORKSPACE_READ, Permission.IMPLEMENT, Permission.VALIDATE}
    ),
    PlatformRole.REVIEWER: frozenset(
        {Permission.WORKSPACE_READ, Permission.APPROVE, Permission.AUDIT_READ}
    ),
}


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    role: PlatformRole
    session_id: str | None = None
    email: str | None = None

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


class AuthenticationError(ValueError):
    """Raised when a bearer token cannot be trusted."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks a permission."""


def _supabase_url() -> str:
    value = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not value:
        raise AuthenticationError("SUPABASE_URL is not configured")
    return value


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def authenticate_bearer(token: str) -> Principal:
    """Verify a Supabase access token and derive authorization from app_metadata.

    Authorization data is deliberately read from ``app_metadata`` rather than
    user-editable ``user_metadata``. The issuer and audience are also checked.
    """
    if not token.strip():
        raise AuthenticationError("empty bearer token")
    issuer = f"{_supabase_url()}/auth/v1"
    audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    jwks_url = f"{issuer}/.well-known/jwks.json"
    try:
        key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256", "EdDSA", "HS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except Exception as exc:
        raise AuthenticationError("invalid or expired access token") from exc

    app_metadata = claims.get("app_metadata")
    if not isinstance(app_metadata, dict):
        raise AuthenticationError("access token has no authorization metadata")
    raw_role = app_metadata.get("colab_role")
    if not isinstance(raw_role, str):
        raise AuthenticationError("access token has no valid Colab role")
    try:
        role = PlatformRole(raw_role)
    except ValueError as exc:
        raise AuthenticationError("access token has no valid Colab role") from exc
    return Principal(
        user_id=str(claims["sub"]),
        role=role,
        session_id=str(claims["session_id"]) if claims.get("session_id") else None,
        email=str(claims["email"]) if claims.get("email") else None,
    )


def require_permission(principal: Principal, permission: Permission) -> None:
    if not principal.can(permission):
        raise AuthorizationError(f"missing permission: {permission.value}")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_id: str
    workflow_id: str
    artifact_id: str
    artifact_version: int
    risk_assessment_id: str
    requested_by: str
    decision: str
    decided_by: str | None = None
    rationale: str | None = None


class ApprovalService:
    """In-memory governance boundary; durable persistence is added before production rollout."""

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRecord] = {}

    def request(
        self,
        approval_id: str,
        workflow_id: str,
        artifact_id: str,
        artifact_version: int,
        risk_assessment_id: str,
        requested_by: Principal,
    ) -> ApprovalRecord:
        require_permission(requested_by, Permission.WORKSPACE_WRITE)
        record = ApprovalRecord(
            approval_id=approval_id,
            workflow_id=workflow_id,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            risk_assessment_id=risk_assessment_id,
            requested_by=requested_by.user_id,
            decision="pending",
        )
        self._requests[approval_id] = record
        return record

    def decide(
        self,
        approval_id: str,
        principal: Principal,
        decision: str,
        rationale: str,
    ) -> ApprovalRecord:
        require_permission(principal, Permission.APPROVE)
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not rationale.strip():
            raise ValueError("approval rationale is required")
        try:
            current = self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(approval_id) from exc
        if current.decision != "pending":
            raise ValueError("approval is already decided")
        if current.requested_by == principal.user_id:
            raise AuthorizationError("requester cannot approve their own request")
        updated = ApprovalRecord(
            approval_id=current.approval_id,
            workflow_id=current.workflow_id,
            artifact_id=current.artifact_id,
            artifact_version=current.artifact_version,
            risk_assessment_id=current.risk_assessment_id,
            requested_by=current.requested_by,
            decision=decision,
            decided_by=principal.user_id,
            rationale=rationale.strip(),
        )
        self._requests[approval_id] = updated
        return updated

    def get(self, approval_id: str) -> ApprovalRecord:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(approval_id) from exc


def principal_from_test_header(user_id: str, role: str) -> Principal:
    """Create a principal only when explicitly running the test/development auth mode."""
    if os.getenv("COLAB_ALLOW_TEST_AUTH", "false").lower() != "true":
        raise AuthenticationError("test authentication is disabled")
    try:
        parsed_role = PlatformRole(role)
    except ValueError as exc:
        raise AuthenticationError("invalid test role") from exc
    return Principal(user_id=user_id, role=parsed_role)
