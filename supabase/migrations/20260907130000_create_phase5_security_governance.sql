-- Phase 5: identity-aware tenancy, approvals, and security audit records.
-- Authorization is based on auth.uid() and app_metadata.colab_role; user_metadata is never used.

CREATE TABLE IF NOT EXISTS public.workspace_memberships (
    membership_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN (
        'owner','project_manager','quant_researcher','strategy_developer',
        'risk_compliance','software_engineer_qa','reviewer'
    )),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS workspace_memberships_user_idx
    ON public.workspace_memberships(user_id, workspace_id);
CREATE INDEX IF NOT EXISTS workspace_memberships_workspace_idx
    ON public.workspace_memberships(workspace_id, user_id);

ALTER TABLE public.product_workspaces
    ADD COLUMN IF NOT EXISTS created_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT;

CREATE TABLE IF NOT EXISTS public.approval_requests (
    approval_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    workflow_id uuid REFERENCES public.workflows(workflow_id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    artifact_version integer NOT NULL CHECK (artifact_version >= 1),
    risk_assessment_id uuid,
    requested_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    decided_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    decision text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','approve','reject')),
    rationale text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    CONSTRAINT approval_rationale_required CHECK (
        decision = 'pending' OR char_length(trim(coalesce(rationale, ''))) > 0
    ),
    CONSTRAINT approval_decider_required CHECK (
        decision = 'pending' OR decided_by IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS approval_requests_workspace_idx
    ON public.approval_requests(workspace_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS approval_requests_pending_idx
    ON public.approval_requests(workspace_id, decision) WHERE decision = 'pending';

CREATE TABLE IF NOT EXISTS public.security_audit_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES public.product_workspaces(workspace_id) ON DELETE SET NULL,
    event_type text NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 100),
    action text NOT NULL CHECK (char_length(action) BETWEEN 1 AND 100),
    outcome text NOT NULL CHECK (outcome IN ('allowed','denied','failed')),
    resource_type text,
    resource_id text,
    correlation_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS security_audit_events_user_idx
    ON public.security_audit_events(user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS security_audit_events_workspace_idx
    ON public.security_audit_events(workspace_id, occurred_at DESC);

ALTER TABLE public.workspace_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.security_audit_events ENABLE ROW LEVEL SECURITY;

GRANT SELECT ON public.product_workspaces TO authenticated;
GRANT INSERT, UPDATE ON public.product_workspaces TO authenticated;
GRANT SELECT ON public.product_artifacts TO authenticated;
GRANT SELECT, INSERT ON public.workspace_memberships TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.approval_requests TO authenticated;
GRANT SELECT, INSERT ON public.security_audit_events TO authenticated;

DROP POLICY IF EXISTS workspace_memberships_select ON public.workspace_memberships;
CREATE POLICY workspace_memberships_select ON public.workspace_memberships
FOR SELECT TO authenticated
USING (user_id = (SELECT auth.uid()) OR EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = workspace_memberships.workspace_id
      AND m.user_id = (SELECT auth.uid())
      AND m.role IN ('owner','project_manager')
));

DROP POLICY IF EXISTS workspace_memberships_insert ON public.workspace_memberships;
CREATE POLICY workspace_memberships_insert ON public.workspace_memberships
FOR INSERT TO authenticated
WITH CHECK (
    user_id = (SELECT auth.uid())
    OR EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = workspace_memberships.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role = 'owner'
    )
);

DROP POLICY IF EXISTS product_workspaces_select ON public.product_workspaces;
CREATE POLICY product_workspaces_select ON public.product_workspaces
FOR SELECT TO authenticated
USING (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = product_workspaces.workspace_id
      AND m.user_id = (SELECT auth.uid())
));

DROP POLICY IF EXISTS product_workspaces_insert ON public.product_workspaces;
CREATE POLICY product_workspaces_insert ON public.product_workspaces
FOR INSERT TO authenticated
WITH CHECK (created_by = (SELECT auth.uid()));

DROP POLICY IF EXISTS product_workspaces_update ON public.product_workspaces;
CREATE POLICY product_workspaces_update ON public.product_workspaces
FOR UPDATE TO authenticated
USING (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = product_workspaces.workspace_id
      AND m.user_id = (SELECT auth.uid())
      AND m.role IN ('owner','project_manager')
))
WITH CHECK (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = product_workspaces.workspace_id
      AND m.user_id = (SELECT auth.uid())
      AND m.role IN ('owner','project_manager')
));

DROP POLICY IF EXISTS product_artifacts_select ON public.product_artifacts;
CREATE POLICY product_artifacts_select ON public.product_artifacts
FOR SELECT TO authenticated
USING (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = product_artifacts.workspace_id
      AND m.user_id = (SELECT auth.uid())
));

DROP POLICY IF EXISTS approval_requests_select ON public.approval_requests;
CREATE POLICY approval_requests_select ON public.approval_requests
FOR SELECT TO authenticated
USING (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = approval_requests.workspace_id
      AND m.user_id = (SELECT auth.uid())
));

DROP POLICY IF EXISTS approval_requests_insert ON public.approval_requests;
CREATE POLICY approval_requests_insert ON public.approval_requests
FOR INSERT TO authenticated
WITH CHECK (
    requested_by = (SELECT auth.uid())
    AND EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = approval_requests.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role IN ('owner','project_manager','risk_compliance')
    )
);

DROP POLICY IF EXISTS approval_requests_update ON public.approval_requests;
CREATE POLICY approval_requests_update ON public.approval_requests
FOR UPDATE TO authenticated
USING (
    decision = 'pending'
    AND EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = approval_requests.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role IN ('owner','project_manager','reviewer')
    )
)
WITH CHECK (
    decided_by = (SELECT auth.uid())
    AND decision IN ('approve','reject')
    AND EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = approval_requests.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role IN ('owner','project_manager','reviewer')
    )
);

DROP POLICY IF EXISTS security_audit_events_select ON public.security_audit_events;
CREATE POLICY security_audit_events_select ON public.security_audit_events
FOR SELECT TO authenticated
USING (
    user_id = (SELECT auth.uid())
    OR EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = security_audit_events.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role IN ('owner','project_manager','risk_compliance','reviewer')
    )
);

DROP POLICY IF EXISTS security_audit_events_insert ON public.security_audit_events;
CREATE POLICY security_audit_events_insert ON public.security_audit_events
FOR INSERT TO authenticated
WITH CHECK (user_id = (SELECT auth.uid()));

-- Explicitly prevent anonymous access to governance records.
REVOKE ALL ON public.workspace_memberships FROM anon;
REVOKE ALL ON public.approval_requests FROM anon;
REVOKE ALL ON public.security_audit_events FROM anon;
