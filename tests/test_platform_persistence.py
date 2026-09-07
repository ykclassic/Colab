from __future__ import annotations

from uuid import uuid4

import pytest

from colab.platform_persistence import connection_factory_from_dsn
from colab.productization import ArtifactRecord, KnowledgeDocument, ToolDefinition, Workspace


def test_connection_factory_rejects_blank_dsn() -> None:
    with pytest.raises(ValueError):
        connection_factory_from_dsn(" ")


def test_platform_models_have_persistence_shapes() -> None:
    workspace = Workspace(name="w", product_goal="g")
    artifact = ArtifactRecord(
        workspace_id=workspace.workspace_id,
        kind="report",
        producer="ceo",
        content={},
        content_hash="0" * 64,
    )
    knowledge = KnowledgeDocument(title="t", text="text", source="internal")
    tool = ToolDefinition(name="safe_tool", description="safe")
    assert isinstance(workspace.workspace_id, type(uuid4()))
    assert artifact.content_hash == "0" * 64
    assert knowledge.version == 1
    assert tool.allowed is True
