"""PostgreSQL persistence and pgvector hybrid retrieval for Phase 17."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .research_platform import DatasetRecord, RetrievalCandidate


def _vector(value: list[float]) -> str:
    return "[" + ",".join(format(float(x), ".9g") for x in value) + "]"


class PostgresDatasetRegistry:
    def __init__(self, connection_factory: Callable[[], Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    def register(self, dataset: DatasetRecord) -> DatasetRecord:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.research_datasets
                (dataset_id,workspace_id,name,version,source_uri,content_hash,schema_hash,metadata,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *""",
                (dataset.dataset_id, dataset.workspace_id, dataset.name, dataset.version, dataset.source_uri,
                 dataset.content_hash, dataset.schema_hash, Jsonb(dataset.metadata), dataset.created_at),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("dataset registration returned no row")
        return DatasetRecord.model_validate(row)

    def get(self, dataset_id: UUID) -> DatasetRecord:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.research_datasets WHERE dataset_id=%s", (dataset_id,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(str(dataset_id))
        return DatasetRecord.model_validate(row)

    def list(self, workspace_id: UUID) -> list[DatasetRecord]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.research_datasets WHERE workspace_id=%s ORDER BY created_at, dataset_id", (workspace_id,))
            return [DatasetRecord.model_validate(row) for row in cur.fetchall()]


class PostgresResearchPlatformStore:
    """Durable dataset/extraction/chunk storage with pgvector hybrid search."""

    def __init__(self, connection_factory: Callable[[], Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    def save_extraction(self, extraction: dict[str, Any]) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.research_extractions
                (extraction_id,dataset_id,media_type,filename,extractor,extracted_text_hash,character_count,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (extraction["extraction_id"], extraction["dataset_id"], extraction["media_type"], extraction.get("filename"),
                 extraction["extractor"], extraction["extracted_text_hash"], extraction["character_count"], extraction["created_at"]),
            )

    def save_chunk(self, *, chunk_id: UUID, dataset_id: UUID, document_id: UUID, ordinal: int, text: str,
                   embedding: list[float], content_hash: str, metadata: dict[str, Any] | None = None) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.research_platform_chunks
                (chunk_id,dataset_id,document_id,ordinal,text,embedding,content_hash,metadata)
                VALUES (%s,%s,%s,%s,%s,%s::vector,%s,%s)""",
                (chunk_id, dataset_id, document_id, ordinal, text, _vector(embedding), content_hash, Jsonb(metadata or {})),
            )

    def hybrid_search(self, *, workspace_id: UUID, query: str, embedding: list[float], limit: int = 10,
                      candidate_limit: int = 40) -> list[RetrievalCandidate]:
        vector = _vector(embedding)
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """WITH vector_hits AS (
                    SELECT c.chunk_id,c.document_id,s.source_id,c.text,s.title,s.uri,
                           1 - (c.embedding <=> %s::vector) AS vector_score,
                           row_number() OVER (ORDER BY c.embedding <=> %s::vector) AS vrank
                    FROM public.research_platform_chunks c
                    JOIN public.research_documents d ON d.document_id=c.document_id
                    JOIN public.research_sources s ON s.source_id=d.source_id
                    WHERE d.workspace_id=%s
                    ORDER BY c.embedding <=> %s::vector LIMIT %s
                ), lexical_hits AS (
                    SELECT c.chunk_id,
                           ts_rank_cd(to_tsvector('simple', coalesce(c.text,'')), plainto_tsquery('simple', %s)) AS lexical_score,
                           row_number() OVER (ORDER BY ts_rank_cd(to_tsvector('simple', coalesce(c.text,'')), plainto_tsquery('simple', %s)) DESC, c.chunk_id) AS lrank
                    FROM public.research_platform_chunks c
                    JOIN public.research_documents d ON d.document_id=c.document_id
                    WHERE d.workspace_id=%s
                      AND to_tsvector('simple', coalesce(c.text,'')) @@ plainto_tsquery('simple', %s)
                    ORDER BY lexical_score DESC LIMIT %s
                ), combined AS (
                    SELECT v.chunk_id,v.document_id,v.source_id,v.text,v.title,v.uri,v.vector_score,coalesce(l.lexical_score,0) AS lexical_score,
                           (1.0/(60+v.vrank)) + coalesce(1.0/(60+l.lrank),0) AS rrf
                    FROM vector_hits v LEFT JOIN lexical_hits l ON l.chunk_id=v.chunk_id
                    UNION ALL
                    SELECT l.chunk_id,c.document_id,s.source_id,c.text,s.title,s.uri,0.0,l.lexical_score,1.0/(60+l.lrank)
                    FROM lexical_hits l
                    JOIN public.research_platform_chunks c ON c.chunk_id=l.chunk_id
                    JOIN public.research_documents d ON d.document_id=c.document_id
                    JOIN public.research_sources s ON s.source_id=d.source_id
                    WHERE NOT EXISTS (SELECT 1 FROM vector_hits v WHERE v.chunk_id=l.chunk_id)
                )
                SELECT DISTINCT ON (chunk_id) chunk_id,document_id,source_id,text,title,uri,vector_score,lexical_score
                FROM combined ORDER BY chunk_id,rrf DESC""",
                (vector, vector, workspace_id, vector, candidate_limit, query, query, workspace_id, query, candidate_limit),
            )
            rows = cur.fetchall()
        return [RetrievalCandidate(chunk_id=row["chunk_id"], document_id=row["document_id"], source_id=row["source_id"],
                                   text=row["text"], title=row["title"], uri=row["uri"], vector_score=float(row["vector_score"]),
                                   lexical_score=float(row["lexical_score"])) for row in rows[:limit]]
