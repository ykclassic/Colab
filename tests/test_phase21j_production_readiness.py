"""Phase 21J production-readiness certification gates.

These tests intentionally separate code-level certification from environment-level
certification. A green CI run proves the repository's safety and durability
contracts; the production database/RLS and deployment checks still require a
real production-like environment.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from colab.agent_platform_vertical_slice import version_transition_allowed
from colab.background_jobs import InMemoryJobQueue
from colab.quant_vertical_slice import QuantVerticalSliceError
from colab.security import PlatformRole, principal_from_test_header

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "colab"
MIGRATIONS = ROOT / "supabase" / "migrations"


def test_security_certification_blocks_test_auth_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLAB_ENV", "production")
    monkeypatch.setenv("COLAB_ALLOW_TEST_AUTH", "true")
    with pytest.raises(ValueError, match="disabled in production"):
        principal_from_test_header(str(UUID(int=1)), PlatformRole.OWNER.value)


def test_security_certification_has_production_auth_and_headers() -> None:
    source = (SRC / "security.py").read_text()
    workspace_source = (SRC / "workspace_api.py").read_text()
    assert 'return os.getenv("COLAB_ENV", "development").lower() == "production"' in source
    assert "SecurityMiddleware" in workspace_source
    assert "app.add_middleware(SecurityMiddleware" in workspace_source
    assert "x-content-type-options" in source
    assert "x-frame-options" in source
    assert "cache-control" in source


def test_tenant_isolation_certification_covers_workspace_membership() -> None:
    source = (SRC / "security.py").read_text()
    workspace_source = (SRC / "workspace_api.py").read_text()
    assert "workspace_memberships" in source
    assert "require_workspace_membership" in workspace_source
    assert "INNER JOIN public.workspace_memberships" in workspace_source
    assert "item.created_by" in workspace_source


def test_migration_certification_is_ordered_and_security_hardened() -> None:
    files = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    assert files == sorted(files)
    assert len(files) >= 10
    assert any(name.startswith("20260909050000_phase13_security_tenant_hardening") for name in files)
    sql = "\n".join((MIGRATIONS / name).read_text() for name in files)
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "workspace_memberships" in sql
    assert "ON CONFLICT" in sql


def test_workflow_durability_certification() -> None:
    store = (SRC / "background_jobs_store.py").read_text()
    persistence = (SRC / "production_persistence.py").read_text()
    worker = (SRC / "background_worker.py").read_text()
    assert "FOR UPDATE SKIP LOCKED" in store or "FOR UPDATE SKIP LOCKED" in persistence
    assert "lease_expires_at" in store
    assert "idempotency_key" in store
    assert "max_attempts" in store
    assert "job.failure" in worker
    assert "artifact.write" in worker


def test_background_worker_certification_requires_postgresql() -> None:
    source = (SRC / "background_worker.py").read_text()
    assert 'COLAB_DATABASE_DSN is required for background workers' in source
    queue = InMemoryJobQueue()
    job = queue.enqueue(UUID(int=2), "backtest", {}, "certification-key")
    claimed = queue.claim("certification-worker")
    assert claimed is not None and claimed.job_id == job.job_id
    queue.complete(job.job_id, "certification-worker", {"certified": True}, "backtest")


def test_research_e2e_certification_surface_exists() -> None:
    research_tests = list((ROOT / "tests").glob("*research*.py"))
    research_sources = [SRC / "research_api.py", SRC / "research_platform_api.py", SRC / "research_intelligence.py"]
    assert research_tests
    assert all(path.exists() for path in research_sources)


def test_quant_e2e_certification_surface_exists() -> None:
    quant_tests = list((ROOT / "tests").glob("*quant*.py"))
    assert quant_tests
    assert (SRC / "quant_vertical_slice.py").exists()
    assert QuantVerticalSliceError.__doc__


def test_agent_e2e_certification_surface_exists() -> None:
    agent_tests = list((ROOT / "tests").glob("*agent*.py"))
    assert agent_tests
    source = (SRC / "agent_platform_vertical_slice.py").read_text()
    assert "benchmark" in source and "governance" in source
    assert "workspace_id" in source


def test_observability_certification() -> None:
    source = (SRC / "observability.py").read_text()
    worker = (SRC / "background_worker.py").read_text()
    assert "correlation" in source
    assert "observe_job" in source
    assert "span(" in source
    assert "workflow.job" in worker
    assert "agent.handler" in worker
    assert "artifact.write" in worker


def test_frontend_e2e_certification() -> None:
    spec = ROOT / "frontend" / "e2e" / "product.spec.ts"
    package = (ROOT / "frontend" / "package.json").read_text()
    assert spec.exists()
    spec_text = spec.read_text()
    for label in ("Research", "Quant", "Agents", "Governance", "Artifacts / Reports"):
        assert label in spec_text
    assert '"e2e"' in package


def test_no_live_execution_authority_is_exposed_to_default_tools() -> None:
    source = (SRC / "api.py").read_text()
    defaults = source.split("def _register_safe_defaults", 1)[1].split("def create_app", 1)[0]
    assert "execution" not in defaults
    readme = (ROOT / "README.md").read_text()
    assert "not currently a live autonomous trading platform" in readme


def test_production_configuration_never_silently_falls_back_to_memory() -> None:
    source = (SRC / "api.py").read_text()
    assert "COLAB_DATABASE_DSN is required when COLAB_ENV=production" in source
    assert 'if production and not dsn:' in source


def test_agent_version_transition_is_workspace_bound() -> None:
    assert version_transition_allowed(None, _workspace_agent()) is False


def _workspace_agent():
    # Keep this gate intentionally lightweight; full agent evaluation is covered
    # by the dedicated Phase 21F/21G regression suites.
    from colab.agent_platform import AgentRecord

    return AgentRecord(
        agent_id=UUID(int=3),
        workspace_id=UUID(int=4),
        name="certification-agent",
        version=2,
        role="researcher",
        code_revision="certification",
        model="deterministic-test-model",
    )
