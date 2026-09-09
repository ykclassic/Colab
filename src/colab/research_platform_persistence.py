"""PostgreSQL persistence and pgvector hybrid retrieval for Phase 17/21D."""
from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .research_intelligence import DocumentSource, ResearchChunk, ResearchDocument
from .research_platform import DatasetRecord, ResearchReport, RetrievalCandidate


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
                ON CONFLICT (dataset_id) DO UPDATE SET
                    metadata=EXCLUDED.metadata
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
    """Durable source/document/chunk/report storage with pgvector hybrid search."""

    def __init__(self, connection_factory: Callable[[], Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    def save_source(self, source: DocumentSource) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.research_sources
                (source_id,uri,title,publisher,author,published_at,retrieved_at,source_type,checksum,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id) DO NOTHING""",
                (source.source_id, source.uri, source.title, source.publisher, source.author,
                 source.published_at, source.retrieved_at, source.source_type, source.checksum, Jsonb(source.metadata)),
            )

    def save_document(self, document: ResearchDocument) -> None:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.research_documents
                (document_id,workspace_id,source_id,title,text,version,content_hash,created_at,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO NOTHING""",
                (document.document_id, document.workspace_id, document.source_id, document.title,
                 document.text, document.version, document.content_hash, document.created_at, Jsonb(document.metadata)),
            )

    def save_chunks(self, chunks: list[ResearchChunk], dataset_id: UUID) -> None:
        if not chunks:
            return
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            for chunk in chunks:
                cur.execute(
                    """INSERT INTO public.research_platform_chunks
                    (chunk_id,dataset_id,document_id,ordinal,text,embedding,content_hash,metadata)
                    VALUES (%s,%s,%s,%s,%s,%s::vector,%s,%s)
                    ON CONFLICT (chunk_id) DO NOTHING""",
                    (chunk.chunk_id, dataset_id, chunk.document_id, chunk.ordinal, chunk.text,
                     _vector(chunk.embedding), chunk.content_hash, Jsonb({"start_char": chunk.start_char, "end_char": chunk.end_char})),
                )

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

    def save_report(self, report: ResearchReport, *, pipeline_hash: str) -> ResearchReport:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.research_reports
                (report_id,workspace_id,query,answer,citations,dataset_ids,retrieval_config,provider,reproducibility_hash,pipeline_hash,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *""",
                (report.report_id, report.workspace_id, report.query, report.answer, Jsonb(report.citations),
                 Jsonb([str(x) for x in report.dataset_ids]), Jsonb(report.retrieval_config), Jsonb(report.provider),
                 report.reproducibility_hash, pipeline_hash, report.generated_at),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("research report insert returned no row")
        return report

    def get_report(self, report_id: UUID, workspace_id: UUID) -> ResearchReport:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.research_reports WHERE report_id=%s AND workspace_id=%s", (report_id, workspace_id))
            row = cur.fetchone()
        if row is None:
            raise KeyError(str(report_id))
        return ResearchReport(
            report_id=row["report_id"], workspace_id=row["workspace_id"], query=row["query"], answer=row["answer"],
            citations=row["citations"], dataset_ids=[UUID(x) for x in row["dataset_ids"]],
            retrieval_config=row["retrieval_config"], provider=row["provider"],
            reproducibility_hash=row["reproducibility_hash"], generated_at=row["created_at"],
        )

    def hybrid_search(self, *, workspace_id: UUID, query: str, embedding: list[float], limit: int = 10,
                      candidate_limit: int = 40, dataset_ids: list[UUID] | None = None) -> list[RetrievalCandidate]:
        vector = _vector(embedding)
        dataset_filter = dataset_ids or []
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """WITH vector_hits AS (
                    SELECT c.chunk_id,c.document_id,c.dataset_id,s.source_id,c.text,s.title,s.uri,
                           1 - (c.embedding <=> %s::vector) AS vector_score,
                           row_number() OVER (ORDER BY c.embedding <=> %s::vector) AS vrank
                    FROM public.research_platform_chunks c
                    JOIN public.research_documents d ON d.document_id=c.document_id
                    JOIN public.research_sources s ON s.source_id=d.source_id
                    WHERE d.workspace_id=%s AND (%s::uuid[] = '{}'::uuid[] OR c.dataset_id = ANY(%s::uuid[]))
                    ORDER BY c.embedding <=> %s::vector LIMIT %s
                ), lexical_hits AS (
                    SELECT c.chunk_id,c.dataset_id,
                           ts_rank_cd(to_tsvector('simple', coalesce(c.text,'')), plainto_tsquery('simple', %s)) AS lexical_score,
                           row_number() OVER (ORDER BY ts_rank_cd(to_tsvector('simple', coalesce(c.text,'')), plainto_tsquery('simple', %s)) DESC, c.chunk_id) AS lrank
                    FROM public.research_platform_chunks c
                    JOIN public.research_documents d ON d.document_id=c.document_id
                    WHERE d.workspace_id=%s AND (%s::uuid[] = '{}'::uuid[] OR c.dataset_id = ANY(%s::uuid[]))
                      AND to_tsvector('simple', coalesce(c.text,'')) @@ plainto_tsquery('simple', %s)
                    ORDER BY lexical_score DESC LIMIT %s
                ), combined AS (
                    SELECT v.chunk_id,v.document_id,v.dataset_id,v.source_id,v.text,v.title,v.uri,v.vector_score,coalesce(l.lexical_score,0) AS lexical_score,
                           (1.0/(60+v.vrank)) + coalesce(1.0/(60+l.lrank),0) AS rrf
                    FROM vector_hits v LEFT JOIN lexical_hits l ON l.chunk_id=v.chunk_id
                    UNION ALL
                    SELECT l.chunk_id,c.document_id,l.dataset_id,s.source_id,c.text,s.title,s.uri,0.0,l.lexical_score,1.0/(60+l.lrank)
                    FROM lexical_hits l
                    JOIN public.research_platform_chunks c ON c.chunk_id=l.chunk_id
                    JOIN public.research_documents d ON d.document_id=c.document_id
                    JOIN public.research_sources s ON s.source_id=d.source_id
                    WHERE NOT EXISTS (SELECT 1 FROM vector_hits v WHERE v.chunk_id=l.chunk_id)
                )
                SELECT DISTINCT ON (chunk_id) chunk_id,document_id,source_id,dataset_id,text,title,uri,vector_score,lexical_score
                FROM combined ORDER BY chunk_id,rrf DESC LIMIT %s""",
                (vector, vector, workspace_id, dataset_filter, dataset_filter, vector, candidate_limit,
                 query, query, workspace_id, dataset_filter, dataset_filter, query, candidate_limit, candidate_limit),
            )
            rows = cur.fetchall()
        return [RetrievalCandidate(chunk_id=row["chunk_id"], document_id=row["document_id"], source_id=row["source_id"],
                                   text=row["text"], title=row["title"], uri=row["uri"], vector_score=float(row["vector_score"]),
                                   lexical_score=float(row["lexical_score"])) for row in rows]
