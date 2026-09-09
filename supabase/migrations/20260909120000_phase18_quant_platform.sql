CREATE TABLE IF NOT EXISTS public.quant_strategies (
    strategy_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    name text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    code_revision text NOT NULL,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    dataset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, name, version)
);
CREATE TABLE IF NOT EXISTS public.quant_experiments (
    experiment_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    strategy_id uuid NOT NULL REFERENCES public.quant_strategies(strategy_id),
    strategy_version integer NOT NULL,
    dataset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    seed integer NOT NULL,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    experiment_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quant_strategies_workspace_idx ON public.quant_strategies(workspace_id);
CREATE INDEX IF NOT EXISTS quant_experiments_workspace_idx ON public.quant_experiments(workspace_id, created_at DESC);
ALTER TABLE public.quant_strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quant_experiments ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT ON public.quant_strategies TO authenticated;
GRANT SELECT, INSERT ON public.quant_experiments TO authenticated;
REVOKE ALL ON public.quant_strategies FROM anon;
REVOKE ALL ON public.quant_experiments FROM anon;
CREATE POLICY quant_strategies_select ON public.quant_strategies FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workspace_memberships m WHERE m.workspace_id=quant_strategies.workspace_id AND m.user_id=(SELECT auth.uid())));
CREATE POLICY quant_strategies_insert ON public.quant_strategies FOR INSERT TO authenticated WITH CHECK (EXISTS (SELECT 1 FROM public.workspace_memberships m WHERE m.workspace_id=quant_strategies.workspace_id AND m.user_id=(SELECT auth.uid()) AND m.role IN ('owner','project_manager','quant_researcher')));
CREATE POLICY quant_experiments_select ON public.quant_experiments FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.workspace_memberships m WHERE m.workspace_id=quant_experiments.workspace_id AND m.user_id=(SELECT auth.uid())));
CREATE POLICY quant_experiments_insert ON public.quant_experiments FOR INSERT TO authenticated WITH CHECK (EXISTS (SELECT 1 FROM public.workspace_memberships m WHERE m.workspace_id=quant_experiments.workspace_id AND m.user_id=(SELECT auth.uid()) AND m.role IN ('owner','project_manager','quant_researcher')));
