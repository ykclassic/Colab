"""PostgreSQL persistence for Phase 8 research intelligence."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .research_intelligence import DocumentSource, ResearchChunk, ResearchDocument


class PostgresResearchIntelligenceStore:
    def __init__(self, connection_factory: Callable[[], Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    def save_source(self, source: DocumentSource) -> DocumentSource:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.research_sources
                (source_id,uri,title,publisher,author,published_at,retrieved_at,source_type,checksum,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id) DO UPDATE SET
                    uri=EXCLUDED.uri,title=EXCLUDED.title,publisher=EXCLUDED.publisher,
                    author=EXCLUDED.author,published_at=EXCLUDED.published_at,
                    retrieved_at=EXCLUDED.retrieved_at,source_type=EXCLUDED.source_type,
                    checksum=EXCLUDED.checksum,metadata=EXCLUDED.metadata
                RETURNING *""",
                (source.source_id, source.uri, source.title, source.publisher, source.author,
                 source.published_at, source.retrieved_at, source.source_type, source.checksum,
                 Jsonb(source.metadata)),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("research source upsert returned no row")
        return DocumentSource.model_validate(row)

    def save_document(self, document: ResearchDocument) -> ResearchDocument:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO public.research_documents
                (document_id,workspace_id,source_id,title,text,version,content_hash,created_at,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET
                    workspace_id=EXCLUDED.workspace_id,source_id=EXCLUDED.source_id,
                    title=EXCLUDED.title,text=EXCLUDED.text,version=research_documents.version+1,
                    content_hash=EXCLUDED.content_hash,metadata=EXCLUDED.metadata
                RETURNING *""",
                (document.document_id, document.workspace_id, document.source_id, document.title,
                 document.text, document.version, document.content_hash, document.created_at,
                 Jsonb(document.metadata)),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("research document upsert returned no row")
        return ResearchDocument.model_validate(row)

    def save_chunks(self, chunks: list[ResearchChunk]) -> list[ResearchChunk]:
        if not chunks:
            return []
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            document_id = chunks[0].document_id
            cur.execute("DELETE FROM public.research_chunks WHERE document_id=%s", (document_id,))
            for chunk in chunks:
                cur.execute(
                    """INSERT INTO public.research_chunks
                    (chunk_id,document_id,ordinal,text,start_char,end_char,embedding,content_hash,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (chunk.chunk_id, chunk.document_id, chunk.ordinal, chunk.text, chunk.start_char,
                     chunk.end_char, Jsonb(chunk.embedding), chunk.content_hash, chunk.created_at),
                )
        return chunks

    def get_document(self, document_id: UUID) -> ResearchDocument:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.research_documents WHERE document_id=%s", (document_id,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(str(document_id))
        return ResearchDocument.model_validate(row)

    def list_sources(self, workspace_id: UUID | None = None) -> list[DocumentSource]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            if workspace_id is None:
                cur.execute("SELECT * FROM public.research_sources ORDER BY retrieved_at DESC")
            else:
                cur.execute(
                    """SELECT s.* FROM public.research_sources s
                       JOIN public.research_documents d ON d.source_id=s.source_id
                       WHERE d.workspace_id=%s GROUP BY s.source_id ORDER BY max(s.retrieved_at) DESC""",
                    (workspace_id,),
                )
            return [DocumentSource.model_validate(row) for row in cur.fetchall()]

    def list_documents(self, workspace_id: UUID | None = None) -> list[ResearchDocument]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            if workspace_id is None:
                cur.execute("SELECT * FROM public.research_documents ORDER BY created_at, document_id")
            else:
                cur.execute(
                    "SELECT * FROM public.research_documents WHERE workspace_id=%s ORDER BY created_at, document_id",
                    (workspace_id,),
                )
            return [ResearchDocument.model_validate(row) for row in cur.fetchall()]

    def list_chunks(self, document_id: UUID | None = None) -> list[ResearchChunk]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            if document_id is None:
                cur.execute("SELECT * FROM public.research_chunks ORDER BY document_id, ordinal")
            else:
                cur.execute(
                    "SELECT * FROM public.research_chunks WHERE document_id=%s ORDER BY ordinal",
                    (document_id,),
                )
            return [ResearchChunk.model_validate(row) for row in cur.fetchall()]
