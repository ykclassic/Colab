# ruff: noqa: I001,E701,E702
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from colab.api import app
from colab.research_intelligence import DeterministicEmbeddingProvider, DocumentIngestionError, ResearchIntelligence


def test_ingestion_chunks_embeds_and_preserves_provenance() -> None:
    engine = ResearchIntelligence(chunk_size=300, chunk_overlap=50); workspace_id = uuid4(); document = engine.ingest_text(title="Research memo", text=("Evidence about portfolio construction and risk controls. " * 40), uri="https://example.test/memo", publisher="Example Research", workspace_id=workspace_id); provenance = engine.provenance(document.document_id); chunks = provenance["chunks"]
    assert provenance["source"]["uri"] == "https://example.test/memo"; assert len(chunks) > 1; assert all(len(chunk["embedding"]) == DeterministicEmbeddingProvider.dimensions for chunk in chunks); assert all(chunk["document_id"] == str(document.document_id) for chunk in chunks)


def test_vector_search_is_ranked_and_synthesis_cites_exact_chunks() -> None:
    engine = ResearchIntelligence(); engine.ingest_text(title="Risk controls", text="Independent risk controls validate exposure, margin, spread and daily loss before approval.", uri="https://example.test/risk"); engine.ingest_text(title="Unrelated memo", text="The office cafeteria serves coffee and sandwiches.", uri="https://example.test/office"); hits = engine.search("risk exposure margin", limit=5); synthesis = engine.synthesize("risk exposure margin", limit=5)
    assert hits; assert hits[0].document.title == "Risk controls"; assert synthesis.citations; assert synthesis.citations[0].uri == "https://example.test/risk"; assert synthesis.citations[0].chunk_id == hits[0].chunk.chunk_id; assert synthesis.citations[0].citation_id in synthesis.answer


def test_empty_document_is_rejected() -> None:
    engine = ResearchIntelligence()
    try: engine.ingest_text(title="Empty", text="  ", uri="https://example.test/empty")
    except DocumentIngestionError as exc: assert "must not be empty" in str(exc)
    else: raise AssertionError("empty document should be rejected")


def test_research_api_is_registered_and_operational() -> None:
    client = TestClient(app); workspace_id = str(uuid4()); payload = {"workspace_id": workspace_id, "title": "API source", "text": "Vector search should retrieve this evidence about factor models.", "uri": "https://example.test/factors"}; response = client.post("/api/research/documents", json=payload); assert response.status_code == 201; document = response.json(); search = client.post("/api/research/search", json={"workspace_id": workspace_id, "query": "factor models", "limit": 5}); assert search.status_code == 200; assert search.json()[0]["document"]["document_id"] == document["document_id"]; synthesis = client.post("/api/research/synthesize", json={"workspace_id": workspace_id, "query": "factor models", "limit": 5}); assert synthesis.status_code == 200; assert synthesis.json()["citations"]
