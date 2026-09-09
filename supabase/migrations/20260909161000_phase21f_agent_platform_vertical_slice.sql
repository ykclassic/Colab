-- Phase 21F: durable agent versions, benchmark evidence and promotion governance.
-- Promotion remains explicitly governed; agents do not receive direct execution authority.
CREATE TABLE IF NOT EXISTS public.agent_versions (
  agent_id uuid NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
  name text NOT NULL, version integer NOT NULL CHECK (version > 0), role text NOT NULL,
  code_revision text NOT NULL, model text NOT NULL, tools jsonb NOT NULL DEFAULT '[]'::jsonb,
  configuration jsonb NOT NULL DEFAULT '{}'::jsonb, enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (agent_id, version), UNIQUE (workspace_id, name, version)
);
CREATE TABLE IF NOT EXISTS public.agent_benchmarks (
  benchmark_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), agent_id uuid NOT NULL,
  version integer NOT NULL, evaluation_ids uuid[] NOT NULL, score double precision NOT NULL,
  pass_rate double precision NOT NULL, evidence_quality double precision NOT NULL,
  regression boolean NOT NULL, baseline_score double precision, benchmark_hash text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (agent_id, version) REFERENCES public.agent_versions(agent_id, version) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS public.agent_version_governance (
  decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), agent_id uuid NOT NULL, version integer NOT NULL,
  approved boolean NOT NULL, reason text NOT NULL, benchmark_hash text NOT NULL,
  decided_at timestamptz NOT NULL,
  FOREIGN KEY (agent_id, version) REFERENCES public.agent_versions(agent_id, version) ON DELETE RESTRICT,
  FOREIGN KEY (benchmark_hash) REFERENCES public.agent_benchmarks(benchmark_hash) ON DELETE RESTRICT
);
ALTER TABLE public.agent_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_benchmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_version_governance ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS phase21f_agent_versions_select ON public.agent_versions;
CREATE POLICY phase21f_agent_versions_select ON public.agent_versions FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21f_agent_benchmarks_select ON public.agent_benchmarks;
CREATE POLICY phase21f_agent_benchmarks_select ON public.agent_benchmarks FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.agent_versions v WHERE v.agent_id=agent_benchmarks.agent_id AND v.version=agent_benchmarks.version AND public.is_workspace_member(v.workspace_id)));
DROP POLICY IF EXISTS phase21f_agent_governance_select ON public.agent_version_governance;
CREATE POLICY phase21f_agent_governance_select ON public.agent_version_governance FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.agent_versions v WHERE v.agent_id=agent_version_governance.agent_id AND v.version=agent_version_governance.version AND public.is_workspace_member(v.workspace_id)));
REVOKE ALL ON public.agent_versions, public.agent_benchmarks, public.agent_version_governance FROM anon;
CREATE OR REPLACE FUNCTION public.prevent_phase21f_immutable_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'phase21f immutable records cannot be updated or deleted'; END; $$;
DROP TRIGGER IF EXISTS phase21f_versions_immutable ON public.agent_versions;
CREATE TRIGGER phase21f_versions_immutable BEFORE UPDATE OR DELETE ON public.agent_versions FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21f_immutable_mutation();
DROP TRIGGER IF EXISTS phase21f_benchmarks_immutable ON public.agent_benchmarks;
CREATE TRIGGER phase21f_benchmarks_immutable BEFORE UPDATE OR DELETE ON public.agent_benchmarks FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21f_immutable_mutation();
DROP TRIGGER IF EXISTS phase21f_governance_immutable ON public.agent_version_governance;
CREATE TRIGGER phase21f_governance_immutable BEFORE UPDATE OR DELETE ON public.agent_version_governance FOR EACH ROW EXECUTE FUNCTION public.prevent_phase21f_immutable_mutation();
CREATE OR REPLACE FUNCTION public.validate_phase21f_governance() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NOT EXISTS (SELECT 1 FROM public.agent_benchmarks b WHERE b.benchmark_hash=NEW.benchmark_hash AND b.agent_id=NEW.agent_id AND b.version=NEW.version) THEN RAISE EXCEPTION 'phase21f governance requires matching benchmark'; END IF; RETURN NEW; END; $$;
DROP TRIGGER IF EXISTS phase21f_governance_validate ON public.agent_version_governance;
CREATE TRIGGER phase21f_governance_validate BEFORE INSERT ON public.agent_version_governance FOR EACH ROW EXECUTE FUNCTION public.validate_phase21f_governance();
