from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from colab.api import PlatformServices, create_app
from colab.platform_persistence import PlatformRepository, connection_factory_from_dsn
from colab.productization import (
    ArtifactRecord,
    KnowledgeBase,
    KnowledgeDocument,
    StrategySpec,
    ToolDefinition,
    Workspace,
    WorkspaceManager,
    WorkspaceStatus,
    build_artifact,
)


class FakeCursor:
    def __init__(self, *, one=None, many=None) -> None:
        self.one = one
        self.many = many or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, query, params=None) -> None:
        return None

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class FakeConnection:
    def __init__(self, *, one=None, many=None) -> None:
        self.cursor_instance = FakeCursor(one=one, many=many)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def transaction(self):
        return self

    def cursor(self, row_factory=None):
        return self.cursor_instance


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


def test_workspace_manager_rejects_invalid_limit() -> None:
    try:
        WorkspaceManager(max_concurrent=0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive concurrency must fail")


def test_knowledge_search_is_ranked_and_validated() -> None:
    kb = KnowledgeBase()
    document = KnowledgeDocument(title="Momentum", text="momentum factor research", source="a", tags=["factor"])
    kb.upsert(document)
    kb.upsert(document)
    kb.upsert(KnowledgeDocument(title="Risk", text="drawdown controls", source="b", tags=["risk"]))
    assert document.version == 2
    assert kb.search("momentum")[0].title == "Momentum"
    try:
        kb.search(" ")
    except ValueError:
        pass
    else:
        raise AssertionError("blank query must fail")
    for limit in (0, 101):
        try:
            kb.search("momentum", limit=limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid search limit must fail")


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


def test_platform_repository_persists_and_lists_metadata() -> None:
    workspace = Workspace(name="durable", product_goal="persist", priority=7)
    artifact = build_artifact(workspace.workspace_id, "report", "qa", {"ok": True})
    document = KnowledgeDocument(title="Research", text="alpha", source="test", tags=["alpha"])
    tool = ToolDefinition(name="market_data", description="read market data", input_schema={"symbol": "str"})

    rows = {
        "workspace": workspace.model_dump(mode="json"),
        "artifact": artifact.model_dump(mode="json"),
    }

    repository = PlatformRepository(lambda: FakeConnection())
    assert repository.create_workspace(workspace) == workspace
    listed_workspace = PlatformRepository(lambda: FakeConnection(many=[rows["workspace"]])).list_workspaces()[0]
    assert listed_workspace.workspace_id == workspace.workspace_id

    artifact_repo = PlatformRepository(lambda: FakeConnection(one={"version": 0}))
    stored = artifact_repo.put_artifact(artifact)
    assert stored.version == 1
    listed_artifact = PlatformRepository(lambda: FakeConnection(many=[rows["artifact"]])).list_artifacts(workspace.workspace_id)[0]
    assert listed_artifact.artifact_id == artifact.artifact_id

    knowledge_repo = PlatformRepository(lambda: FakeConnection(one={"version": 2}))
    assert knowledge_repo.upsert_knowledge(document).version == 2
    assert repository.register_tool(tool) == tool


def test_platform_repository_rejects_empty_dsn_and_connects_lazily() -> None:
    try:
        connection_factory_from_dsn(" ")
    except ValueError:
        pass
    else:
        raise AssertionError("blank DSN must fail")

    factory = connection_factory_from_dsn("postgresql://example")
    with patch("psycopg.connect") as connect:
        sentinel = object()
        connect.return_value = sentinel
        assert factory() is sentinel
        connect.assert_called_once_with("postgresql://example", row_factory=__import__("psycopg.rows", fromlist=["dict_row"]).dict_row)


def test_platform_repository_raises_on_missing_return_rows() -> None:
    workspace_id = uuid4()
    artifact = ArtifactRecord(
        workspace_id=workspace_id,
        kind="report",
        producer="qa",
        content={"x": 1},
        content_hash="0" * 64,
    )
    repository = PlatformRepository(lambda: FakeConnection(one=None))
    try:
        repository.put_artifact(artifact)
    except RuntimeError as exc:
        assert "artifact version" in str(exc)
    else:
        raise AssertionError("missing artifact version row must fail")

    document = KnowledgeDocument(title="x", text="y", source="z")
    try:
        repository.upsert_knowledge(document)
    except RuntimeError as exc:
        assert "knowledge upsert" in str(exc)
    else:
        raise AssertionError("missing knowledge version row must fail")
