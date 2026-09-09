"""Static verification of Phase 21C database invariants.

The application CI environment does not provision a production Supabase
instance, so these checks validate migration structure. SQL execution must be
run against the target database before production rollout.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "20260909143000_phase21c_durable_workflow_governance.sql"


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_phase21c_migration_is_ordered_after_phase21b() -> None:
    assert MIGRATION.name.startswith("20260909143000_")
    versions = sorted(path.name for path in MIGRATION.parent.glob("*.sql"))
    assert versions.index(MIGRATION.name) > versions.index("20260909140000_phase21b_database_tenant_integrity.sql")
    assert re.match(r"^\d{14}_", MIGRATION.name)


def test_governance_event_ledger_is_workspace_bound_and_append_only() -> None:
    text = sql()
    assert "CREATE TABLE IF NOT EXISTS public.governance_approval_events" in text
    assert "workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id)" in text
    assert "UNIQUE (approval_id, sequence_no)" in text
    assert "governance_approval_events_immutable" in text
    assert "BEFORE UPDATE OR DELETE ON public.governance_approval_events" in text


def test_governance_state_machine_is_enforced_in_database() -> None:
    text = sql()
    for state in ("draft", "submitted", "risk_review", "risk_approved", "human_review", "approved", "promoted", "rejected", "invalidated", "superseded", "expired"):
        assert f"'{state}'" in text
    assert "governance chain must start with DRAFT" in text
    assert "governance sequence must be contiguous" in text
    assert "governance from_state does not match prior state" in text
    assert "invalid governance transition" in text


def test_workflow_replay_and_audit_records_are_immutable() -> None:
    text = sql()
    assert "workflow_events_immutable_phase21c" in text
    assert "workflow_checkpoints_immutable_phase21c" in text
    assert "audit_events_immutable_phase21c" in text
    assert "BEFORE UPDATE OR DELETE ON public.workflow_events" in text
    assert "BEFORE UPDATE OR DELETE ON public.workflow_checkpoints" in text
    assert "BEFORE UPDATE OR DELETE ON public.audit_events" in text


def test_governed_input_changes_create_invalidation_ledger_entries() -> None:
    text = sql()
    assert "invalidate_governance_approvals_for_risk_change" in text
    assert "governance_risk_change_invalidation" in text
    assert "governance_workflow_artifact_invalidation" in text
    assert "governance_approval_invalidations" in text
    assert "NOT EXISTS" in text
