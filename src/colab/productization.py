"""Phase 3 productization primitives: workspaces, artifacts, tools, and knowledge."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, List, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceStatus(str):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAILED = "failed"
    ARCHIVED = "archived"


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    product_goal: str = Field(min_length=1, max_length=10000)
    status: str = WorkspaceStatus.QUEUED
    priority: int = Field(default=100, ge=0, le=1000)
    strategies: list[StrategySpec] = Field(default_factory=list)
    created_by: UUID | None = None
    version: int = Field(default=1, ge=1)
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    kind: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    producer: str = Field(min_length=1, max_length=100)
    content: dict[str, Any]
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=200000)
    source: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=1000)
    allowed: bool = True
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ArtifactStore(Protocol):
    def put(self, artifact: ArtifactRecord) -> ArtifactRecord: ...
    def list(self, workspace_id: UUID) -> list[ArtifactRecord]: ...


@dataclass
class InMemoryArtifactStore:
    records: dict[UUID, list[ArtifactRecord]] = field(default_factory=dict)

    def put(self, artifact: ArtifactRecord) -> ArtifactRecord:
        versions = self.records.setdefault(artifact.workspace_id, [])
        if any(item.content_hash == artifact.content_hash and item.kind == artifact.kind for item in versions):
            return next(item for item in versions if item.content_hash == artifact.content_hash and item.kind == artifact.kind)
        same_kind = [item for item in versions if item.kind == artifact.kind]
        if same_kind:
            artifact.version = max(item.version for item in same_kind) + 1
        versions.append(artifact)
        return artifact

    def list(self, workspace_id: UUID) -> list[ArtifactRecord]:
        return list(self.records.get(workspace_id, []))


class KnowledgeBase:
    def __init__(self) -> None:
        self._documents: dict[UUID, KnowledgeDocument] = {}

    def upsert(self, document: KnowledgeDocument) -> KnowledgeDocument:
        previous = self._documents.get(document.document_id)
        if previous is not None:
            document.version = previous.version + 1
        self._documents[document.document_id] = document
        return document

    def search(self, query: str, limit: int = 10) -> list[KnowledgeDocument]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        terms = {term.lower() for term in query.split() if term.strip()}
        scored: list[tuple[int, KnowledgeDocument]] = []
        for document in self._documents.values():
            haystack = f"{document.title} {document.text} {' '.join(document.tags)}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].created_at, str(item[1].document_id)))
        return [document for _, document in scored[:limit]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise KeyError(f"tool {name!r} is not registered") from exc
        if not tool.allowed:
            raise PermissionError(f"tool {name!r} is disabled by policy")
        return tool

    def list(self) -> list[ToolDefinition]:
        return sorted(self._tools.values(), key=lambda tool: tool.name)


class WorkspaceManager:
    def __init__(self, max_concurrent: int = 2) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self.max_concurrent = max_concurrent
        self._workspaces: dict[UUID, Workspace] = {}
        self._idempotency: dict[str, UUID] = {}

    def submit(self, workspace: Workspace, idempotency_key: str | None = None) -> Workspace:
        if idempotency_key:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                return self.get(existing_id)
            self._idempotency[idempotency_key] = workspace.workspace_id
        self._workspaces[workspace.workspace_id] = workspace
        self._schedule()
        return workspace

    def get(self, workspace_id: UUID) -> Workspace:
        try:
            return self._workspaces[workspace_id]
        except KeyError as exc:
            raise KeyError(str(workspace_id)) from exc

    def list(self, include_archived: bool = False) -> List[Workspace]:
        items = self._workspaces.values() if include_archived else (item for item in self._workspaces.values() if item.status != WorkspaceStatus.ARCHIVED)
        return sorted(items, key=lambda item: (-item.priority, item.created_at))

    def update(self, workspace_id: UUID, expected_version: int, *, name: str, product_goal: str, priority: int, strategies: list[StrategySpec]) -> Workspace:
        workspace = self.get(workspace_id)
        self._check_version(workspace, expected_version)
        if workspace.status == WorkspaceStatus.ARCHIVED:
            raise ValueError("archived workspace cannot be edited")
        workspace.name, workspace.product_goal, workspace.priority, workspace.strategies = name, product_goal, priority, strategies
        workspace.version += 1
        workspace.updated_at = datetime.now(UTC)
        self._schedule()
        return workspace

    def archive(self, workspace_id: UUID, expected_version: int) -> Workspace:
        workspace = self.get(workspace_id)
        self._check_version(workspace, expected_version)
        if workspace.status == WorkspaceStatus.ARCHIVED:
            return workspace
        workspace.status = WorkspaceStatus.ARCHIVED
        workspace.archived_at = datetime.now(UTC)
        workspace.version += 1
        workspace.updated_at = datetime.now(UTC)
        return workspace

    def restore(self, workspace_id: UUID, expected_version: int) -> Workspace:
        workspace = self.get(workspace_id)
        self._check_version(workspace, expected_version)
        if workspace.status != WorkspaceStatus.ARCHIVED:
            return workspace
        workspace.status = WorkspaceStatus.QUEUED
        workspace.archived_at = None
        workspace.version += 1
        workspace.updated_at = datetime.now(UTC)
        self._schedule()
        return workspace

    def delete(self, workspace_id: UUID, expected_version: int) -> None:
        workspace = self.get(workspace_id)
        self._check_version(workspace, expected_version)
        if workspace.status != WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace must be archived before permanent deletion")
        del self._workspaces[workspace_id]
        for key, value in list(self._idempotency.items()):
            if value == workspace_id:
                del self._idempotency[key]

    @staticmethod
    def _check_version(workspace: Workspace, expected_version: int) -> None:
        if expected_version != workspace.version:
            raise RuntimeError(f"workspace version conflict: expected {expected_version}, current {workspace.version}")

    def _schedule(self) -> None:
        running = sorted((item for item in self._workspaces.values() if item.status == WorkspaceStatus.RUNNING), key=lambda item: (item.priority, item.created_at))
        queued = [item for item in self.list() if item.status == WorkspaceStatus.QUEUED]
        slots = max(0, self.max_concurrent - len(running))
        if running and queued:
            highest_queued = queued[0]
            lower_running = [item for item in running if item.priority < highest_queued.priority]
            for workspace in lower_running[: min(len(queued), len(lower_running))]:
                workspace.status = WorkspaceStatus.QUEUED
                workspace.updated_at = datetime.now(UTC)
            running = [item for item in running if item.status == WorkspaceStatus.RUNNING]
            slots = max(0, self.max_concurrent - len(running))
        for workspace in [item for item in self.list() if item.status == WorkspaceStatus.QUEUED][:slots]:
            workspace.status = WorkspaceStatus.RUNNING
            workspace.updated_at = datetime.now(UTC)


def build_artifact(workspace_id: UUID, kind: str, producer: str, content: dict[str, Any]) -> ArtifactRecord:
    canonical = repr(sorted(content.items())).encode("utf-8")
    return ArtifactRecord(workspace_id=workspace_id, kind=kind, producer=producer, content=content, content_hash=sha256(canonical).hexdigest())
