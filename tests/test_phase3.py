from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from colab.api import PlatformServices, create_app
from colab.productization import (
    KnowledgeBase,
    KnowledgeDocument,
    StrategySpec,
    Workspace,
    WorkspaceManager,
    WorkspaceStatus,
    build_artifact,
)


def test_artifact_store_versions_and_deduplicates() -> None:
    services = PlatformServices()
    workspace = services.workspaces.submit(Workspace(name="alpha", product_goal="research"))
    first = services.artifacts.put(build_artifact(workspace.workspace_id, "report", "researcher", {"x": 1}))
    duplicate = services.artifacts.put(build_artifact(workspace.workspace_id, "report", "researcher", {"x": 1}))
    second = services.artifacts.put(build_artifact(workspace.workspace_id, "report", "researcher", {"x": 2}))
    assert first.version == 1
    assert duplicate.artifact_id == first.artifact_id
    assert second.version == 2
    assert len(services.artifacts.list(workspace.workspace_id)) == 2


def test_workspace_manager_respects_concurrency_and_priority() -> None:
    manager = WorkspaceManager(max_concurrent=1)
    low = Workspace(name="low", product_goal="x", priority=1)
    high = Workspace(name="high", product_goal="y", priority=10)
    manager.submit(low)
    manager.submit(high)
    assert manager.get(high.workspace_id).status == WorkspaceStatus.RUNNING
    assert manager.get(low.workspace_id).status == WorkspaceStatus.QUEUED


def test_knowledge_search_is_ranked_and_validated() -> None:
    kb = KnowledgeBase()
    kb.upsert(KnowledgeDocument(title="Momentum", text="momentum factor research", source="a", tags=["factor"]))
    kb.upsert(KnowledgeDocument(title="Risk", text="drawdown controls", source="b", tags=["risk"]))
    assert kb.search("momentum")[0].title == "Momentum"
    try:
        kb.search(" ")
    except ValueError:
        pass
    else:
        raise AssertionError("blank query must fail")


def test_api_exposes_product_workspace_and_artifact_flow() -> None:
    client = TestClient(create_app(PlatformServices(max_concurrent=2)))
    health = client.get("/health")
    assert health.status_code == 200
    created = client.post("/api/workspaces", json={"name": "demo", "product_goal": "build a signal"})
    assert created.status_code == 201
    workspace = created.json()
    artifact = client.post(
        f"/api/workspaces/{workspace['workspace_id']}/artifacts",
        json={"kind": "research", "producer": "quant_researcher", "content": {"factor": "momentum"}},
    )
    assert artifact.status_code == 201
    assert artifact.json()["version"] == 1
    assert client.get("/api/workspaces/not-a-uuid").status_code == 422
    assert client.get(f"/api/workspaces/{workspace['workspace_id']}/artifacts").json()[0]["kind"] == "research"
    assert client.get("/").status_code == 200


def test_api_knowledge_and_safe_tool_registry() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/knowledge",
        json={"title": "Walk forward", "text": "out of sample validation", "source": "internal", "tags": ["validation"]},
    )
    assert response.status_code == 201
    results = client.get("/api/knowledge/search?q=validation").json()
    assert results[0]["title"] == "Walk forward"
    tools = client.get("/api/tools").json()
    names = {tool["name"] for tool in tools}
    assert "backtest" in names
    assert "artifact_store" in names


def test_strategy_spec_is_supported_in_workspace() -> None:
    strategy = StrategySpec(name="trend", description="trend following", parameters={"lookback": 20})
    workspace = Workspace(name="multi", product_goal="compare strategies", strategies=[strategy])
    assert workspace.strategies[0].parameters["lookback"] == 20
    assert workspace.workspace_id != uuid4()
