-- Phase 13: durable tenant isolation and controlled integration audit.
-- The application uses a privileged DB connection, so API authorization remains
-- mandatory even though RLS also protects direct Supabase access.

ALTER TABLE public.knowledge_documents
    ADD COLUMN IF NOT EXISTS workspace_id uuid REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS knowledge_documents_workspace_idx
    ON public.knowledge_documents(workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.external_integration_audits (
    audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL,
    workspace_id uuid REFERENCES public.product_workspaces(workspace_id) ON DELETE SET NULL,
    user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    connector text NOT NULL CHECK (char_length(connector) BETWEEN 1 AND 100),
    path text NOT NULL CHECK (char_length(path) BETWEEN 1 AND 500),
    status_code integer,
    success boolean NOT NULL,
    error text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (request_id)
);
CREATE INDEX IF NOT EXISTS external_integration_audits_workspace_idx
    ON public.external_integration_audits(workspace_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS external_integration_audits_user_idx
    ON public.external_integration_audits(user_id, occurred_at DESC);

ALTER TABLE public.knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.external_integration_audits ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON public.knowledge_documents TO authenticated;
GRANT SELECT, INSERT ON public.external_integration_audits TO authenticated;
REVOKE ALL ON public.knowledge_documents FROM anon;
REVOKE ALL ON public.external_integration_audits FROM anon;

DROP POLICY IF EXISTS knowledge_documents_workspace_select ON public.knowledge_documents;
CREATE POLICY knowledge_documents_workspace_select ON public.knowledge_documents
FOR SELECT TO authenticated
USING (
    workspace_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = knowledge_documents.workspace_id
          AND m.user_id = (SELECT auth.uid())
    )
);

DROP POLICY IF EXISTS knowledge_documents_workspace_insert ON public.knowledge_documents;
CREATE POLICY knowledge_documents_workspace_insert ON public.knowledge_documents
FOR INSERT TO authenticated
WITH CHECK (
    workspace_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = knowledge_documents.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role IN ('owner','project_manager','quant_researcher')
    )
);

DROP POLICY IF EXISTS knowledge_documents_workspace_update ON public.knowledge_documents;
CREATE POLICY knowledge_documents_workspace_update ON public.knowledge_documents
FOR UPDATE TO authenticated
USING (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = knowledge_documents.workspace_id
      AND m.user_id = (SELECT auth.uid())
      AND m.role IN ('owner','project_manager','quant_researcher')
))
WITH CHECK (EXISTS (
    SELECT 1 FROM public.workspace_memberships m
    WHERE m.workspace_id = knowledge_documents.workspace_id
      AND m.user_id = (SELECT auth.uid())
      AND m.role IN ('owner','project_manager','quant_researcher')
));

DROP POLICY IF EXISTS external_integration_audits_select ON public.external_integration_audits;
CREATE POLICY external_integration_audits_select ON public.external_integration_audits
FOR SELECT TO authenticated
USING (
    user_id = (SELECT auth.uid()) OR EXISTS (
        SELECT 1 FROM public.workspace_memberships m
        WHERE m.workspace_id = external_integration_audits.workspace_id
          AND m.user_id = (SELECT auth.uid())
          AND m.role IN ('owner','project_manager','risk_compliance','reviewer')
    )
);

DROP POLICY IF EXISTS external_integration_audits_insert ON public.external_integration_audits;
CREATE POLICY external_integration_audits_insert ON public.external_integration_audits
FOR INSERT TO authenticated
WITH CHECK (user_id = (SELECT auth.uid()));

-- Existing rows cannot be safely assigned to a tenant. They are deliberately
-- left NULL and are therefore invisible through the authenticated RLS policy.
