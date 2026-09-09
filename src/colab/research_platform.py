"""Phase 17 research platform: datasets, real embeddings, retrieval, citations and reports."""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ResearchPlatformError(RuntimeError):
    """Base error for research platform failures."""


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider:
    """Real remote embedding provider using the OpenAI embeddings HTTP API."""

    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None, dimensions: int = 1536) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("COLAB_EMBEDDING_MODEL", "text-embedding-3-small")
        self.dimensions = dimensions
        if not self.api_key:
            raise ResearchPlatformError("OPENAI_API_KEY is required for the real embedding provider")

    def embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        request = urllib.request.Request(
            os.getenv("COLAB_EMBEDDING_URL", "https://api.openai.com/v1/embeddings"),
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=float(os.getenv("COLAB_EMBEDDING_TIMEOUT", "30"))) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ResearchPlatformError("embedding provider request failed") from exc
        try:
            vector = [float(value) for value in body["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ResearchPlatformError("embedding provider returned an invalid response") from exc
        if len(vector) != self.dimensions:
            raise ResearchPlatformError(f"embedding dimension mismatch: expected {self.dimensions}, got {len(vector)}")
        return vector


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    source_uri: str = Field(min_length=1, max_length=2000)
    content_hash: str = Field(min_length=64, max_length=64)
    schema_hash: str = Field(min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExtractionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extraction_id: UUID = Field(default_factory=uuid4)
    dataset_id: UUID
    media_type: str = Field(min_length=1, max_length=200)
    filename: str | None = Field(default=None, max_length=500)
    extractor: str = Field(min_length=1, max_length=100)
    extracted_text_hash: str = Field(min_length=64, max_length=64)
    character_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CitationValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation_id: str
    valid: bool
    reason: str


class ResearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    query: str
    answer: str
    citations: list[dict[str, Any]]
    dataset_ids: list[UUID]
    retrieval_config: dict[str, Any]
    provider: dict[str, Any]
    reproducibility_hash: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DatasetRegistry(Protocol):
    def register(self, dataset: DatasetRecord) -> DatasetRecord: ...
    def get(self, dataset_id: UUID) -> DatasetRecord: ...
    def list(self, workspace_id: UUID) -> list[DatasetRecord]: ...


class InMemoryDatasetRegistry:
    def __init__(self) -> None:
        self._items: dict[UUID, DatasetRecord] = {}

    def register(self, dataset: DatasetRecord) -> DatasetRecord:
        self._items[dataset.dataset_id] = dataset
        return dataset

    def get(self, dataset_id: UUID) -> DatasetRecord:
        if dataset_id not in self._items:
            raise KeyError(str(dataset_id))
        return self._items[dataset_id]

    def list(self, workspace_id: UUID) -> list[DatasetRecord]:
        return sorted((x for x in self._items.values() if x.workspace_id == workspace_id), key=lambda x: (x.created_at, str(x.dataset_id)))


class TextExtractionPipeline:
    """Safe, dependency-light extraction for text, JSON, CSV and HTML."""

    def extract(self, content: bytes, media_type: str, filename: str | None = None) -> tuple[str, str]:
        suffix = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
        allowed = {"text/plain", "text/markdown", "text/csv", "application/json", "text/html", "application/octet-stream"}
        if media_type not in allowed and suffix not in {"txt", "md", "csv", "json", "html", "htm"}:
            raise ResearchPlatformError("unsupported media type for extraction")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchPlatformError("uploaded content must be UTF-8") from exc
        if media_type == "application/json" or suffix == "json":
            try:
                text = json.dumps(json.loads(text), sort_keys=True, ensure_ascii=False, indent=2)
            except json.JSONDecodeError as exc:
                raise ResearchPlatformError("invalid JSON document") from exc
        if media_type == "text/html" or suffix in {"html", "htm"}:
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)
            text = re.sub(r"&(?:nbsp|amp|lt|gt);", " ", text)
        text = re.sub(r"\x00", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            raise ResearchPlatformError("extraction produced empty text")
        return text, "utf8-text-v1"


def citation_id_for(source_id: UUID, chunk_id: UUID) -> str:
    return "CIT-" + sha256(f"{source_id}:{chunk_id}".encode()).hexdigest()[:12].upper()


def validate_citations(citations: list[dict[str, Any]], evidence: dict[str, str]) -> list[CitationValidation]:
    results: list[CitationValidation] = []
    for citation in citations:
        cid = str(citation.get("citation_id", ""))
        quote = str(citation.get("quote", ""))
        source_text = evidence.get(cid)
        if source_text is None:
            results.append(CitationValidation(citation_id=cid, valid=False, reason="citation target is missing"))
        elif not quote.strip() or quote.strip() not in source_text:
            results.append(CitationValidation(citation_id=cid, valid=False, reason="quoted evidence is not present in source chunk"))
        else:
            results.append(CitationValidation(citation_id=cid, valid=True, reason="citation resolves to indexed evidence"))
    return results


def reproducibility_hash(*, query: str, workspace_id: UUID, dataset_ids: list[UUID], retrieval_config: dict[str, Any], provider: dict[str, Any], citations: list[dict[str, Any]]) -> str:
    manifest = {
        "query": query,
        "workspace_id": str(workspace_id),
        "dataset_ids": sorted(str(x) for x in dataset_ids),
        "retrieval_config": retrieval_config,
        "provider": provider,
        "citations": citations,
    }
    return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    text: str
    title: str
    uri: str
    vector_score: float
    lexical_score: float


def reciprocal_rank_fusion(vector_rank: list[RetrievalCandidate], lexical_rank: list[RetrievalCandidate], k: int = 60) -> list[RetrievalCandidate]:
    scores: dict[UUID, float] = {}
    values: dict[UUID, RetrievalCandidate] = {}
    for rank, item in enumerate(vector_rank, 1):
        scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
        values[item.chunk_id] = item
    for rank, item in enumerate(lexical_rank, 1):
        scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
        values[item.chunk_id] = item
    return sorted(values.values(), key=lambda item: (-scores[item.chunk_id], str(item.chunk_id)))


def rerank(query: str, candidates: list[RetrievalCandidate], limit: int) -> list[RetrievalCandidate]:
    terms = set(re.findall(r"[a-z0-9][a-z0-9_-]*", query.lower()))
    scored: list[tuple[float, RetrievalCandidate]] = []
    for item in candidates:
        words = set(re.findall(r"[a-z0-9][a-z0-9_-]*", item.text.lower()))
        overlap = len(terms & words) / max(1, len(terms))
        score = 0.45 * item.vector_score + 0.35 * item.lexical_score + 0.20 * overlap
        scored.append((score, item))
    scored.sort(key=lambda x: (-x[0], str(x[1].chunk_id)))
    return [item for _, item in scored[:limit]]


def build_report(*, workspace_id: UUID, query: str, answer: str, citations: list[dict[str, Any]], dataset_ids: list[UUID], retrieval_config: dict[str, Any], provider: dict[str, Any]) -> ResearchReport:
    validations = validate_citations(citations, {str(c["citation_id"]): str(c.get("source_text", "")) for c in citations})
    invalid = [x for x in validations if not x.valid]
    if invalid:
        raise ResearchPlatformError("citation validation failed")
    digest = reproducibility_hash(query=query, workspace_id=workspace_id, dataset_ids=dataset_ids, retrieval_config=retrieval_config, provider=provider, citations=citations)
    return ResearchReport(workspace_id=workspace_id, query=query, answer=answer, citations=citations, dataset_ids=dataset_ids, retrieval_config=retrieval_config, provider=provider, reproducibility_hash=digest)
