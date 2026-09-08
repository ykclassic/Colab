-- Phase 8: durable source provenance, document versions, chunks and vector embeddings.
-- Embeddings are JSONB so the application remains deployable on PostgreSQL instances
-- without requiring a pgvector extension. The service performs cosine retrieval and
-- can migrate to a native vector index later without changing the API contracts.
CREATE TABLE IF NOT EXISTS public.research_sources (
    source_id uuid PRIMARY KEY,
    uri text NOT NULL,
    title text NOT NULL,
    publisher text,
    author text,
    published_at timestamptz,
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    source_type text NOT NULL,
    checksum text NOT NULL CHECK (length(checksum) = 64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.research_documents (
    document_id uuid PRIMARY KEY,
    workspace_id uuid REFERENCES public.product_workspaces(workspace_id) ON DELETE SET NULL,
    source_id uuid NOT NULL REFERENCES public.research_sources(source_id) ON DELETE RESTRICT,
    title text NOT NULL,
    text text NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS research_documents_workspace_idx
    ON public.research_documents(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS research_documents_source_idx
    ON public.research_documents(source_id, version);

CREATE TABLE IF NOT EXISTS public.research_chunks (
    chunk_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES public.research_documents(document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    text text NOT NULL,
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL CHECK (end_char > start_char),
    embedding jsonb NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS research_chunks_document_idx
    ON public.research_chunks(document_id, ordinal);

ALTER TABLE public.research_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_chunks ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.research_sources FROM anon, authenticated;
REVOKE ALL ON public.research_documents FROM anon, authenticated;
REVOKE ALL ON public.research_chunks FROM anon, authenticated;
