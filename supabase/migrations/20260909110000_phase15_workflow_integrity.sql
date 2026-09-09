-- Phase 15: workflow integrity.
-- Workflow events and snapshots are append-only durable records. The application
-- computes SHA-256 hashes over canonical state; PostgreSQL enforces immutability.

ALTER TABLE public.workflow_checkpoints
    ADD COLUMN IF NOT EXISTS state_hash text;

UPDATE public.workflow_checkpoints
SET state_hash = encode(digest(state::text, 'sha256'), 'hex')
WHERE state_hash IS NULL;

ALTER TABLE public.workflow_checkpoints
    ALTER COLUMN state_hash SET NOT NULL;

CREATE TABLE IF NOT EXISTS public.workflow_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id uuid NOT NULL REFERENCES public.workflows(workflow_id) ON DELETE CASCADE,
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    event_type text NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 100),
    from_stage text NOT NULL CHECK (char_length(from_stage) BETWEEN 1 AND 100),
    to_stage text NOT NULL CHECK (char_length(to_stage) BETWEEN 1 AND 100),
    previous_state_hash text,
    resulting_state_hash text NOT NULL CHECK (resulting_state_hash ~ '^[0-9a-f]{64}$'),
    snapshot_version bigint NOT NULL CHECK (snapshot_version > 0),
    actor text NOT NULL CHECK (char_length(actor) BETWEEN 1 AND 100),
    message text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workflow_id, sequence_no),
    UNIQUE (workflow_id, event_id)
);

CREATE INDEX IF NOT EXISTS workflow_events_workflow_idx
    ON public.workflow_events(workflow_id, sequence_no);

ALTER TABLE public.workflow_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_checkpoints ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS workflow_events_workspace_select ON public.workflow_events;
CREATE POLICY workflow_events_workspace_select ON public.workflow_events
FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.workflows w
        JOIN public.workspace_memberships m ON m.workspace_id = w.workspace_id
        WHERE w.workflow_id = workflow_events.workflow_id
          AND m.user_id = (SELECT auth.uid())
    )
);

DROP FUNCTION IF EXISTS public.prevent_workflow_integrity_mutation();
CREATE OR REPLACE FUNCTION public.prevent_workflow_integrity_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'workflow integrity records are append-only';
END;
$$;

DROP TRIGGER IF EXISTS workflow_events_immutable ON public.workflow_events;
CREATE TRIGGER workflow_events_immutable
BEFORE UPDATE OR DELETE ON public.workflow_events
FOR EACH ROW EXECUTE FUNCTION public.prevent_workflow_integrity_mutation();

DROP TRIGGER IF EXISTS workflow_checkpoints_immutable ON public.workflow_checkpoints;
CREATE TRIGGER workflow_checkpoints_immutable
BEFORE UPDATE OR DELETE ON public.workflow_checkpoints
FOR EACH ROW EXECUTE FUNCTION public.prevent_workflow_integrity_mutation();

REVOKE UPDATE, DELETE ON public.workflow_events FROM authenticated;
REVOKE UPDATE, DELETE ON public.workflow_checkpoints FROM authenticated;
GRANT SELECT, INSERT ON public.workflow_events TO authenticated;
GRANT SELECT, INSERT ON public.workflow_checkpoints TO authenticated;

COMMENT ON TABLE public.workflow_events IS 'Append-only tamper-evident workflow transition ledger.';
COMMENT ON TABLE public.workflow_checkpoints IS 'Append-only durable workflow snapshots validated against state hashes.';
