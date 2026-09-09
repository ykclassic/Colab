"""Phase 21B static verification for database tenancy and migration integrity."""
from __future__ import annotations

import re

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
PHASE21B = MIGRATIONS / "20260909140000_phase21b_database_tenant_integrity.sql"
PHASE19 = MIGRATIONS / "20260909130000_phase19_agent_platform.sql"


def _migration_versions() -> list[tuple[int, str]]:
    files = sorted(MIGRATIONS.glob("*.sql"))
    versions: list[tuple[int, str]] = []
    for path in files:
        match = re.match(r"^(\d{14})_", path.name)
        assert match is not None, f"migration is missing a 14-digit version prefix: {path.name}"
        versions.append((int(match.group(1)), path.name))
    return versions


def test_migration_versions_are_unique_and_strictly_ordered() -> None:
    versions = _migration_versions()
    numeric = [version for version, _ in versions]
    assert numeric == sorted(numeric)
    assert len(numeric) == len(set(numeric)), "duplicate migration version detected"


def test_phase21b_enforces_workspace_identity_for_legacy_workflows() -> None:
    sql = PHASE21B.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS workspace_id uuid" in sql
    assert "SET workspace_id = candidates.workspace_id" in sql
    assert "workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id)" in sql


def test_phase21b_uses_non_recursive_membership_helper() -> None:
    sql = PHASE21B.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION public.is_workspace_member" in sql
    assert "SECURITY DEFINER" in sql
    assert "GRANT EXECUTE ON FUNCTION public.is_workspace_member(uuid) TO authenticated" in sql


def test_phase21b_covers_core_tenant_tables() -> None:
    sql = PHASE21B.read_text(encoding="utf-8")
    required = (
        "public.product_artifacts",
        "public.knowledge_documents",
        "public.research_documents",
        "public.research_chunks",
        "public.research_sources",
        "public.quant_strategies",
        "public.quant_experiments",
        "public.agents",
        "public.agent_evaluations",
        "public.agent_memory",
        "public.agent_costs",
        "public.workflow_execution_jobs",
        "public.workflow_operational_events",
    )
    for table in required:
        assert table in sql, f"Phase 21B does not cover {table}"


def test_phase21b_revokes_anonymous_tenant_data_access() -> None:
    sql = PHASE21B.read_text(encoding="utf-8")
    assert "FROM anon;" in sql
    assert "public.workflows" in sql
    assert "public.agent_costs" in sql


def test_phase21b_does_not_restore_anonymous_or_cross_tenant_access() -> None:
    sql = PHASE21B.read_text(encoding="utf-8")
    assert "TO anon" not in sql
    assert "public.is_workspace_member(workspace_id)" in sql


def test_phase19_uses_the_authoritative_product_workspace_table() -> None:
    sql = PHASE19.read_text(encoding="utf-8")
    assert "references public.product_workspaces(workspace_id)" in sql
    assert "references public.workspaces(id)" not in sql
