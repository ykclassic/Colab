from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest

from colab.research_intelligence import DeterministicEmbeddingProvider
from colab.research_platform import (
    DatasetRecord,
    InMemoryDatasetRegistry,
    OpenAIEmbeddingProvider,
    ResearchPlatformError,
    RetrievalCandidate,
    TextExtractionPipeline,
    build_report,
    citation_id_for,
    reciprocal_rank_fusion,
    rerank,
    validate_citations,
)


def test_dataset_registry_is_workspace_scoped() -> None:
    registry = InMemoryDatasetRegistry()
    workspace = uuid4()
    item = DatasetRecord(
        workspace_id=workspace,
        name="macro",
        source_uri="https://example.test/macro",
        content_hash=sha256(b"data").hexdigest(),
        schema_hash=sha256(b"{}").hexdigest(),
    )
    registry.register(item)
    assert registry.list(workspace) == [item]
    assert registry.list(uuid4()) == []


def test_extraction_normalizes_html_and_json() -> None:
    extractor = TextExtractionPipeline()
    html, version = extractor.extract(b"<script>bad()</script><h1>Research</h1>", "text/html")
    assert html == "Research"
    assert version == "utf8-text-v1"
    json_text, _ = extractor.extract(b'{"b":2,"a":1}', "application/json")
    assert '"a": 1' in json_text
    assert '"b": 2' in json_text


def test_extraction_rejects_invalid_input() -> None:
    with pytest.raises(ResearchPlatformError):
        TextExtractionPipeline().extract(b"", "text/plain")
    with pytest.raises(ResearchPlatformError):
        TextExtractionPipeline().extract(b"nope", "application/pdf")


def test_real_provider_requires_secret() -> None:
    with pytest.raises(ResearchPlatformError, match="OPENAI_API_KEY"):
        OpenAIEmbeddingProvider(api_key=None)


def test_embedding_contract_has_model_metadata() -> None:
    provider = DeterministicEmbeddingProvider()
    assert provider.model == "deterministic-hash-v1"
    assert len(provider.embed("research evidence")) == provider.dimensions


def test_reranking_and_rrf_are_deterministic() -> None:
    a = RetrievalCandidate(uuid4(), uuid4(), uuid4(), "alpha beta evidence", "A", "u:a", 0.9, 0.8)
    b = RetrievalCandidate(uuid4(), uuid4(), uuid4(), "alpha", "B", "u:b", 0.7, 0.9)
    fused = reciprocal_rank_fusion([a, b], [b, a])
    assert {x.chunk_id for x in fused} == {a.chunk_id, b.chunk_id}
    ranked = rerank("alpha beta", fused, 1)
    assert len(ranked) == 1


def test_citation_validation_rejects_missing_or_fabricated_quote() -> None:
    valid = {"CIT-1": "The market grew by 10 percent."}
    assert validate_citations([{"citation_id": "CIT-1", "quote": "grew by 10 percent"}], valid)[0].valid
    assert not validate_citations([{"citation_id": "CIT-2", "quote": "invented"}], valid)[0].valid
    assert not validate_citations([{"citation_id": "CIT-1", "quote": "invented"}], valid)[0].valid


def test_report_manifest_is_reproducible_and_citations_are_checked() -> None:
    workspace = uuid4()
    source = uuid4()
    chunk = uuid4()
    cid = citation_id_for(source, chunk)
    citations = [{"citation_id": cid, "chunk_id": str(chunk), "quote": "evidence", "title": "Source", "uri": "https://example.test/source"}]
    report1 = build_report(workspace_id=workspace, query="q", answer="evidence", citations=citations,
                           evidence={cid: "more evidence"}, dataset_ids=[uuid4()], retrieval_config={"k": 10},
                           provider={"name": "test", "model": "v1", "dimensions": 3})
    report2 = build_report(workspace_id=workspace, query="q", answer="evidence", citations=citations,
                           evidence={cid: "more evidence"}, dataset_ids=report1.dataset_ids, retrieval_config={"k": 10},
                           provider={"name": "test", "model": "v1", "dimensions": 3})
    assert report1.reproducibility_hash == report2.reproducibility_hash

    with pytest.raises(ResearchPlatformError, match="citation validation"):
        build_report(workspace_id=workspace, query="q", answer="evidence", citations=citations,
                     evidence={cid: "different source"}, dataset_ids=[], retrieval_config={}, provider={})
