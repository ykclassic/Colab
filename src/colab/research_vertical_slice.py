"""Phase 21D end-to-end research vertical slice orchestration."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .research_platform import (
    CitationValidation,
    DatasetRecord,
    ResearchPlatformError,
    ResearchReport,
    RetrievalCandidate,
    TextExtractionPipeline,
    build_report,
    citation_id_for,
    rerank,
    validate_citations,
)


@dataclass(frozen=True)
class ResearchChunkRecord:
    chunk_id: UUID
    dataset_id: UUID
    ordinal: int
    text: str
    content_hash: str
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class ResearchRun:
    run_id: UUID
    workspace_id: UUID
    dataset: DatasetRecord
    extraction_hash: str
    normalized_hash: str
    chunks: tuple[ResearchChunkRecord, ...]
    candidates: tuple[RetrievalCandidate, ...]
    ranked: tuple[RetrievalCandidate, ...]
    citations: tuple[dict[str, Any], ...]
    validations: tuple[CitationValidation, ...]
    report: ResearchReport
    reproducibility_hash: str
    created_at: datetime


class InMemoryResearchRunStore:
    """Repository-shaped store used for deterministic tests and local development."""

    def __init__(self) -> None:
        self._runs: dict[UUID, ResearchRun] = {}

    def save(self, run: ResearchRun) -> ResearchRun:
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: UUID) -> ResearchRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(str(run_id)) from exc

    def list(self, workspace_id: UUID) -> list[ResearchRun]:
        return sorted(
            (run for run in self._runs.values() if run.workspace_id == workspace_id),
            key=lambda run: (run.created_at, str(run.run_id)),
        )


class ResearchVerticalSlice:
    """Execute upload through report as one deterministic research run."""

    def __init__(self, *, embedding_provider: Any, extractor: TextExtractionPipeline | None = None,
                 store: InMemoryResearchRunStore | None = None, chunk_size: int = 1200,
                 chunk_overlap: int = 180) -> None:
        if chunk_size < 200:
            raise ValueError("chunk_size must be at least 200")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size-1")
        self.embedding_provider = embedding_provider
        self.extractor = extractor or TextExtractionPipeline()
        self.store = store or InMemoryResearchRunStore()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def run(self, *, workspace_id: UUID, dataset_name: str, source_uri: str,
            title: str, content: bytes, media_type: str, filename: str | None = None,
            query: str, schema_definition: dict[str, Any] | None = None,
            metadata: dict[str, Any] | None = None, limit: int = 8,
            candidate_limit: int = 40, answer: str | None = None) -> ResearchRun:
        if not query.strip():
            raise ResearchPlatformError("research query must not be empty")
        if limit < 1 or candidate_limit < limit:
            raise ValueError("candidate_limit must be >= limit and both must be positive")

        extracted, extractor_version = self.extractor.extract(content, media_type, filename)
        normalized = self._normalize(extracted)
        normalized_hash = sha256(normalized.encode("utf-8")).hexdigest()
        extraction_hash = sha256(extracted.encode("utf-8")).hexdigest()
        dataset_id = uuid5(NAMESPACE_URL, f"{workspace_id}:{dataset_name}:{normalized_hash}")
        dataset = DatasetRecord(
            dataset_id=dataset_id, workspace_id=workspace_id, name=dataset_name, version=1,
            source_uri=source_uri, content_hash=normalized_hash,
            schema_hash=sha256(json.dumps(schema_definition or {}, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            metadata={**(metadata or {}), "extractor": extractor_version},
        )

        chunks = tuple(self._chunks(dataset.dataset_id, normalized))
        if not chunks:
            raise ResearchPlatformError("document produced no research chunks")
        query_vector = self.embedding_provider.embed(query)
        candidates = tuple(self._hybrid_candidates(query, chunks, query_vector, title, source_uri))[:candidate_limit]
        ranked = tuple(rerank(query, list(candidates), limit))
        if not ranked:
            raise ResearchPlatformError("research query produced no evidence")

        citations: list[dict[str, Any]] = []
        evidence: dict[str, str] = {}
        for hit in ranked:
            citation_id = citation_id_for(hit.source_id, hit.chunk_id)
            quote = " ".join(hit.text.split())[:1000]
            citations.append({
                "citation_id": citation_id, "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id), "dataset_id": str(dataset.dataset_id),
                "title": hit.title, "uri": hit.uri, "quote": quote,
            })
            evidence[citation_id] = hit.text
        validations = tuple(validate_citations(citations, evidence))
        if not all(item.valid for item in validations):
            raise ResearchPlatformError("citation validation failed")

        provider = {"name": self.embedding_provider.name, "model": self.embedding_provider.model,
                    "dimensions": self.embedding_provider.dimensions}
        retrieval_config = {
            "hybrid": True, "rrf_k": 60, "candidate_limit": candidate_limit, "limit": limit,
            "reranker": "deterministic-overlap-v1", "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }
        report = build_report(
            workspace_id=workspace_id, query=query,
            answer=answer or self._extractive_answer(query, ranked, citations),
            citations=citations, evidence=evidence, dataset_ids=[dataset.dataset_id],
            retrieval_config=retrieval_config, provider=provider,
        )
        reproducibility_hash = self._run_hash(
            workspace_id, dataset, extraction_hash, normalized_hash, chunks, query,
            retrieval_config, provider, citations, report.reproducibility_hash,
        )
        run = ResearchRun(
            run_id=uuid4(), workspace_id=workspace_id, dataset=dataset,
            extraction_hash=extraction_hash, normalized_hash=normalized_hash,
            chunks=chunks, candidates=candidates, ranked=ranked,
            citations=tuple(citations), validations=validations, report=report,
            reproducibility_hash=reproducibility_hash, created_at=datetime.now(UTC),
        )
        return self.store.save(run)

    def _chunks(self, dataset_id: UUID, text: str) -> list[ResearchChunkRecord]:
        chunks: list[ResearchChunkRecord] = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        ordinal = 0
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            if end < len(text):
                boundary = text.rfind(" ", start + self.chunk_size // 2, end)
                if boundary > start:
                    end = boundary
            chunk_text = text[start:end].strip()
            if chunk_text:
                content_hash = sha256(chunk_text.encode("utf-8")).hexdigest()
                chunk_id = uuid5(NAMESPACE_URL, f"{dataset_id}:{ordinal}:{content_hash}")
                chunks.append(ResearchChunkRecord(
                    chunk_id=chunk_id, dataset_id=dataset_id, ordinal=ordinal,
                    text=chunk_text, content_hash=content_hash,
                    embedding=tuple(self.embedding_provider.embed(chunk_text)),
                ))
                ordinal += 1
            if end >= len(text):
                break
            start = max(start + step, end - self.chunk_overlap)
        return chunks

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text.replace("\x00", ""))).strip()

    @staticmethod
    def _hybrid_candidates(query: str, chunks: tuple[ResearchChunkRecord, ...],
                           query_vector: list[float], title: str, uri: str) -> list[RetrievalCandidate]:
        terms = set(re.findall(r"[a-z0-9][a-z0-9_-]*", query.lower()))
        vector_scores = [(chunk, _cosine(query_vector, list(chunk.embedding))) for chunk in chunks]
        lexical_scores = []
        for chunk in chunks:
            words = set(re.findall(r"[a-z0-9][a-z0-9_-]*", chunk.text.lower()))
            lexical_scores.append((chunk, len(terms & words) / max(1, len(terms))))
        vector_rank = [x for x, _ in sorted(vector_scores, key=lambda item: (-item[1], str(item[0].chunk_id)))]
        lexical_rank = [x for x, _ in sorted(lexical_scores, key=lambda item: (-item[1], str(item[0].chunk_id)))]
        vector_by_id = dict(vector_scores)
        lexical_by_id = dict(lexical_scores)
        rank_v = {chunk.chunk_id: index for index, chunk in enumerate(vector_rank, 1)}
        rank_l = {chunk.chunk_id: index for index, chunk in enumerate(lexical_rank, 1)}
        ordered = sorted(
            chunks,
            key=lambda chunk: (-(1 / (60 + rank_v[chunk.chunk_id]) + 1 / (60 + rank_l[chunk.chunk_id])), str(chunk.chunk_id)),
        )
        source_id = uuid5(NAMESPACE_URL, uri)
        return [RetrievalCandidate(
            chunk_id=chunk.chunk_id, document_id=uuid5(NAMESPACE_URL, f"document:{chunk.dataset_id}"),
            source_id=source_id, text=chunk.text, title=title, uri=uri,
            vector_score=vector_by_id[chunk], lexical_score=lexical_by_id[chunk],
        ) for chunk in ordered]

    @staticmethod
    def _extractive_answer(query: str, ranked: tuple[RetrievalCandidate, ...], citations: list[dict[str, Any]]) -> str:
        lines = [f"Research synthesis for: {query.strip()}"]
        for hit, citation in zip(ranked, citations, strict=True):
            lines.append(f"[{citation['citation_id']}] {' '.join(hit.text.split())[:1000]}")
        return "\n\n".join(lines)

    @staticmethod
    def _run_hash(workspace_id: UUID, dataset: DatasetRecord, extraction_hash: str,
                  normalized_hash: str, chunks: tuple[ResearchChunkRecord, ...], query: str,
                  retrieval_config: dict[str, Any], provider: dict[str, Any],
                  citations: list[dict[str, Any]], report_hash: str) -> str:
        manifest = {
            "workspace_id": str(workspace_id),
            "dataset": {"name": dataset.name, "version": dataset.version, "source_uri": dataset.source_uri,
                        "content_hash": dataset.content_hash, "schema_hash": dataset.schema_hash,
                        "metadata": dataset.metadata},
            "extraction_hash": extraction_hash, "normalized_hash": normalized_hash,
            "chunks": [{"hash": x.content_hash, "ordinal": x.ordinal} for x in chunks],
            "query": query, "retrieval_config": retrieval_config, "provider": provider,
            "citations": citations, "report_hash": report_hash,
        }
        return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(a * a for a in right) ** 0.5
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
