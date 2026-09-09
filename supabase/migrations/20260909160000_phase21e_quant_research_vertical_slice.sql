-- Phase 21E quantitative research vertical slice persistence.
CREATE TABLE IF NOT EXISTS public.quant_research_runs (
    run_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id),
    dataset_id uuid NOT NULL,
    strategy_id uuid NOT NULL REFERENCES public.quant_strategies(strategy_id),
    experiment_id uuid NOT NULL REFERENCES public.quant_experiments(experiment_id),
    experiment_hash text NOT NULL,
    validation_hash text NOT NULL,
    reproducibility_hash text NOT NULL,
    backtest jsonb NOT NULL,
    walk_forward_oos jsonb NOT NULL,
    risk jsonb NOT NULL,
    stress jsonb NOT NULL,
    monte_carlo jsonb NOT NULL,
    robustness jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, reproducibility_hash)
);

ALTER TABLE public.quant_research_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS quant_research_runs_workspace_select ON public.quant_research_runs;
CREATE POLICY quant_research_runs_workspace_select ON public.quant_research_runs
    FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS quant_research_runs_workspace_insert ON public.quant_research_runs;
CREATE POLICY quant_research_runs_workspace_insert ON public.quant_research_runs
    FOR INSERT TO authenticated WITH CHECK (public.is_workspace_member(workspace_id));
REVOKE ALL ON public.quant_research_runs FROM anon;

CREATE OR REPLACE FUNCTION public.prevent_quant_research_run_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'quant research runs are immutable';
END;
$$;
DROP TRIGGER IF EXISTS quant_research_runs_immutable ON public.quant_research_runs;
CREATE TRIGGER quant_research_runs_immutable
BEFORE UPDATE OR DELETE ON public.quant_research_runs
FOR EACH ROW EXECUTE FUNCTION public.prevent_quant_research_run_mutation();
