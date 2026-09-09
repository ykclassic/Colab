from uuid import uuid4

from fastapi.testclient import TestClient

from colab.api import PlatformServices, create_app


def test_knowledge_api_requires_workspace_and_filters_results() -> None:
    client = TestClient(create_app(PlatformServices()))
    workspace_a = str(uuid4())
    workspace_b = str(uuid4())

    created = client.post("/api/knowledge", json={"workspace_id": workspace_a, "title": "A", "text": "tenant alpha evidence", "source": "a"})
    assert created.status_code == 201
    assert created.json()["workspace_id"] == workspace_a

    assert client.get("/api/knowledge/search", params={"q": "tenant", "workspace_id": workspace_a}).json()[0]["workspace_id"] == workspace_a
    assert client.get("/api/knowledge/search", params={"q": "tenant", "workspace_id": workspace_b}).json() == []
    assert client.post("/api/knowledge", json={"title": "missing scope", "text": "x", "source": "x"}).status_code == 422


def test_knowledge_cannot_move_document_between_workspaces() -> None:
    client = TestClient(create_app(PlatformServices()))
    workspace_a = str(uuid4())
    workspace_b = str(uuid4())
    created = client.post("/api/knowledge", json={"workspace_id": workspace_a, "title": "A", "text": "evidence", "source": "a"})
    document_id = created.json()["document_id"]
    moved = client.post("/api/knowledge", json={"workspace_id": workspace_b, "document_id": document_id, "title": "A", "text": "evidence", "source": "a"})
    assert moved.status_code == 422


def test_research_api_requires_workspace_and_isolates_search_and_provenance() -> None:
    client = TestClient(create_app(PlatformServices()))
    workspace_a = str(uuid4())
    workspace_b = str(uuid4())
    created = client.post("/api/research/documents", json={"workspace_id": workspace_a, "title": "A", "text": "alpha tenant research evidence", "uri": "https://example.com/a"})
    assert created.status_code == 201
    document_id = created.json()["document_id"]

    a_hits = client.post("/api/research/search", json={"workspace_id": workspace_a, "query": "alpha"})
    assert a_hits.status_code == 200
    assert a_hits.json()[0]["document"]["workspace_id"] == workspace_a

    b_hits = client.post("/api/research/search", json={"workspace_id": workspace_b, "query": "alpha"})
    assert b_hits.status_code == 200
    assert b_hits.json() == []

    assert client.get(f"/api/research/documents/{document_id}/provenance", params={"workspace_id": workspace_b}).status_code == 404
    assert client.get(f"/api/research/documents/{document_id}/provenance", params={"workspace_id": workspace_a}).status_code == 200
    assert client.get("/api/research/documents").status_code == 422
