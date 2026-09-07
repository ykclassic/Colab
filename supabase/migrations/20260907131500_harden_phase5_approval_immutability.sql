-- Approval decisions may change only the decision, rationale, decider and timestamp.
CREATE OR REPLACE FUNCTION public.enforce_approval_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF OLD.decision <> 'pending' THEN
        RAISE EXCEPTION 'approval request is already decided';
    END IF;
    IF NEW.approval_id <> OLD.approval_id
       OR NEW.workspace_id <> OLD.workspace_id
       OR NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
       OR NEW.artifact_id <> OLD.artifact_id
       OR NEW.artifact_version <> OLD.artifact_version
       OR NEW.risk_assessment_id IS DISTINCT FROM OLD.risk_assessment_id
       OR NEW.requested_by <> OLD.requested_by
       OR NEW.requested_at <> OLD.requested_at THEN
        RAISE EXCEPTION 'approval request identity is immutable';
    END IF;
    IF NEW.decision NOT IN ('approve','reject') THEN
        RAISE EXCEPTION 'approval transition must approve or reject';
    END IF;
    IF NEW.decided_by IS NULL OR NEW.decided_at IS NULL THEN
        RAISE EXCEPTION 'decider and decision timestamp are required';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.enforce_approval_transition() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS approval_requests_transition ON public.approval_requests;
CREATE TRIGGER approval_requests_transition
BEFORE UPDATE ON public.approval_requests
FOR EACH ROW
EXECUTE FUNCTION public.enforce_approval_transition();

ALTER TABLE public.approval_requests
    ADD CONSTRAINT approval_decision_timestamp_check
    CHECK ((decision = 'pending' AND decided_at IS NULL) OR (decision <> 'pending' AND decided_at IS NOT NULL));
