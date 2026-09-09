"""Phase 17 dataset, ingestion, hybrid retrieval and reproducible report APIs."""
from __future__ import annotations

import json
import os
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .research_intelligence import DeterministicEmbeddingProvider, ResearchIntelligence
from .research_platform import (
    DatasetRecord,
    ExtractionRecord,
    InMemoryDatasetRegistry,
    OpenAIEmbeddingProvider,
    ResearchPlatformError,
    RetrievalCandidate,
    TextExtractionPipeline,
    build_report,
    citation_id_for,
    rerank,
    validate_citations,
)
from .research_platform_persistence import PostgresDatasetRegistry, PostgresResearchPlatformStore
from .security import Permission, require_workspace_membership

router = APIRouter(prefix="/api/research-platform", tags=["research-platform"])


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    source_uri: str = Field(min_length=1, max_length=2000)
    content: str = Field(min_length=1, max_length=2_000_000)
    schema_definition: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    dataset_id: UUID
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    media_type: str = Field(default="text/plain", min_length=1, max_length=200)
    filename: str | None = Field(default=None, max_length=500)
    uri: str = Field(min_length=1, max_length=2000)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    query: str = Field(min_length=1, max_length=10_000)
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=10, ge=1, le=50)
    candidate_limit: int = Field(default=40, ge=1, le=200)


class ReportRequest(SearchRequest):
    answer: str = Field(min_length=1, max_length=100_000)


class ResearchPlatformServices:
    def __init__(self, database_dsn: str | None = None, production: bool = False) -> None:
        self.production = production
        if database_dsn:
            from .service_adapters import production_connection_factory_from_dsn
            factory = production_connection_factory_from_dsn(database_dsn)
            self.datasets: Any = PostgresDatasetRegistry(factory)
            self.store: Any = PostgresResearchPlatformStore(factory)
        else:
            self.datasets = InMemoryDatasetRegistry()
            self.store = None
        api_key = os.getenv("OPENAI_API_KEY")
        if production and not api_key:
            raise ResearchPlatformError("OPENAI_API_KEY is required in production for real embeddings")
        self.embedder = OpenAIEmbeddingProvider(api_key=api_key) if api_key else DeterministicEmbeddingProvider()
        self.extractor = TextExtractionPipeline()
        self.engine = ResearchIntelligence()
        self.documents: dict[UUID, UUID] = {}


def _services(request: Request) -> ResearchPlatformServices:
    return cast(ResearchPlatformServices, request.app.state.research_platform)


@router.post("/datasets", response_model=DatasetRecord, status_code=201)
def register_dataset(payload: DatasetCreate, request: Request) -> DatasetRecord:
    require_workspace_membership(request, payload.workspace_id, Permission.RESEARCH_WRITE)
    content_hash = sha256(payload.content.encode("utf-8")).hexdigest()
    schema_hash = sha256(json.dumps(payload.schema_definition, sort_keys=True).encode()).hexdigest()
    versions = _services(request).datasets.list(payload.workspace_id)
    version = max((x.version for x in versions if x.name == payload.name), default=0) + 1
    dataset = DatasetRecord(workspace_id=payload.workspace_id, name=payload.name, version=version,
                            source_uri=payload.source_uri, content_hash=content_hash, schema_hash=schema_hash,
                            metadata=payload.metadata)
    result = _services(request).datasets.register(dataset)
    return cast(DatasetRecord, result)


@router.get("/datasets", response_model=list[DatasetRecord])
def list_datasets(request: Request, workspace_id: UUID) -> list[DatasetRecord]:
    require_workspace_membership(request, workspace_id, Permission.WORKSPACE_READ)
    result = _services(request).datasets.list(workspace_id)
    return cast(list[DatasetRecord], result)


