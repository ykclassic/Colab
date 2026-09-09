-- Phase 16: Durable Governance
-- Append-only persistence for approvals, strategy versions, gate results,
-- readiness reports, and promotion decisions.

CREATE TABLE IF NOT EXISTS public.governance_strategy_versions (
    version_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    name text NOT NULL,
    version text NOT NULL,
    artifact_digest text NOT NULL,
    manifest_hash text NOT NULL,
    created_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (workspace_id, name, version)
);

CREATE TABLE IF NOT EXISTS public.governance_gate_results (
    gate_result_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    version_id uuid NOT NULL REFERENCES public.governance_strategy_versions(version_id) ON DELETE RESTRICT,
    gate text NOT NULL,
    passed boolean NOT NULL,
    score double precision NOT NULL CHECK (score >= 0 AND score <= 100),
    required boolean NOT NULL DEFAULT true,
    evidence text NOT NULL DEFAULT '',
    checked_at timestamptz NOT NULL,
    UNIQUE (version_id, gate, checked_at)
);

CREATE TABLE IF NOT EXISTS public.governance_readiness_reports (
    report_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    version_id uuid NOT NULL REFERENCES public.governance_strategy_versions(version_id) ON DELETE RESTRICT,
    score double precision NOT NULL CHECK (score >= 0 AND score <= 100),
    rating text NOT NULL,
    dimensions jsonb NOT NULL,
    blocking_gates jsonb NOT NULL,
    generated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS public.governance_promotion_decisions (
    decision_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    version_id uuid NOT NULL REFERENCES public.governance_strategy_versions(version_id) ON DELETE RESTRICT,
    from_stage text NOT NULL,
    to_stage text NOT NULL,
    approved boolean NOT NULL,
    readiness_score double precision NOT NULL CHECK (readiness_score >= 0 AND readiness_score <= 100),
    gates jsonb NOT NULL,
    reasons jsonb NOT NULL,
    decided_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS public.governance_approvals (
    approval_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    workflow_id uuid,
    artifact_id uuid,
    strategy_version_id uuid NOT NULL REFERENCES public.governance_strategy_versions(version_id) ON DELETE RESTRICT,
    artifact_digest text NOT NULL,
    risk_assessment_id uuid,
    risk_assessment_digest text NOT NULL,
    requested_by uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('pending','approve','reject')),
    decided_by uuid,
    rationale text,
    required_reviewers integer NOT NULL CHECK (required_reviewers >= 1),
    requested_at timestamptz NOT NULL,
    decided_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.governance_approval_invalidations (
    invalidation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id uuid NOT NULL REFERENCES public.governance_approvals(approval_id) ON DELETE RESTRICT,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    reason text NOT NULL,
    invalidated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_strategy_versions_workspace_idx
    ON public.governance_strategy_versions(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS governance_gate_results_version_idx
    ON public.governance_gate_results(version_id, checked_at);
CREATE INDEX IF NOT EXISTS governance_readiness_reports_version_idx
    ON public.governance_readiness_reports(version_id, generated_at);
CREATE INDEX IF NOT EXISTS governance_promotion_decisions_workspace_idx
    ON public.governance_promotion_decisions(workspace_id, decided_at);
CREATE INDEX IF NOT EXISTS governance_approvals_workspace_idx
    ON public.governance_approvals(workspace_id, requested_at);
CREATE INDEX IF NOT EXISTS governance_approval_invalidations_approval_idx
    ON public.governance_approval_invalidations(approval_id, invalidated_at);

ALTER TABLE public.governance_strategy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.governance_gate_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.governance_readiness_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.governance_promotion_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.governance_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.governance_approval_invalidations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS governance_strategy_versions_workspace ON public.governance_strategy_versions;
CREATE POLICY governance_strategy_versions_workspace ON public.governance_strategy_versions
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS governance_gate_results_workspace ON public.governance_gate_results;
CREATE POLICY governance_gate_results_workspace ON public.governance_gate_results
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS governance_readiness_reports_workspace ON public.governance_readiness_reports;
CREATE POLICY governance_readiness_reports_workspace ON public.governance_readiness_reports
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS governance_promotion_decisions_workspace ON public.governance_promotion_decisions;
CREATE POLICY governance_promotion_decisions_workspace ON public.governance_promotion_decisions
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS governance_approvals_workspace ON public.governance_approvals;
CREATE POLICY governance_approvals_workspace ON public.governance_approvals
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS governance_approval_invalidations_workspace ON public.governance_approval_invalidations;
CREATE POLICY governance_approval_invalidations_workspace ON public.governance_approval_invalidations
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));

CREATE OR REPLACE FUNCTION public.prevent_governance_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'durable governance records are append-only';
END;
$$;

DROP TRIGGER IF EXISTS governance_strategy_versions_immutable ON public.governance_strategy_versions;
CREATE TRIGGER governance_strategy_versions_immutable BEFORE UPDATE OR DELETE ON public.governance_strategy_versions
FOR EACH ROW EXECUTE FUNCTION public.prevent_governance_mutation();
DROP TRIGGER IF EXISTS governance_gate_results_immutable ON public.governance_gate_results;
CREATE TRIGGER governance_gate_results_immutable BEFORE UPDATE OR DELETE ON public.governance_gate_results
FOR EACH ROW EXECUTE FUNCTION public.prevent_governance_mutation();
DROP TRIGGER IF EXISTS governance_readiness_reports_immutable ON public.governance_readiness_reports;
CREATE TRIGGER governance_readiness_reports_immutable BEFORE UPDATE OR DELETE ON public.governance_readiness_reports
FOR EACH ROW EXECUTE FUNCTION public.prevent_governance_mutation();
DROP TRIGGER IF EXISTS governance_promotion_decisions_immutable ON public.governance_promotion_decisions;
CREATE TRIGGER governance_promotion_decisions_immutable BEFORE UPDATE OR DELETE ON public.governance_promotion_decisions
FOR EACH ROW EXECUTE FUNCTION public.prevent_governance_mutation();
DROP TRIGGER IF EXISTS governance_approvals_immutable ON public.governance_approvals;
CREATE TRIGGER governance_approvals_immutable BEFORE UPDATE OR DELETE ON public.governance_approvals
FOR EACH ROW EXECUTE FUNCTION public.prevent_governance_mutation();
DROP TRIGGER IF EXISTS governance_approval_invalidations_immutable ON public.governance_approval_invalidations;
CREATE TRIGGER governance_approval_invalidations_immutable BEFORE UPDATE OR DELETE ON public.governance_approval_invalidations
FOR EACH ROW EXECUTE FUNCTION public.prevent_governance_mutation();

-- A changed governed artifact can never silently retain an approval. The
-- invalidation ledger records the fact without mutating the original approval.
CREATE OR REPLACE FUNCTION public.invalidate_governance_approvals_for_artifact() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
        INSERT INTO public.governance_approval_invalidations(approval_id, workspace_id, reason)
        SELECT approval_id, workspace_id, 'governed artifact content changed'
        FROM public.governance_approvals
        WHERE artifact_id = NEW.artifact_id AND artifact_digest = OLD.content_hash
          AND NOT EXISTS (
              SELECT 1 FROM public.governance_approval_invalidations i
              WHERE i.approval_id = governance_approvals.approval_id
          );
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO public.governance_approval_invalidations(approval_id, workspace_id, reason)
        SELECT approval_id, workspace_id, 'governed artifact was deleted'
        FROM public.governance_approvals
        WHERE artifact_id = OLD.artifact_id
          AND NOT EXISTS (
              SELECT 1 FROM public.governance_approval_invalidations i
              WHERE i.approval_id = governance_approvals.approval_id
          );
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS governance_artifact_change_invalidation ON public.product_artifacts;
CREATE TRIGGER governance_artifact_change_invalidation
AFTER UPDATE OF content_hash OR DELETE ON public.product_artifacts
FOR EACH ROW EXECUTE FUNCTION public.invalidate_governance_approvals_for_artifact();
