-- Phase 21G: durable production background jobs.
-- API requests enqueue bounded work; workers claim leases and persist progress/results.
CREATE TABLE IF NOT EXISTS public.background_jobs (
  job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
  workflow_id uuid,
  job_type text NOT NULL CHECK (job_type IN ('research_ingestion','embedding','backtest','monte_carlo','robustness_analysis','report_generation','agent_evaluation')),
  idempotency_key text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  progress_message text,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
  lease_owner text,
  lease_expires_at timestamptz,
  artifact_id uuid,
  result jsonb,
  error text,
  notification_status text NOT NULL DEFAULT 'pending' CHECK (notification_status IN ('pending','sent','failed','disabled')),
  notification_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.background_job_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES public.background_jobs(job_id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
  status text NOT NULL,
  progress integer NOT NULL CHECK (progress BETWEEN 0 AND 100),
  message text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.background_job_artifacts (
  artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES public.background_jobs(job_id) ON DELETE RESTRICT,
  workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
  kind text NOT NULL,
  content jsonb NOT NULL,
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, content_hash)
);

CREATE INDEX IF NOT EXISTS background_jobs_claim_idx ON public.background_jobs(status, lease_expires_at, created_at);
CREATE INDEX IF NOT EXISTS background_jobs_workspace_idx ON public.background_jobs(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS background_job_events_job_idx ON public.background_job_events(job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS background_job_artifacts_job_idx ON public.background_job_artifacts(job_id, created_at DESC);

ALTER TABLE public.background_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.background_job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.background_job_artifacts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS phase21g_jobs_select ON public.background_jobs;
CREATE POLICY phase21g_jobs_select ON public.background_jobs FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21g_events_select ON public.background_job_events;
CREATE POLICY phase21g_events_select ON public.background_job_events FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS phase21g_artifacts_select ON public.background_job_artifacts;
CREATE POLICY phase21g_artifacts_select ON public.background_job_artifacts FOR SELECT TO authenticated USING (public.is_workspace_member(workspace_id));
REVOKE ALL ON public.background_jobs, public.background_job_events, public.background_job_artifacts FROM anon;

CREATE OR REPLACE FUNCTION public.phase21g_touch_background_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;
DROP TRIGGER IF EXISTS phase21g_touch_job ON public.background_jobs;
CREATE TRIGGER phase21g_touch_job BEFORE UPDATE ON public.background_jobs FOR EACH ROW EXECUTE FUNCTION public.phase21g_touch_background_job();

CREATE OR REPLACE FUNCTION public.phase21g_claim_background_job(p_worker text, p_lease_seconds integer)
RETURNS SETOF public.background_jobs LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  WITH candidate AS (
    SELECT job_id FROM public.background_jobs
    WHERE (status = 'queued' OR (status = 'running' AND lease_expires_at <= now()))
      AND attempt < max_attempts
    ORDER BY created_at, job_id
    FOR UPDATE SKIP LOCKED LIMIT 1
  )
  UPDATE public.background_jobs j
  SET status='running', attempt=j.attempt+1, lease_owner=p_worker,
      lease_expires_at=now() + make_interval(secs => p_lease_seconds),
      started_at=COALESCE(j.started_at, now()), progress=GREATEST(j.progress, 1)
  FROM candidate c WHERE j.job_id=c.job_id RETURNING j.*;
END; $$;
