-- Phase 21B: database-level tenant isolation and migration integrity.
-- The API remains authorized independently; these policies provide a second,
-- database-enforced boundary for direct authenticated Supabase access.

CREATE OR REPLACE FUNCTION public.is_workspace_member(target_workspace_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.workspace_memberships wm
        WHERE wm.workspace_id = target_workspace_id
          AND wm.user_id = (SELECT auth.uid())
    );
$$;

REVOKE ALL ON FUNCTION public.is_workspace_member(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_workspace_member(uuid) TO authenticated;

-- Legacy workflow rows did not carry tenant identity. New writes must be bound
-- to a workspace; existing rows remain inaccessible to authenticated tenants
-- until explicitly migrated by an operator with authoritative ownership data.
ALTER TABLE public.workflows
    ADD COLUMN IF NOT EXISTS workspace_id uuid REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS workflows_workspace_idx
    ON public.workflows(workspace_id, updated_at DESC);

-- Recover workspace identity where an execution record provides an unambiguous
-- tenant binding. Do not guess ownership for orphaned legacy workflows.
UPDATE public.workflows w
SET workspace_id = candidates.workspace_id
FROM (
    SELECT workflow_id, min(workspace_id) AS workspace_id
    FROM public.workflow_execution_jobs
    GROUP BY workflow_id
    HAVING count(DISTINCT workspace_id) = 1
) candidates
WHERE w.workflow_id = candidates.workflow_id
  AND w.workspace_id IS NULL;

ALTER TABLE public.workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.risk_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_execution_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_operational_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quant_strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quant_experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_costs ENABLE ROW LEVEL SECURITY;

-- Replace recursive membership checks with the SECURITY DEFINER helper.
DROP POLICY IF EXISTS workspace_memberships_select ON public.workspace_memberships;
CREATE POLICY workspace_memberships_select ON public.workspace_memberships
FOR SELECT TO authenticated
USING (user_id = (SELECT auth.uid()) OR public.is_workspace_member(workspace_id));

DROP POLICY IF EXISTS workspace_memberships_insert ON public.workspace_memberships;
CREATE POLICY workspace_memberships_insert ON public.workspace_memberships
FOR INSERT TO authenticated
WITH CHECK (user_id = (SELECT auth.uid()) OR public.is_workspace_member(workspace_id));

-- Parent workflow boundary.
DROP POLICY IF EXISTS phase21b_workflows_select ON public.workflows;
CREATE POLICY phase21b_workflows_select ON public.workflows
FOR SELECT TO authenticated USING (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_workflows_insert ON public.workflows;
CREATE POLICY phase21b_workflows_insert ON public.workflows
FOR INSERT TO authenticated WITH CHECK (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_workflows_update ON public.workflows;
CREATE POLICY phase21b_workflows_update ON public.workflows
FOR UPDATE TO authenticated USING (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id))
WITH CHECK (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id));

-- Child workflow records derive their tenant from the workflow parent.
DROP POLICY IF EXISTS phase21b_workflow_children_select ON public.workflow_checkpoints;
CREATE POLICY phase21b_workflow_children_select ON public.workflow_checkpoints
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=workflow_checkpoints.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));
DROP POLICY IF EXISTS phase21b_workflow_children_select_tasks ON public.agent_tasks;
CREATE POLICY phase21b_workflow_children_select_tasks ON public.agent_tasks
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=agent_tasks.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));
DROP POLICY IF EXISTS phase21b_workflow_children_select_artifacts ON public.artifacts;
CREATE POLICY phase21b_workflow_children_select_artifacts ON public.artifacts
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=artifacts.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));
DROP POLICY IF EXISTS phase21b_workflow_children_select_risk ON public.risk_assessments;
CREATE POLICY phase21b_workflow_children_select_risk ON public.risk_assessments
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=risk_assessments.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));
DROP POLICY IF EXISTS phase21b_workflow_children_select_decisions ON public.workflow_decisions;
CREATE POLICY phase21b_workflow_children_select_decisions ON public.workflow_decisions
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=workflow_decisions.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));
DROP POLICY IF EXISTS phase21b_workflow_children_select_approvals ON public.workflow_approvals;
CREATE POLICY phase21b_workflow_children_select_approvals ON public.workflow_approvals
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=workflow_approvals.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));
DROP POLICY IF EXISTS phase21b_workflow_children_select_audit ON public.audit_events;
CREATE POLICY phase21b_workflow_children_select_audit ON public.audit_events
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workflows w WHERE w.workflow_id=audit_events.workflow_id AND w.workspace_id IS NOT NULL AND public.is_workspace_member(w.workspace_id)));

