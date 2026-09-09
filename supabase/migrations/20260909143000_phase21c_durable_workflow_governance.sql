-- Phase 21C: durable workflow replay and governance verification.
-- This migration adds an append-only governance event ledger and prevents
-- mutation/deletion of workflow integrity records and audit history.

CREATE TABLE IF NOT EXISTS public.governance_approval_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id uuid NOT NULL REFERENCES public.governance_approvals(approval_id) ON DELETE RESTRICT,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    sequence_no bigint NOT NULL CHECK (sequence_no >= 1),
    from_state text,
    to_state text NOT NULL CHECK (to_state IN ('draft','submitted','risk_review','risk_approved','human_review','approved','promoted','rejected','invalidated','superseded','expired')),
    actor uuid NOT NULL,
    governed_input_digest text NOT NULL,
    previous_event_hash text,
    event_hash text NOT NULL CHECK (length(event_hash) = 64),
    reason text NOT NULL DEFAULT '',
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (approval_id, sequence_no),
    UNIQUE (approval_id, event_hash)
);

ALTER TABLE public.governance_approval_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS governance_approval_events_workspace ON public.governance_approval_events;
CREATE POLICY governance_approval_events_workspace ON public.governance_approval_events
    FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));

REVOKE ALL ON public.governance_approval_events FROM anon;
GRANT SELECT ON public.governance_approval_events TO authenticated;

CREATE OR REPLACE FUNCTION public.validate_governance_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous record;
    allowed boolean := false;
BEGIN
    SELECT sequence_no, to_state, event_hash, workspace_id
      INTO previous
      FROM public.governance_approval_events
     WHERE approval_id = NEW.approval_id
     ORDER BY sequence_no DESC
     LIMIT 1;

    IF previous IS NULL THEN
        IF NEW.sequence_no <> 1 OR NEW.from_state IS NOT NULL OR NEW.to_state <> 'draft' THEN
            RAISE EXCEPTION 'governance chain must start with DRAFT at sequence 1';
        END IF;
    ELSE
        IF NEW.sequence_no <> previous.sequence_no + 1 THEN
            RAISE EXCEPTION 'governance sequence must be contiguous';
        END IF;
        IF NEW.from_state IS DISTINCT FROM previous.to_state THEN
            RAISE EXCEPTION 'governance from_state does not match prior state';
        END IF;
        IF NEW.previous_event_hash IS DISTINCT FROM previous.event_hash THEN
            RAISE EXCEPTION 'governance event hash chain is broken';
        END IF;
        IF NEW.workspace_id IS DISTINCT FROM previous.workspace_id THEN
            RAISE EXCEPTION 'governance workspace binding cannot change';
        END IF;

        allowed :=
            (previous.to_state = 'draft' AND NEW.to_state IN ('submitted','rejected','superseded')) OR
            (previous.to_state = 'submitted' AND NEW.to_state IN ('risk_review','rejected','superseded','expired')) OR
            (previous.to_state = 'risk_review' AND NEW.to_state IN ('risk_approved','rejected','superseded')) OR
            (previous.to_state = 'risk_approved' AND NEW.to_state IN ('human_review','rejected','invalidated','superseded','expired')) OR
            (previous.to_state = 'human_review' AND NEW.to_state IN ('approved','rejected','invalidated','superseded','expired')) OR
            (previous.to_state = 'approved' AND NEW.to_state IN ('promoted','invalidated','superseded','expired'));
        IF NOT allowed THEN
            RAISE EXCEPTION 'invalid governance transition: % -> %', previous.to_state, NEW.to_state;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS governance_transition_validation ON public.governance_approval_events;
CREATE TRIGGER governance_transition_validation
BEFORE INSERT ON public.governance_approval_events
FOR EACH ROW EXECUTE FUNCTION public.validate_governance_transition();

CREATE OR REPLACE FUNCTION public.prevent_phase21c_immutable_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Phase 21C integrity records are append-only';
END;
$$;

DROP TRIGGER IF EXISTS governance_approval_events_immutable ON public.governance_approval_events;
CREATE TRIGGER governance_approval_events_immutable
BEFORE UPDATE OR DELETE ON public.governance_approval_events
FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21c_immutable_mutation();

DROP TRIGGER IF EXISTS workflow_events_immutable_phase21c ON public.workflow_events;
CREATE TRIGGER workflow_events_immutable_phase21c
BEFORE UPDATE OR DELETE ON public.workflow_events
FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21c_immutable_mutation();

DROP TRIGGER IF EXISTS workflow_checkpoints_immutable_phase21c ON public.workflow_checkpoints;
CREATE TRIGGER workflow_checkpoints_immutable_phase21c
BEFORE UPDATE OR DELETE ON public.workflow_checkpoints
FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21c_immutable_mutation();

DROP TRIGGER IF EXISTS audit_events_immutable_phase21c ON public.audit_events;
CREATE TRIGGER audit_events_immutable_phase21c
BEFORE UPDATE OR DELETE ON public.audit_events
FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21c_immutable_mutation();

-- Any change to a governed risk assessment invalidates approvals bound to it.
CREATE OR REPLACE FUNCTION public.invalidate_governance_approvals_for_risk_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.governance_approval_invalidations(approval_id, workspace_id, reason)
    SELECT approval_id, workspace_id,
           CASE WHEN TG_OP = 'DELETE' THEN 'governed risk assessment was deleted'
                ELSE 'governed risk assessment changed' END
      FROM public.governance_approvals
     WHERE risk_assessment_id = COALESCE(NEW.assessment_id, OLD.assessment_id)
       AND NOT EXISTS (
           SELECT 1 FROM public.governance_approval_invalidations i
            WHERE i.approval_id = governance_approvals.approval_id
       );
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS governance_risk_change_invalidation ON public.risk_assessments;
CREATE TRIGGER governance_risk_change_invalidation
AFTER UPDATE OR DELETE ON public.risk_assessments
FOR EACH ROW EXECUTE FUNCTION public.invalidate_governance_approvals_for_risk_change();

-- Product artifact changes are already digest-aware in Phase 16; retain that
-- trigger and add a generic workflow-artifact invalidation path where the
-- workflow artifact is directly bound to an approval.
CREATE OR REPLACE FUNCTION public.invalidate_governance_approvals_for_workflow_artifact() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.governance_approval_invalidations(approval_id, workspace_id, reason)
    SELECT approval_id, workspace_id,
           CASE WHEN TG_OP = 'DELETE' THEN 'governed workflow artifact was deleted'
                ELSE 'governed workflow artifact changed' END
      FROM public.governance_approvals
     WHERE artifact_id = COALESCE(NEW.artifact_id, OLD.artifact_id)
       AND NOT EXISTS (
           SELECT 1 FROM public.governance_approval_invalidations i
            WHERE i.approval_id = governance_approvals.approval_id
       );
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS governance_workflow_artifact_invalidation ON public.artifacts;
CREATE TRIGGER governance_workflow_artifact_invalidation
AFTER UPDATE OR DELETE ON public.artifacts
FOR EACH ROW EXECUTE FUNCTION public.invalidate_governance_approvals_for_workflow_artifact();
