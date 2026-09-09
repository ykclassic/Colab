"""HTTP routes for Phase 8 Knowledge & Research Intelligence."""
from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .research_intelligence import (
    DocumentIngestionError,
    ResearchDocument,
    ResearchIntelligence,
    ResearchSynthesis,
)
from .security import Permission, require_workspace_membership

router = APIRouter(prefix="/api/research", tags=["research-intelligence"])


class DocumentIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=2_000_000)
    uri: str = Field(min_length=1, max_length=2000)
    workspace_id: UUID
    publisher: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    source_type: str = Field(default="document", min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=10, ge=1, le=100)
    workspace_id: UUID


def _engine(request: Request) -> ResearchIntelligence:
    return cast(ResearchIntelligence, request.app.state.research_intelligence)


def _authorize(request: Request, workspace_id: UUID, permission: Permission) -> None:
    require_workspace_membership(request, workspace_id, permission)


@router.post("/documents", response_model=ResearchDocument, status_code=201)
def ingest_document(payload: DocumentIngestRequest, request: Request) -> ResearchDocument:
    _authorize(request, payload.workspace_id, Permission.RESEARCH_WRITE)
    try:
        return _engine(request).ingest_text(**payload.model_dump())
    except DocumentIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/documents", response_model=list[ResearchDocument])
def list_documents(request: Request, workspace_id: UUID) -> list[ResearchDocument]:
    _authorize(request, workspace_id, Permission.WORKSPACE_READ)
    return _engine(request).store.list_documents(workspace_id)


@router.get("/documents/{document_id}/provenance")
def document_provenance(document_id: UUID, request: Request, workspace_id: UUID) -> dict[str, Any]:
    _authorize(request, workspace_id, Permission.WORKSPACE_READ)
    try:
        document = _engine(request).store.get_document(document_id)
        if document.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="research document not found")
        return _engine(request).provenance(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="research document not found") from exc


@router.post("/search")
def search_research(payload: ResearchSearchRequest, request: Request) -> list[dict[str, Any]]:
    _authorize(request, payload.workspace_id, Permission.WORKSPACE_READ)
    hits = _engine(request).search(payload.query, limit=payload.limit, workspace_id=payload.workspace_id)
    return [
        {
            "chunk": hit.chunk.model_dump(mode="json"),
            "document": hit.document.model_dump(mode="json"),
            "source": hit.source.model_dump(mode="json"),
            "score": round(hit.score, 6),
        }
        for hit in hits
    ]


@router.post("/synthesize", response_model=ResearchSynthesis)
def synthesize_research(payload: ResearchSearchRequest, request: Request) -> ResearchSynthesis:
    _authorize(request, payload.workspace_id, Permission.WORKSPACE_READ)
    return _engine(request).synthesize(payload.query, limit=payload.limit, workspace_id=payload.workspace_id)
