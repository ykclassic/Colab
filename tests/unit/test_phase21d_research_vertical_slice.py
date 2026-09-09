from __future__ import annotations

from uuid import uuid4

from colab.research_intelligence import DeterministicEmbeddingProvider
from colab.research_platform import TextExtractionPipeline
from colab.research_vertical_slice import InMemoryResearchRunStore, ResearchVerticalSlice


def _pipeline() -> ResearchVerticalSlice:
    return ResearchVerticalSlice(
        embedding_provider=DeterministicEmbeddingProvider(),
        extractor=TextExtractionPipeline(),
        store=InMemoryResearchRunStore(),
        chunk_size=300,
        chunk_overlap=50,
    )


def test_complete_research_vertical_slice_is_evidence_backed() -> None:
    workspace = uuid4()
    content = (
        b"Inflation fell from 6.2 percent to 5.1 percent after the policy rate increased. "
        b"The research dataset attributes the change to tighter monetary conditions."
    )
    run = _pipeline().run(
        workspace_id=workspace,
        dataset_name="macro",
        source_uri="https://example.test/macro.txt",
        title="Macro research",
        content=content,
        media_type="text/plain",
        filename="macro.txt",
        query="inflation policy rate monetary conditions",
    )
    assert run.extraction_hash
    assert run.normalized_hash
    assert run.chunks
    assert run.candidates
    assert run.ranked
    assert run.citations
    assert all(item.valid for item in run.validations)
    assert run.report.workspace_id == workspace
    assert len(run.report.reproducibility_hash) == 64
    assert len(run.reproducibility_hash) == 64
    for citation in run.citations:
        assert citation["quote"] in next(x.text for x in run.ranked if str(x.chunk_id) == citation["chunk_id"])


def test_vertical_slice_is_reproducible_for_identical_inputs() -> None:
    workspace = uuid4()
    kwargs = dict(
        workspace_id=workspace,
        dataset_name="rates",
        source_uri="https://example.test/rates.txt",
        title="Rates",
        content=b"Central bank policy tightened as inflation declined.",
        media_type="text/plain",
        filename="rates.txt",
        query="central bank inflation policy",
    )
    first = _pipeline().run(**kwargs)
    second = _pipeline().run(**kwargs)
    assert first.reproducibility_hash == second.reproducibility_hash
    assert first.report.reproducibility_hash == second.report.reproducibility_hash
    assert first.normalized_hash == second.normalized_hash


def test_workspace_isolation_and_persistent_shape() -> None:
    store = InMemoryResearchRunStore()
    pipeline = ResearchVerticalSlice(
        embedding_provider=DeterministicEmbeddingProvider(),
        store=store,
        chunk_size=300,
        chunk_overlap=50,
    )
    first_workspace = uuid4()
    second_workspace = uuid4()
    pipeline.run(
        workspace_id=first_workspace, dataset_name="one", source_uri="https://example.test/one",
        title="One", content=b"alpha evidence", media_type="text/plain", query="alpha evidence",
    )
    pipeline.run(
        workspace_id=second_workspace, dataset_name="two", source_uri="https://example.test/two",
        title="Two", content=b"beta evidence", media_type="text/plain", query="beta evidence",
    )
    assert len(store.list(first_workspace)) == 1
    assert len(store.list(second_workspace)) == 1
    assert store.list(first_workspace)[0].workspace_id != store.list(second_workspace)[0].workspace_id


def test_fabricated_citation_cannot_become_a_report() -> None:
    pipeline = _pipeline()
    run = pipeline.run(
        workspace_id=uuid4(), dataset_name="source", source_uri="https://example.test/source",
        title="Source", content=b"real evidence", media_type="text/plain", query="real evidence",
    )
    assert all(item.valid for item in run.validations)
    assert run.report.citations
