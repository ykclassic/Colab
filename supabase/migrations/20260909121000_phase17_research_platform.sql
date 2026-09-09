-- Phase 17: Research Platform
-- Dataset registry, extraction lineage, real embeddings, pgvector hybrid retrieval.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.research_datasets (
    dataset_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.product_workspaces(workspace_id) ON DELETE RESTRICT,
    name text NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    source_uri text NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    schema_hash text NOT NULL CHECK (length(schema_hash) = 64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL,
    UNIQUE (workspace_id, name, version)
);

CREATE TABLE IF NOT EXISTS public.research_extractions (
    extraction_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES public.research_datasets(dataset_id) ON DELETE RESTRICT,
    media_type text NOT NULL,
    filename text,
    extractor text NOT NULL,
    extracted_text_hash text NOT NULL CHECK (length(extracted_text_hash) = 64),
    character_count integer NOT NULL CHECK (character_count >= 0),
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS public.research_platform_chunks (
    chunk_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES public.research_datasets(dataset_id) ON DELETE RESTRICT,
    document_id uuid NOT NULL REFERENCES public.research_documents(document_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    text text NOT NULL,
    embedding vector(1536) NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_document tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS research_datasets_workspace_idx ON public.research_datasets(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS research_extractions_dataset_idx ON public.research_extractions(dataset_id, created_at);
CREATE INDEX IF NOT EXISTS research_platform_chunks_dataset_idx ON public.research_platform_chunks(dataset_id, document_id, ordinal);
CREATE INDEX IF NOT EXISTS research_platform_chunks_fts_idx ON public.research_platform_chunks USING gin(search_document);
CREATE INDEX IF NOT EXISTS research_platform_chunks_embedding_idx
    ON public.research_platform_chunks USING hnsw (embedding vector_cosine_ops);

ALTER TABLE public.research_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_platform_chunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS research_datasets_workspace ON public.research_datasets;
CREATE POLICY research_datasets_workspace ON public.research_datasets
    FOR ALL USING (public.is_workspace_member(workspace_id)) WITH CHECK (public.is_workspace_member(workspace_id));
DROP POLICY IF EXISTS research_extractions_workspace ON public.research_extractions;
CREATE POLICY research_extractions_workspace ON public.research_extractions
    FOR ALL USING (EXISTS (SELECT 1 FROM public.research_datasets d WHERE d.dataset_id = research_extractions.dataset_id AND public.is_workspace_member(d.workspace_id)))
    WITH CHECK (EXISTS (SELECT 1 FROM public.research_datasets d WHERE d.dataset_id = research_extractions.dataset_id AND public.is_workspace_member(d.workspace_id)));
DROP POLICY IF EXISTS research_platform_chunks_workspace ON public.research_platform_chunks;
CREATE POLICY research_platform_chunks_workspace ON public.research_platform_chunks
    FOR ALL USING (EXISTS (SELECT 1 FROM public.research_datasets d WHERE d.dataset_id = research_platform_chunks.dataset_id AND public.is_workspace_member(d.workspace_id)))
    WITH CHECK (EXISTS (SELECT 1 FROM public.research_datasets d WHERE d.dataset_id = research_platform_chunks.dataset_id AND public.is_workspace_member(d.workspace_id)));

-- Platform records are lineage-bearing and should be replaced by new versions rather than mutated.
CREATE OR REPLACE FUNCTION public.prevent_research_platform_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'research platform lineage records are append-only';
END;
$$;
DROP TRIGGER IF EXISTS research_datasets_immutable ON public.research_datasets;
CREATE TRIGGER research_datasets_immutable BEFORE UPDATE OR DELETE ON public.research_datasets
FOR EACH ROW EXECUTE FUNCTION public.prevent_research_platform_mutation();
DROP TRIGGER IF EXISTS research_extractions_immutable ON public.research_extractions;
CREATE TRIGGER research_extractions_immutable BEFORE UPDATE OR DELETE ON public.research_extractions
FOR EACH ROW EXECUTE FUNCTION public.prevent_research_platform_mutation();
DROP TRIGGER IF EXISTS research_platform_chunks_immutable ON public.research_platform_chunks;
CREATE TRIGGER research_platform_chunks_immutable BEFORE UPDATE OR DELETE ON public.research_platform_chunks
FOR EACH ROW EXECUTE FUNCTION public.prevent_research_platform_mutation();
