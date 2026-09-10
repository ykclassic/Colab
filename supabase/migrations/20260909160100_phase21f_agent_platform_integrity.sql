-- Phase 21F: durable workspace-bound agent platform integrity.
CREATE TABLE IF NOT EXISTS public.agent_platform_versions (
  agent_id uuid NOT NULL,
  version integer NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id),
  config_hash text NOT NULL,
  status text NOT NULL CHECK (status IN ('DRAFT','EVALUATING','PROMOTED','REJECTED','SUPERSEDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_id, version)
);
CREATE TABLE IF NOT EXISTS public.agent_platform_evaluations (
  evaluation_id uuid PRIMARY KEY,
  agent_id uuid NOT NULL,
  version integer NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id),
  task_type text NOT NULL,
  benchmark_id text NOT NULL,
  score double precision NOT NULL CHECK (score BETWEEN 0 AND 1),
  evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (agent_id, version) REFERENCES public.agent_platform_versions(agent_id, version)
);
CREATE TABLE IF NOT EXISTS public.agent_platform_performance (
  performance_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id uuid NOT NULL, version integer NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id),
  task_type text NOT NULL, score double precision NOT NULL,
  sample_count integer NOT NULL CHECK (sample_count >= 0), window_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (agent_id, version) REFERENCES public.agent_platform_versions(agent_id, version)
);
CREATE TABLE IF NOT EXISTS public.agent_platform_memory (
  memory_id uuid PRIMARY KEY, agent_id uuid NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id),
  task_type text NOT NULL, content text NOT NULL, evidence_ids jsonb NOT NULL,
  content_hash text NOT NULL, active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.agent_platform_costs (
  cost_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), agent_id uuid NOT NULL, version integer NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id), task_type text NOT NULL,
  input_tokens integer NOT NULL CHECK (input_tokens >= 0), output_tokens integer NOT NULL CHECK (output_tokens >= 0),
  cost numeric(18,8) NOT NULL CHECK (cost >= 0), created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (agent_id, version) REFERENCES public.agent_platform_versions(agent_id, version)
);
CREATE TABLE IF NOT EXISTS public.agent_platform_arbitrations (
  decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id),
  task_type text NOT NULL, winner_agent_id uuid NOT NULL, winner_version integer NOT NULL,
  confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1), evidence_ids jsonb NOT NULL,
  decision_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['agent_platform_versions','agent_platform_evaluations','agent_platform_performance','agent_platform_memory','agent_platform_costs','agent_platform_arbitrations'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS phase21f_member_select ON public.%I', t);
    EXECUTE format('CREATE POLICY phase21f_member_select ON public.%I FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id))', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon', t);
  END LOOP;
END $$;

-- Evaluation records are append-only; memory is explicitly lifecycle-managed by active=false rather than deletion.
CREATE OR REPLACE FUNCTION public.phase21f_block_eval_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Phase 21F evaluation records are immutable'; END; $$;
DROP TRIGGER IF EXISTS phase21f_eval_immutable ON public.agent_platform_evaluations;
CREATE TRIGGER phase21f_eval_immutable BEFORE UPDATE OR DELETE ON public.agent_platform_evaluations FOR EACH ROW EXECUTE FUNCTION public.phase21f_block_eval_mutation();
