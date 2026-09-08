"""Phase 8 knowledge and research intelligence primitives."""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ResearchIntelligenceError(RuntimeError):
    """Base error for Phase 8 research intelligence failures."""


class DocumentIngestionError(ResearchIntelligenceError):
    """Raised when a document cannot be safely ingested."""


class EmbeddingProvider(ABC):
    """Provider-neutral embedding contract."""

    name: str
    dimensions: int

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable offline hashing embedding for tests and no-key environments."""

    name = "deterministic-hash"
    dimensions = 384

    def embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9][a-z0-9_'-]*", text.lower())
        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class TextExtractor(Protocol):
    def extract(self, content: bytes, media_type: str, filename: str | None = None) -> str: ...


class BasicTextExtractor:
    """Dependency-light extractor for supported UTF-8 text formats."""

    allowed_media_types = {"text/plain", "text/markdown", "text/csv", "application/json", "application/octet-stream"}

    def extract(self, content: bytes, media_type: str, filename: str | None = None) -> str:
        suffix = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
        if media_type not in self.allowed_media_types and suffix not in {"txt", "md", "csv", "json"}:
            raise DocumentIngestionError("unsupported document type; Phase 8 accepts text, markdown, CSV and JSON")
        try:
            return content.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise DocumentIngestionError("document must be UTF-8 text") from exc


class DocumentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID = Field(default_factory=uuid4)
    uri: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_type: str = Field(default="document", min_length=1, max_length=100)
    checksum: str = Field(min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID | None = None
    source_id: UUID
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=2_000_000)
    version: int = Field(default=1, ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=50_000)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    embedding: list[float] = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(pattern=r"^SRC-[0-9A-F]{12}$")
    source_id: UUID
    document_id: UUID
    chunk_id: UUID
    locator: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=500)
    uri: str = Field(min_length=1, max_length=2000)
    relevance: float = Field(ge=0.0, le=1.0)


class ResearchSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthesis_id: UUID = Field(default_factory=uuid4)
    query: str = Field(min_length=1, max_length=10_000)
    answer: str = Field(min_length=1, max_length=100_000)
    citations: list[Citation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    method: str = Field(default="extractive-deterministic", min_length=1, max_length=100)


@dataclass(frozen=True)
class SearchHit:
    chunk: ResearchChunk
    document: ResearchDocument
    source: DocumentSource
    score: float


class ResearchIntelligenceStore(Protocol):
    def save_source(self, source: DocumentSource) -> DocumentSource: ...
    def save_document(self, document: ResearchDocument) -> ResearchDocument: ...
    def save_chunks(self, chunks: list[ResearchChunk]) -> list[ResearchChunk]: ...
    def get_document(self, document_id: UUID) -> ResearchDocument: ...
    def list_sources(self, workspace_id: UUID | None = None) -> list[DocumentSource]: ...
    def list_documents(self, workspace_id: UUID | None = None) -> list[ResearchDocument]: ...
    def list_chunks(self, document_id: UUID | None = None) -> list[ResearchChunk]: ...


@dataclass
class InMemoryResearchIntelligenceStore:
    sources: dict[UUID, DocumentSource] = field(default_factory=dict)
    documents: dict[UUID, ResearchDocument] = field(default_factory=dict)
    chunks: dict[UUID, ResearchChunk] = field(default_factory=dict)

    def save_source(self, source: DocumentSource) -> DocumentSource:
        self.sources[source.source_id] = source
        return source

    def save_document(self, document: ResearchDocument) -> ResearchDocument:
        previous = self.documents.get(document.document_id)
        if previous is not None:
            document.version = previous.version + 1
        self.documents[document.document_id] = document
        return document

    def save_chunks(self, chunks: list[ResearchChunk]) -> list[ResearchChunk]:
        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk
        return chunks

    def get_document(self, document_id: UUID) -> ResearchDocument:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise KeyError(str(document_id)) from exc

    def list_sources(self, workspace_id: UUID | None = None) -> list[DocumentSource]:
        if workspace_id is None:
            return list(self.sources.values())
        source_ids = {doc.source_id for doc in self.documents.values() if doc.workspace_id == workspace_id}
        return [source for source in self.sources.values() if source.source_id in source_ids]

    def list_documents(self, workspace_id: UUID | None = None) -> list[ResearchDocument]:
        values = [doc for doc in self.documents.values() if workspace_id is None or doc.workspace_id == workspace_id]
        return sorted(values, key=lambda doc: (doc.created_at, str(doc.document_id)))

    def list_chunks(self, document_id: UUID | None = None) -> list[ResearchChunk]:
        values = [chunk for chunk in self.chunks.values() if document_id is None or chunk.document_id == document_id]
        return sorted(values, key=lambda chunk: (chunk.document_id, chunk.ordinal))


class ResearchIntelligence:
    """Ingest, index, retrieve and synthesize evidence with explicit provenance."""

    def __init__(self, store: ResearchIntelligenceStore | None = None, embedder: EmbeddingProvider | None = None,
                 extractor: TextExtractor | None = None, chunk_size: int = 1200, chunk_overlap: int = 180) -> None:
        if chunk_size < 200:
            raise ValueError("chunk_size must be at least 200")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size-1")
        self.store = store or InMemoryResearchIntelligenceStore()
        self.embedder = embedder or DeterministicEmbeddingProvider()
        self.extractor = extractor or BasicTextExtractor()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def ingest_text(self, *, title: str, text: str, uri: str, workspace_id: UUID | None = None,
                    publisher: str | None = None, author: str | None = None,
                    published_at: datetime | None = None, source_type: str = "document",
                    metadata: dict[str, Any] | None = None) -> ResearchDocument:
        clean = self._normalize(text)
        if not clean:
            raise DocumentIngestionError("document text must not be empty")
        checksum = sha256(clean.encode("utf-8")).hexdigest()
        source = DocumentSource(uri=uri, title=title, publisher=publisher, author=author,
                                published_at=published_at, source_type=source_type, checksum=checksum,
                                metadata=metadata or {})
        document = ResearchDocument(workspace_id=workspace_id, source_id=source.source_id, title=title,
                                    text=clean, content_hash=checksum, metadata=metadata or {})
        self.store.save_source(source)
        self.store.save_document(document)
        self.store.save_chunks(self._chunk(document))
        return document

    def ingest_bytes(self, *, title: str, content: bytes, uri: str, media_type: str,
                     filename: str | None = None, workspace_id: UUID | None = None,
                     metadata: dict[str, Any] | None = None) -> ResearchDocument:
        text = self.extractor.extract(content, media_type, filename)
        return self.ingest_text(title=title, text=text, uri=uri, workspace_id=workspace_id,
                                source_type="uploaded_document", metadata=metadata)

    def search(self, query: str, *, limit: int = 10, workspace_id: UUID | None = None) -> list[SearchHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        query_vector = self.embedder.embed(query)
        documents = {doc.document_id: doc for doc in self.store.list_documents(workspace_id)}
        sources = {source.source_id: source for source in self.store.list_sources(workspace_id)}
        hits: list[SearchHit] = []
        for chunk in self.store.list_chunks():
            document = documents.get(chunk.document_id)
            if document is None:
                continue
            source = sources.get(document.source_id)
            if source is None:
                continue
            score = _cosine(query_vector, chunk.embedding)
            if score > 0:
                hits.append(SearchHit(chunk, document, source, score))
        hits.sort(key=lambda hit: (-hit.score, str(hit.chunk.chunk_id)))
        return hits[:limit]

    def synthesize(self, query: str, *, limit: int = 8, workspace_id: UUID | None = None) -> ResearchSynthesis:
        hits = self.search(query, limit=limit, workspace_id=workspace_id)
        if not hits:
            return ResearchSynthesis(query=query, answer="No indexed evidence matched the research question.")
        citations: list[Citation] = []
        lines: list[str] = []
        for hit in hits:
            citation_id = "SRC-" + sha256(str(hit.source.source_id).encode("utf-8")).hexdigest()[:12].upper()
            quote = _evidence_quote(hit.chunk.text)
            citations.append(Citation(citation_id=citation_id, source_id=hit.source.source_id,
                                      document_id=hit.document.document_id, chunk_id=hit.chunk.chunk_id,
                                      locator=f"chunk {hit.chunk.ordinal + 1} ({hit.chunk.start_char}:{hit.chunk.end_char})",
                                      quote=quote, title=hit.source.title, uri=hit.source.uri,
                                      relevance=round(max(0.0, min(1.0, hit.score)), 6)))
            lines.append(f"[{citation_id}] {quote}")
        answer = (f"Research synthesis for: {query.strip()}\n\n"
                  "The indexed evidence most relevant to this question is:\n"
                  + "\n".join(f"- {line}" for line in lines)
                  + "\n\nThis synthesis is evidence-grounded and extractive; each statement above is traceable to its cited source chunk.")
        return ResearchSynthesis(query=query, answer=answer, citations=citations)

    def provenance(self, document_id: UUID) -> dict[str, Any]:
        document = self.store.get_document(document_id)
        source = next((item for item in self.store.list_sources() if item.source_id == document.source_id), None)
        if source is None:
            raise ResearchIntelligenceError("document source provenance is missing")
        return {"document": document.model_dump(mode="json"), "source": source.model_dump(mode="json"),
                "chunks": [chunk.model_dump(mode="json") for chunk in self.store.list_chunks(document_id)]}

    def _chunk(self, document: ResearchDocument) -> list[ResearchChunk]:
        text = document.text
        step = self.chunk_size - self.chunk_overlap
        chunks: list[ResearchChunk] = []
        ordinal = 0
        start = 0
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            if end < len(text):
                boundary = text.rfind(" ", start + self.chunk_size // 2, end)
                if boundary > start:
                    end = boundary
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(ResearchChunk(document_id=document.document_id, ordinal=ordinal, text=chunk_text,
                                            start_char=start, end_char=end, embedding=self.embedder.embed(chunk_text),
                                            content_hash=sha256(chunk_text.encode("utf-8")).hexdigest()))
                ordinal += 1
            if end >= len(text):
                break
            start = max(start + step, end - self.chunk_overlap)
        return chunks

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text.replace("\x00", "")).strip()


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _evidence_quote(text: str) -> str:
    clean = " ".join(text.split())
    return clean[:997] + "..." if len(clean) > 1000 else clean
