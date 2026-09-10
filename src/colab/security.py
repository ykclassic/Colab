"""Phase 13 identity, authorization, tenant isolation, and governance security."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
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
    INTEGRATION_READ = "integration.read"


ROLE_PERMISSIONS: dict[PlatformRole, frozenset[Permission]] = {
    PlatformRole.OWNER: frozenset(Permission),
    PlatformRole.PROJECT_MANAGER: frozenset({Permission.WORKSPACE_READ, Permission.WORKSPACE_WRITE, Permission.AUDIT_READ, Permission.APPROVE, Permission.INTEGRATION_READ}),
    PlatformRole.RESEARCHER: frozenset({Permission.WORKSPACE_READ, Permission.RESEARCH_WRITE}),
    PlatformRole.STRATEGY: frozenset({Permission.WORKSPACE_READ, Permission.STRATEGY_WRITE}),
    PlatformRole.RISK: frozenset({Permission.WORKSPACE_READ, Permission.RISK_ASSESS, Permission.AUDIT_READ}),
    PlatformRole.ENGINEER: frozenset({Permission.WORKSPACE_READ, Permission.IMPLEMENT, Permission.VALIDATE}),
    PlatformRole.REVIEWER: frozenset({Permission.WORKSPACE_READ, Permission.APPROVE, Permission.AUDIT_READ, Permission.INTEGRATION_READ}),
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: PlatformRole
    session_id: str | None = None
    email: str | None = None

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


class AuthenticationError(ValueError):
    """Raised when an access token cannot be trusted."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks a permission."""


def auth_required() -> bool:
    configured = os.getenv("COLAB_REQUIRE_AUTH")
    if configured is not None:
        return configured.lower() == "true"
    return os.getenv("COLAB_ENV", "development").lower() == "production"


def _supabase_url() -> str:
    value = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not value:
        raise AuthenticationError("SUPABASE_URL is not configured")
    return value


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def authenticate_bearer(token: str) -> Principal:
    if not token.strip():
        raise AuthenticationError("empty bearer token")
    issuer = f"{_supabase_url()}/auth/v1"
    audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        secret = os.getenv("COLAB_JWT_SECRET")
        if secret:
            if algorithm not in {"HS256", "HS384", "HS512"}:
                raise AuthenticationError("unsupported local JWT algorithm")
            claims: dict[str, Any] = jwt.decode(token, secret, algorithms=[algorithm], audience=audience, issuer=issuer, options={"require": ["sub", "exp", "iat", "iss", "aud"]})
        else:
            if algorithm not in {"RS256", "ES256", "EdDSA"}:
                raise AuthenticationError("unsupported Supabase JWT algorithm")
            key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=[algorithm], audience=audience, issuer=issuer, options={"require": ["sub", "exp", "iat", "iss", "aud"]})
    except (jwt.PyJWTError, AuthenticationError, ValueError, OSError) as exc:
        raise AuthenticationError("invalid or expired access token") from exc
    subject = claims.get("sub")
    app_metadata = claims.get("app_metadata")
    if not isinstance(subject, str) or not isinstance(app_metadata, dict):
        raise AuthenticationError("access token is missing required claims")
    raw_role = app_metadata.get("colab_role")
    if not isinstance(raw_role, str):
        raise AuthenticationError("access token has no valid Colab role")
    try:
        role = PlatformRole(raw_role)
    except ValueError as exc:
        raise AuthenticationError("access token has no valid Colab role") from exc
    return Principal(user_id=subject, role=role, session_id=str(claims["session_id"]) if claims.get("session_id") else None, email=str(claims["email"]) if claims.get("email") else None)


def principal_from_test_header(user_id: str, role: str) -> Principal:
    if os.getenv("COLAB_ENV", "development").lower() == "production":
        raise ValueError("test authentication is disabled in production")
    if os.getenv("COLAB_ALLOW_TEST_AUTH", "false").lower() != "true":
        raise ValueError("test authentication is disabled")
    try:
        return Principal(user_id=user_id, role=PlatformRole(role))
    except ValueError as exc:
        raise ValueError("invalid test role") from exc


def require_permission(principal: Principal, permission: Permission) -> None:
    if not principal.can(permission):
        raise AuthorizationError(f"missing permission: {permission.value}")


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            principal = authenticate_bearer(token.strip())
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc
        request.state.principal = principal
        return principal
    if os.getenv("COLAB_ENV", "development").lower() != "production" and os.getenv("COLAB_ALLOW_TEST_AUTH", "false").lower() == "true":
        test_user, test_role = request.headers.get("X-Test-User"), request.headers.get("X-Test-Role")
        if test_user and test_role:
            try:
                principal = principal_from_test_header(test_user, test_role)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc
            request.state.principal = principal
            return principal
    if not auth_required():
        principal = Principal(user_id="development", role=PlatformRole.OWNER)
        request.state.principal = principal
        return principal
    raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})


def get_current_principal(request: Request) -> Principal:
    return current_principal(request)


