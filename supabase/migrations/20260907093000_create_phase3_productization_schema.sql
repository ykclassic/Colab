-- Phase 3 productization metadata. Content is application-level JSON and remains behind RLS.
CREATE TABLE IF NOT EXISTS public.product_workspaces (
    workspace_id uuid PRIMARY KEY,
    name text NOT NULL,
    product_goal text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','running','paused','complete','failed')),
    priority integer NOT NULL DEFAULT 100 CHECK (priority BETWEEN 0 AND 1000),
    strategies jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.product_artifacts (
    artifact_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE CASCADE,
    kind text NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    producer text NOT NULL,
    content jsonb NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, kind, version)
);
CREATE INDEX IF NOT EXISTS product_artifacts_workspace_idx
    ON public.product_artifacts(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS public.knowledge_documents (
    document_id uuid PRIMARY KEY,
    title text NOT NULL,
    text text NOT NULL,
    source text NOT NULL,
    tags text[] NOT NULL DEFAULT '{}',
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.platform_tools (
    name text PRIMARY KEY,
    description text NOT NULL,
    allowed boolean NOT NULL DEFAULT true,
    input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_schema jsonb NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE public.product_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_tools ENABLE ROW LEVEL SECURITY;

-- No browser role receives access until authenticated workspace/user policies are introduced.
REVOKE ALL ON public.product_workspaces FROM anon, authenticated;
REVOKE ALL ON public.product_artifacts FROM anon, authenticated;
REVOKE ALL ON public.knowledge_documents FROM anon, authenticated;
REVOKE ALL ON public.platform_tools FROM anon, authenticated;

DROP TRIGGER IF EXISTS product_workspaces_updated_at ON public.product_workspaces;
CREATE TRIGGER product_workspaces_updated_at
BEFORE UPDATE ON public.product_workspaces
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