@router.post("/ingest", response_model=ExtractionRecord, status_code=201)
def ingest(payload: IngestRequest, request: Request) -> ExtractionRecord:
    require_workspace_membership(request, payload.workspace_id, Permission.RESEARCH_WRITE)
    services = _services(request)
    dataset = services.datasets.get(payload.dataset_id)
    if dataset.workspace_id != payload.workspace_id:
        raise HTTPException(status_code=404, detail="dataset not found")
    try:
        text, extractor_name = services.extractor.extract(payload.content.encode("utf-8"), payload.media_type, payload.filename)
        document = services.engine.ingest_text(title=payload.title, text=text, uri=payload.uri,
                                               workspace_id=payload.workspace_id, source_type="research-platform")
        services.documents[document.document_id] = dataset.dataset_id
        chunks = services.engine.store.list_chunks(document.document_id)
        if services.store is not None:
            for chunk in chunks:
                services.store.save_chunk(chunk_id=chunk.chunk_id, dataset_id=dataset.dataset_id,
                                          document_id=document.document_id, ordinal=chunk.ordinal, text=chunk.text,
                                          embedding=services.embedder.embed(chunk.text), content_hash=chunk.content_hash)
        extraction = ExtractionRecord(dataset_id=dataset.dataset_id, media_type=payload.media_type,
                                      filename=payload.filename, extractor=extractor_name,
                                      extracted_text_hash=sha256(text.encode()).hexdigest(), character_count=len(text))
        if services.store is not None:
            services.store.save_extraction(extraction.model_dump())
        return extraction
    except ResearchPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/search")
def search(payload: SearchRequest, request: Request) -> list[dict[str, Any]]:
    require_workspace_membership(request, payload.workspace_id, Permission.WORKSPACE_READ)
    services = _services(request)
    query_vector = services.embedder.embed(payload.query)
    if services.store is not None:
        hits = services.store.hybrid_search(workspace_id=payload.workspace_id, query=payload.query,
                                            embedding=query_vector, limit=payload.candidate_limit,
                                            candidate_limit=payload.candidate_limit)
        ranked = rerank(payload.query, hits, payload.limit)
    else:
        hits = services.engine.search(payload.query, limit=payload.candidate_limit, workspace_id=payload.workspace_id)
        ranked = [RetrievalCandidate(chunk_id=h.chunk.chunk_id, document_id=h.document.document_id,
                                     source_id=h.source.source_id, text=h.chunk.text, title=h.source.title,
                                     uri=h.source.uri, vector_score=h.score, lexical_score=0.0) for h in hits]
        ranked = rerank(payload.query, ranked, payload.limit)
    allowed = set(payload.dataset_ids)
    results: list[dict[str, Any]] = []
    for hit in ranked:
        dataset_id = services.documents.get(hit.document_id)
        if allowed and dataset_id not in allowed:
            continue
        cid = citation_id_for(hit.source_id, hit.chunk_id)
        results.append({"citation_id": cid, "chunk_id": str(hit.chunk_id), "document_id": str(hit.document_id),
                        "dataset_id": str(dataset_id) if dataset_id else None, "title": hit.title, "uri": hit.uri,
                        "text": hit.text, "vector_score": hit.vector_score, "lexical_score": hit.lexical_score,
                        "quote": " ".join(hit.text.split())[:1000]})
    return results[:payload.limit]


@router.post("/reports")
def create_report(payload: ReportRequest, request: Request) -> dict[str, Any]:
    require_workspace_membership(request, payload.workspace_id, Permission.RESEARCH_WRITE)
    evidence = search(SearchRequest(**payload.model_dump(exclude={"answer"})), request)
    citations = [{"citation_id": x["citation_id"], "chunk_id": x["chunk_id"], "document_id": x["document_id"],
                  "dataset_id": x["dataset_id"], "title": x["title"], "uri": x["uri"], "quote": x["quote"]}
                 for x in evidence]
    evidence_map = {x["citation_id"]: x["text"] for x in evidence}
    validations = validate_citations(citations, evidence_map)
    if not all(x.valid for x in validations):
        raise HTTPException(status_code=422, detail="citation validation failed")
    dataset_ids = [UUID(x["dataset_id"]) for x in evidence if x["dataset_id"]]
    provider = {"name": _services(request).embedder.name, "model": _services(request).embedder.model,
                "dimensions": _services(request).embedder.dimensions}
    config = {"limit": payload.limit, "candidate_limit": payload.candidate_limit,
              "reranker": "deterministic-overlap-v1", "hybrid": True}
    report = build_report(workspace_id=payload.workspace_id, query=payload.query, answer=payload.answer,
                          citations=citations, evidence=evidence_map, dataset_ids=dataset_ids,
                          retrieval_config=config, provider=provider)
    return report.model_dump(mode="json") | {"citation_validation": [x.model_dump() for x in validations]}
