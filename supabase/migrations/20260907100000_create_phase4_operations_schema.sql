-- Phase 4: durable execution jobs and append-only operational telemetry.
CREATE TABLE IF NOT EXISTS public.workflow_execution_jobs (
    job_id uuid PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES public.workflows(workflow_id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    stage text NOT NULL CHECK (char_length(stage) BETWEEN 1 AND 100),
    idempotency_key text NOT NULL UNIQUE CHECK (char_length(idempotency_key) BETWEEN 1 AND 255),
    status text NOT NULL CHECK (status IN ('pending','running','succeeded','failed','cancelled')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
    lease_owner text,
    lease_expires_at timestamptz,
    error text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS workflow_execution_jobs_claim_idx
    ON public.workflow_execution_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS workflow_execution_jobs_lease_idx
    ON public.workflow_execution_jobs (status, lease_expires_at);

CREATE TABLE IF NOT EXISTS public.workflow_operational_events (
    event_id uuid PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES public.workflows(workflow_id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    job_id uuid REFERENCES public.workflow_execution_jobs(job_id) ON DELETE SET NULL,
    event_type text NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 100),
    level text NOT NULL CHECK (level IN ('info','warning','error')),
    actor text NOT NULL CHECK (char_length(actor) BETWEEN 1 AND 255),
    message text NOT NULL CHECK (char_length(message) BETWEEN 1 AND 5000),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS workflow_operational_events_workflow_idx
    ON public.workflow_operational_events (workflow_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS workflow_operational_events_job_idx
    ON public.workflow_operational_events (job_id, occurred_at DESC);

ALTER TABLE public.workflow_execution_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_operational_events ENABLE ROW LEVEL SECURITY;

-- No anon/authenticated policies are granted. The application service role owns
-- these operational records until workspace/user tenancy is introduced.
REVOKE ALL ON public.workflow_execution_jobs FROM anon, authenticated;
REVOKE ALL ON public.workflow_operational_events FROM anon, authenticated;
