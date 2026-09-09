"""Phase 13 identity, authorization, tenant isolation, and governance security."""
from __future__ import annotations

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
    PlatformRole.PROJECT_MANAGER: frozenset(
        {
            Permission.WORKSPACE_READ,
            Permission.WORKSPACE_WRITE,
            Permission.AUDIT_READ,
            Permission.APPROVE,
            Permission.INTEGRATION_READ,
        }
    ),
    PlatformRole.RESEARCHER: frozenset({Permission.WORKSPACE_READ, Permission.RESEARCH_WRITE}),
    PlatformRole.STRATEGY: frozenset({Permission.WORKSPACE_READ, Permission.STRATEGY_WRITE}),
    PlatformRole.RISK: frozenset({Permission.WORKSPACE_READ, Permission.RISK_ASSESS, Permission.AUDIT_READ}),
    PlatformRole.ENGINEER: frozenset({Permission.WORKSPACE_READ, Permission.IMPLEMENT, Permission.VALIDATE}),
    PlatformRole.REVIEWER: frozenset(
        {Permission.WORKSPACE_READ, Permission.APPROVE, Permission.AUDIT_READ, Permission.INTEGRATION_READ}
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
            claims: dict[str, Any] = jwt.decode(
                token,
                secret,
                algorithms=[algorithm],
                audience=audience,
                issuer=issuer,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
        else:
            if algorithm not in {"RS256", "ES256", "EdDSA"}:
                raise AuthenticationError("unsupported Supabase JWT algorithm")
            key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=audience,
                issuer=issuer,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
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
    return Principal(
        user_id=subject,
        role=role,
        session_id=str(claims["session_id"]) if claims.get("session_id") else None,
        email=str(claims["email"]) if claims.get("email") else None,
    )


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
    if os.getenv("COLAB_ALLOW_TEST_AUTH", "false").lower() == "true":
        test_user, test_role = request.headers.get("X-Test-User"), request.headers.get("X-Test-Role")
        if test_user and test_role:
            try:
                principal = principal_from_test_header(test_user, test_role)
            except AuthenticationError as exc:
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
        cur.execute(
            "SELECT role FROM public.workspace_memberships WHERE workspace_id=%s AND user_id=%s",
            (workspace_id, user_uuid),
        )
        row = cur.fetchone()
    return None if row is None else str(row[0])


def require_workspace_membership(
    request: Request,
    workspace_id: UUID,
    permission: Permission = Permission.WORKSPACE_READ,
) -> Principal:
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
    require_permission(principal, permission)
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
    if not match:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


class RateLimiter:
    """Process-local safety net; edge rate limiting remains recommended in production."""

    def __init__(self, requests_per_minute: int = 120) -> None:
        self.requests_per_minute = max(1, requests_per_minute)
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = [stamp for stamp in self._hits.get(key, []) if now - stamp < 60]
        if len(hits) >= self.requests_per_minute:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


class SecurityMiddleware:
    """Production API authentication, tenant checks, rate limiting, and headers."""

    def __init__(self, app: Any, requests_per_minute: int = 120) -> None:
        self.app = app
        self.limiter = RateLimiter(requests_per_minute)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path.startswith("/api/") and auth_required():
            client = scope.get("client")
            if not self.limiter.allow(str(client[0]) if client else "unknown"):
                await self._json(send, 429, b'{"detail":"rate limit exceeded"}', [(b"retry-after", b"60")])
                return
            request = Request(scope, receive=receive)
            try:
                principal = current_principal(request)
                scope.setdefault("state", {})["principal"] = principal
                workspace_id = extract_workspace_id(path)
                if workspace_id is not None:
                    permission = (
                        Permission.WORKSPACE_WRITE
                        if scope.get("method", "GET").upper() in {"POST", "PUT", "PATCH", "DELETE"}
                        else Permission.WORKSPACE_READ
                    )
                    require_workspace_membership(request, workspace_id, permission)
            except HTTPException as exc:
                headers = [(b"www-authenticate", b"Bearer")] if exc.status_code == 401 else []
                body = f'{{"detail":"{str(exc.detail)}"}}'.encode()
                await self._json(send, exc.status_code, body, headers)
                return

        async def secure_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, secure_send)

    @staticmethod
    async def _json(send: Any, code: int, body: bytes, extra: list[tuple[bytes, bytes]]) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    *extra,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


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
    """In-memory governance boundary retained for deterministic unit tests."""

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
            approval_id,
            workflow_id,
            artifact_id,
            artifact_version,
            risk_assessment_id,
            requested_by.user_id,
            "pending",
        )
        self._requests[approval_id] = record
        return record

    def decide(self, approval_id: str, principal: Principal, decision: str, rationale: str) -> ApprovalRecord:
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
            current.approval_id,
            current.workflow_id,
            current.artifact_id,
            current.artifact_version,
            current.risk_assessment_id,
            current.requested_by,
            decision,
            principal.user_id,
            rationale.strip(),
        )
        self._requests[approval_id] = updated
        return updated

    def get(self, approval_id: str) -> ApprovalRecord:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(approval_id) from exc


def principal_from_test_header(user_id: str, role: str) -> Principal:
    if os.getenv("COLAB_ALLOW_TEST_AUTH", "false").lower() != "true":
        raise AuthenticationError("test authentication is disabled")
    try:
        parsed_role = PlatformRole(role)
    except ValueError as exc:
        raise AuthenticationError("invalid test role") from exc
    return Principal(user_id=user_id, role=parsed_role)
