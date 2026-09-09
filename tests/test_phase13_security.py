from __future__ import annotations

import time
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from colab.security import (
    Permission,
    PlatformRole,
    Principal,
    RateLimiter,
    SecurityMiddleware,
    auth_required,
    authenticate_bearer,
    current_principal,
    principal_from_test_header,
    require_permission,
    require_workspace_membership,
)


def _token(secret: str, user_id: UUID, role: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "aud": "authenticated", "iss": "https://example.supabase.co/auth/v1", "iat": now, "exp": now + 300, "app_metadata": {"colab_role": role}}, secret, algorithm="HS256")


def test_role_matrix_keeps_risk_and_approval_independent() -> None:
    risk = Principal("risk", PlatformRole.RISK)
    reviewer = Principal("reviewer", PlatformRole.REVIEWER)
    assert risk.can(Permission.RISK_ASSESS)
    assert not risk.can(Permission.APPROVE)
    assert reviewer.can(Permission.APPROVE)
    with pytest.raises(PermissionError):
        require_permission(risk, Permission.APPROVE)


def test_supabase_jwt_validates_issuer_audience_and_app_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("COLAB_JWT_SECRET", secret)
    principal = authenticate_bearer(_token(secret, UUID("00000000-0000-0000-0000-000000000001"), "reviewer"))
    assert principal.user_id == "00000000-0000-0000-0000-000000000001"
    assert principal.role is PlatformRole.REVIEWER


def test_supabase_jwt_rejects_bad_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("COLAB_JWT_SECRET", "test-secret")
    token = jwt.encode({"sub": str(uuid4()), "aud": "wrong", "iss": "https://example.supabase.co/auth/v1", "iat": int(time.time()), "exp": int(time.time()) + 300, "app_metadata": {"colab_role": "reviewer"}}, "test-secret", algorithm="HS256")
    with pytest.raises(ValueError, match="invalid or expired"):
        authenticate_bearer(token)


def test_authentication_edge_cases_and_test_auth_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("COLAB_JWT_SECRET", raising=False)
    with pytest.raises(ValueError, match="empty bearer"):
        authenticate_bearer("")
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        authenticate_bearer("not-a-jwt")

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("COLAB_JWT_SECRET", "test-secret")
    with pytest.raises(ValueError, match="unsupported local JWT algorithm"):
        token = jwt.encode({"sub": str(uuid4()), "aud": "authenticated", "iss": "https://example.supabase.co/auth/v1", "iat": int(time.time()), "exp": int(time.time()) + 300, "app_metadata": {"colab_role": "reviewer"}}, "test-secret", algorithm="HS384")
        monkeypatch.delenv("COLAB_JWT_SECRET")
        authenticate_bearer(token)

    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "false")
    with pytest.raises(ValueError, match="disabled"):
        principal_from_test_header("tester", "reviewer")
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")
    with pytest.raises(ValueError, match="invalid test role"):
        principal_from_test_header("tester", "invalid")
    assert principal_from_test_header("tester", "reviewer").role is PlatformRole.REVIEWER


def test_auth_mode_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLAB_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("COLAB_ENV", raising=False)
    assert not auth_required()
    monkeypatch.setenv("COLAB_ENV", "production")
    assert auth_required()
    monkeypatch.setenv("COLAB_REQUIRE_AUTH", "false")
    assert not auth_required()
    monkeypatch.setenv("COLAB_REQUIRE_AUTH", "TRUE")
    assert auth_required()


def test_security_principal_and_membership_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")
    app = FastAPI()
    app.state.services = type("Services", (), {"database": None})()

    @app.get("/api/test")
    def test_route(request: Request) -> dict[str, str]:
        principal = current_principal(request)
        return {"user_id": principal.user_id, "role": principal.role.value}

    @app.get("/api/membership/{workspace_id}")
    def membership_route(request: Request, workspace_id: UUID) -> dict[str, bool]:
        request.state.principal = Principal("researcher", PlatformRole.RESEARCHER)
        require_workspace_membership(request, workspace_id, Permission.APPROVE)
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/api/test", headers={"X-Test-User": "tester", "X-Test-Role": "reviewer"})
    assert response.status_code == 200
    assert response.json() == {"user_id": "tester", "role": "reviewer"}
    assert client.get(f"/api/membership/{uuid4()}").status_code == 403


def test_security_middleware_rate_limit_and_headers() -> None:
    app = FastAPI()
    app.add_middleware(SecurityMiddleware, rate_limiter=RateLimiter(1))

    @app.get("/api/open")
    def open_route() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    first = client.get("/api/open")
    second = client.get("/api/open")
    assert first.status_code == 200
    assert first.headers["x-content-type-options"] == "nosniff"
    assert second.status_code == 429


def test_security_middleware_scopes_workspace_requests() -> None:
    app = FastAPI()
    app.state.services = type("Services", (), {"database": None})()
    app.add_middleware(SecurityMiddleware)

    @app.get("/api/workspaces/{workspace_id}")
    def workspace(request: Request) -> dict[str, bool]:
        assert isinstance(request.state.principal, Principal)
        return {"ok": True}

    client = TestClient(app)
    assert client.get(f"/api/workspaces/{uuid4()}").status_code == 200


def test_security_middleware_protects_api_when_auth_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_ENV", "production")
    monkeypatch.delenv("COLAB_REQUIRE_AUTH", raising=False)
    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.get("/api/protected")
    def protected() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/api/protected").status_code == 401


def test_workspace_authorization_denies_role_without_permission() -> None:
    app = FastAPI()
    app.state.services = type("Services", (), {"database": None})()

    @app.get("/api/workspaces/{workspace_id}")
    def workspace(request: Request) -> dict[str, bool]:
        request.state.principal = Principal("researcher", PlatformRole.RESEARCHER)
        require_workspace_membership(request, UUID(request.path_params["workspace_id"]), Permission.APPROVE)
        return {"ok": True}

    client = TestClient(app)
    assert client.get(f"/api/workspaces/{uuid4()}").status_code == 403