-- Operational records already carry workspace_id.
DROP POLICY IF EXISTS phase21b_execution_jobs_access ON public.workflow_execution_jobs;
CREATE POLICY phase21b_execution_jobs_access ON public.workflow_execution_jobs
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_operational_events_access ON public.workflow_operational_events;
CREATE POLICY phase21b_operational_events_access ON public.workflow_operational_events
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));

-- Product artifacts and knowledge documents are directly workspace-bound.
DROP POLICY IF EXISTS phase21b_product_artifacts_access ON public.product_artifacts;
CREATE POLICY phase21b_product_artifacts_access ON public.product_artifacts
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_knowledge_documents_access ON public.knowledge_documents;
CREATE POLICY phase21b_knowledge_documents_access ON public.knowledge_documents
FOR ALL TO authenticated USING (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id))
WITH CHECK (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id));

-- Research sources are intentionally not globally readable. Access is through
-- documents belonging to a tenant; chunks are protected through their document.
DROP POLICY IF EXISTS phase21b_research_documents_access ON public.research_documents;
CREATE POLICY phase21b_research_documents_access ON public.research_documents
FOR ALL TO authenticated USING (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id))
WITH CHECK (workspace_id IS NOT NULL AND public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_research_chunks_access ON public.research_chunks;
CREATE POLICY phase21b_research_chunks_access ON public.research_chunks
FOR ALL TO authenticated USING (EXISTS (SELECT 1 FROM public.research_documents d WHERE d.document_id=research_chunks.document_id AND d.workspace_id IS NOT NULL AND public.is_workspace_member(d.workspace_id)))
WITH CHECK (EXISTS (SELECT 1 FROM public.research_documents d WHERE d.document_id=research_chunks.document_id AND d.workspace_id IS NOT NULL AND public.is_workspace_member(d.workspace_id)));
DROP POLICY IF EXISTS phase21b_research_sources_access ON public.research_sources;
CREATE POLICY phase21b_research_sources_access ON public.research_sources
FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.research_documents d WHERE d.source_id=research_sources.source_id AND d.workspace_id IS NOT NULL AND public.is_workspace_member(d.workspace_id)));

-- Quant and agent platform records.
DROP POLICY IF EXISTS phase21b_quant_strategies_access ON public.quant_strategies;
CREATE POLICY phase21b_quant_strategies_access ON public.quant_strategies
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_quant_experiments_access ON public.quant_experiments;
CREATE POLICY phase21b_quant_experiments_access ON public.quant_experiments
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_agents_access ON public.agents;
CREATE POLICY phase21b_agents_access ON public.agents
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_agent_evaluations_access ON public.agent_evaluations;
CREATE POLICY phase21b_agent_evaluations_access ON public.agent_evaluations
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_agent_memory_access ON public.agent_memory;
CREATE POLICY phase21b_agent_memory_access ON public.agent_memory
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21b_agent_costs_access ON public.agent_costs;
CREATE POLICY phase21b_agent_costs_access ON public.agent_costs
FOR ALL TO authenticated USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));

-- Anonymous clients must never obtain direct database access to tenant data.
REVOKE ALL ON public.workflows, public.workflow_checkpoints, public.agent_tasks,
    public.artifacts, public.risk_assessments, public.workflow_decisions,
    public.workflow_approvals, public.audit_events, public.workflow_execution_jobs,
    public.workflow_operational_events, public.product_artifacts, public.knowledge_documents,
    public.research_documents, public.research_chunks, public.research_sources,
    public.quant_strategies, public.quant_experiments, public.agents,
    public.agent_evaluations, public.agent_memory, public.agent_costs FROM anon;
