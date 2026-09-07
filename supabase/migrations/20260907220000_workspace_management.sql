-- Workspace management: idempotent creation, optimistic concurrency, and archival.
ALTER TABLE public.product_workspaces
    ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS archived_at timestamptz,
    ADD COLUMN IF NOT EXISTS create_idempotency_key text;

ALTER TABLE public.product_workspaces
    DROP CONSTRAINT IF EXISTS product_workspaces_status_check;
ALTER TABLE public.product_workspaces
    ADD CONSTRAINT product_workspaces_status_check
    CHECK (status IN ('queued','running','paused','complete','failed','archived'));

ALTER TABLE public.product_workspaces
    DROP CONSTRAINT IF EXISTS product_workspaces_version_check;
ALTER TABLE public.product_workspaces
    ADD CONSTRAINT product_workspaces_version_check CHECK (version >= 1);

CREATE UNIQUE INDEX IF NOT EXISTS product_workspaces_create_idempotency_key_idx
    ON public.product_workspaces(create_idempotency_key)
    WHERE create_idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS product_workspaces_active_idx
    ON public.product_workspaces(status, priority DESC, created_at)
    WHERE status <> 'archived';

-- Keep archived workspaces out of the active scheduler.
UPDATE public.product_workspaces
SET archived_at = COALESCE(archived_at, updated_at)
WHERE status = 'archived' AND archived_at IS NULL;
