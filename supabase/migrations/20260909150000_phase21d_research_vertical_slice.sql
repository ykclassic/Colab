-- Phase 21D: durable research vertical-slice lineage and reproducible reports.
-- The existing Phase 17 tables hold dataset/extraction/chunk lineage. This migration
-- adds immutable report manifests so a completed research run can be retrieved after
-- process restart without relying on in-memory mappings.

CREATE TABLE IF NOT EXISTS public.research_reports (
    report_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    query text NOT NULL,
    answer text NOT NULL,
    citations jsonb NOT NULL,
    dataset_ids jsonb NOT NULL,
    retrieval_config jsonb NOT NULL,
    provider jsonb NOT NULL,
    reproducibility_hash text NOT NULL CHECK (length(reproducibility_hash) = 64),
    pipeline_hash text NOT NULL CHECK (length(pipeline_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_reports_workspace_idx
    ON public.research_reports(workspace_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS research_reports_pipeline_hash_idx
    ON public.research_reports(workspace_id, pipeline_hash);

ALTER TABLE public.research_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS research_reports_workspace ON public.research_reports;
CREATE POLICY research_reports_workspace ON public.research_reports
    FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));
REVOKE ALL ON public.research_reports FROM anon;
GRANT SELECT ON public.research_reports TO authenticated;

-- Report manifests are evidence of a completed run and must be replaced by a new
-- report when inputs change rather than edited in place.
CREATE OR REPLACE FUNCTION public.prevent_research_report_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'research reports are append-only';
END;
$$;
DROP TRIGGER IF EXISTS research_reports_immutable ON public.research_reports;
CREATE TRIGGER research_reports_immutable
BEFORE UPDATE OR DELETE ON public.research_reports
FOR EACH ROW EXECUTE FUNCTION public.prevent_research_report_mutation();