def membership_role(connection_factory: Any, workspace_id: UUID, user_id: str) -> str | None:
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return None
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT role FROM public.workspace_memberships WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_uuid))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def require_workspace_membership(request: Request, workspace_id: UUID, permission: Permission = Permission.WORKSPACE_READ) -> Principal:
    principal = current_principal(request)
    services = getattr(request.app.state, "services", None)
    database = getattr(services, "database", None)
    if database is not None:
        role_name = membership_role(database._connection_factory, workspace_id, principal.user_id)
        if role_name is None:
            raise HTTPException(status_code=404, detail="workspace not found")
        try:
            scoped_role = PlatformRole(role_name)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="invalid workspace role") from exc
        scoped = Principal(principal.user_id, scoped_role, principal.session_id, principal.email)
        try:
            require_permission(scoped, permission)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail="insufficient permissions") from exc
        request.state.workspace_role = scoped_role
        return scoped
    try:
        require_permission(principal, permission)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    return principal


def authorize_endpoint(request: Request, permission: Permission = Permission.WORKSPACE_READ) -> Principal:
    principal = current_principal(request)
    try:
        require_permission(principal, permission)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    return principal


def extract_workspace_id(path: str) -> UUID | None:
    match = re.search(r"/api/workspaces/([0-9a-fA-F-]{36})(?:/|$)", path)
    if match is None:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


class RateLimiter:
    def __init__(self, limit: int = 120, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        events = [stamp for stamp in self._events.get(key, []) if stamp > cutoff]
        if len(events) >= self.limit:
            self._events[key] = events
            return False
        events.append(now)
        self._events[key] = events
        return True


class SecurityMiddleware:
    """Production API authentication, tenant authorization, rate limiting and headers."""

    def __init__(self, app: Any, rate_limiter: RateLimiter | None = None) -> None:
        self.app = app
        self.rate_limiter = rate_limiter or RateLimiter()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path.startswith("/api/"):
            client = scope.get("client")
            client_ip = client[0] if client else "unknown"
            if not self.rate_limiter.allow(client_ip):
                await self._json(send, 429, b'{"detail":"rate limit exceeded"}', [])
                return
            request = Request(scope, receive=receive)
            try:
                principal = current_principal(request)
                scope.setdefault("state", {})["principal"] = principal
                workspace_id = extract_workspace_id(path)
                if workspace_id is not None:
                    permission = Permission.WORKSPACE_WRITE if method in {"POST", "PUT", "PATCH", "DELETE"} else Permission.WORKSPACE_READ
                    require_workspace_membership(request, workspace_id, permission)
            except HTTPException as exc:
                response_headers = [(b"www-authenticate", b"Bearer")] if exc.status_code == 401 else []
                body = json.dumps({"detail": exc.detail}, separators=(",", ":")).encode()
                await self._json(send, exc.status_code, body, response_headers)
                return

        async def secure_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend([(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store")])
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, secure_send)

    @staticmethod
    async def _json(send: Any, status_code: int, body: bytes, headers: list[tuple[bytes, bytes]]) -> None:
        base_headers = [(b"content-type", b"application/json"), *headers]
        await send({"type": "http.response.start", "status": status_code, "headers": base_headers})
        await send({"type": "http.response.body", "body": body})


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    workflow_id: str
    artifact_id: str
    risk_assessment_id: str
    requested_by: str
    decision: str
    decided_by: str | None = None
    rationale: str | None = None
    required_reviewers: int = 1
    workspace_id: str | None = None
    strategy_version_id: str | None = None
    artifact_digest: str | None = None
    risk_assessment_digest: str | None = None


class ApprovalService:
    """Compatibility approval service with explicit independent human decisioning."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def request(self, approval_id: str, workflow_id: str, artifact_id: str, required_reviewers: int, risk_assessment_id: str, principal: Principal) -> ApprovalRecord:
        require_permission(principal, Permission.APPROVE)
        if required_reviewers < 1:
            raise ValueError("required reviewers must be at least one")
        if approval_id in self._records:
            raise ValueError("approval already exists")
        record = ApprovalRecord(approval_id, workflow_id, artifact_id, risk_assessment_id, principal.user_id, "pending", None, None, required_reviewers)
        self._records[approval_id] = record
        return record

    def decide(self, approval_id: str, principal: Principal, decision: str, rationale: str) -> ApprovalRecord:
        require_permission(principal, Permission.APPROVE)
        record = self._records.get(approval_id)
        if record is None:
            raise KeyError("approval not found")
        if record.decision != "pending":
            raise ValueError("approval already decided")
        if principal.user_id == record.requested_by:
            raise AuthorizationError("requester cannot approve their own request")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not rationale.strip():
            raise ValueError("rationale is required")
        decided = ApprovalRecord(record.approval_id, record.workflow_id, record.artifact_id, record.risk_assessment_id, record.requested_by, decision, principal.user_id, rationale.strip(), record.required_reviewers, record.workspace_id, record.strategy_version_id, record.artifact_digest, record.risk_assessment_digest)
        self._records[approval_id] = decided
        return decided

    def get(self, approval_id: str) -> ApprovalRecord:
        return self._records[approval_id]

    def submit(self, artifact_id: str, principal: Principal, decision: str) -> ApprovalRecord:
        require_permission(principal, Permission.APPROVE)
        approval_id = f"approval-{len(self._records) + 1}"
        record = ApprovalRecord(approval_id, "", artifact_id, "", principal.user_id, decision, principal.user_id, "legacy submission", 1)
        self._records[approval_id] = record
        return record

    def list(self) -> list[ApprovalRecord]:
        return list(self._records.values())
