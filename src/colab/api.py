"""HTTP interface for Phase 3 productization capabilities."""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .productization import (
    ArtifactRecord,
    InMemoryArtifactStore,
    KnowledgeBase,
    KnowledgeDocument,
    StrategySpec,
    ToolDefinition,
    ToolRegistry,
    Workspace,
    WorkspaceManager,
    build_artifact,
)


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    product_goal: str = Field(min_length=1, max_length=10000)
    priority: int = Field(default=100, ge=0, le=1000)
    strategies: list[StrategySpec] = Field(default_factory=list)


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=100)
    producer: str = Field(min_length=1, max_length=100)
    content: dict[str, Any]


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=200000)
    source: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list)


class PlatformServices:
    def __init__(self, max_concurrent: int = 2) -> None:
        self.workspaces = WorkspaceManager(max_concurrent=max_concurrent)
        self.artifacts = InMemoryArtifactStore()
        self.knowledge = KnowledgeBase()
        self.tools = ToolRegistry()
        self._register_safe_defaults()

    def _register_safe_defaults(self) -> None:
        defaults = (
            ToolDefinition(
                name="market_data",
                description="Provider-neutral market-data lookup; execution is not permitted.",
            ),
            ToolDefinition(
                name="research_search",
                description="Search approved research and knowledge sources.",
            ),
            ToolDefinition(
                name="quant_sandbox",
                description="Run trusted quantitative analysis inside the configured sandbox.",
            ),
            ToolDefinition(
                name="backtest",
                description="Run deterministic backtests and validation workloads.",
            ),
            ToolDefinition(
                name="artifact_store",
                description="Read and write versioned workflow artifacts.",
            ),
        )
        for tool in defaults:
            self.tools.register(tool)


def create_app(services: PlatformServices | None = None) -> FastAPI:
    services = services or PlatformServices(
        max_concurrent=int(os.getenv("COLAB_MAX_CONCURRENT_WORKSPACES", "2"))
    )
    app = FastAPI(title="Colab Agent Platform", version="0.3.0")
    app.state.services = services

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "colab-agent-platform"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _DASHBOARD_HTML

    @app.post("/api/workspaces", response_model=Workspace, status_code=201)
    def create_workspace(payload: WorkspaceCreate) -> Workspace:
        return services.workspaces.submit(Workspace(**payload.model_dump()))

    @app.get("/api/workspaces", response_model=list[Workspace])
    def list_workspaces() -> list[Workspace]:
        return services.workspaces.list()

    @app.get("/api/workspaces/{workspace_id}", response_model=Workspace)
    def get_workspace(workspace_id: UUID) -> Workspace:
        try:
            return services.workspaces.get(workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workspace not found") from exc

    @app.post("/api/workspaces/{workspace_id}/artifacts", response_model=ArtifactRecord, status_code=201)
    def create_artifact(workspace_id: UUID, payload: ArtifactCreate) -> ArtifactRecord:
        try:
            services.workspaces.get(workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workspace not found") from exc
        artifact = build_artifact(workspace_id, payload.kind, payload.producer, payload.content)
        return services.artifacts.put(artifact)

    @app.get("/api/workspaces/{workspace_id}/artifacts", response_model=list[ArtifactRecord])
    def list_artifacts(workspace_id: UUID) -> list[ArtifactRecord]:
        try:
            services.workspaces.get(workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workspace not found") from exc
        return services.artifacts.list(workspace_id)

    @app.post("/api/knowledge", response_model=KnowledgeDocument, status_code=201)
    def add_knowledge(payload: KnowledgeCreate) -> KnowledgeDocument:
        return services.knowledge.upsert(KnowledgeDocument(**payload.model_dump()))

    @app.get("/api/knowledge/search", response_model=list[KnowledgeDocument])
    def search_knowledge(
        q: str = Query(min_length=1), limit: int = Query(default=10, ge=1, le=100)
    ) -> list[KnowledgeDocument]:
        return services.knowledge.search(q, limit)

    @app.get("/api/tools", response_model=list[ToolDefinition])
    def list_tools() -> list[ToolDefinition]:
        return services.tools.list()

    return app


app = create_app()

_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Colab Agent Platform</title><style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px;background:#f7f7f8;color:#171717}
.card{background:white;border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0;box-shadow:0 2px 8px #0000000d}
input,textarea,button{font:inherit;padding:10px;border:1px solid #bbb;border-radius:8px;margin:5px 0;width:100%;box-sizing:border-box}
button{cursor:pointer;width:auto}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#eee}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head><body>
<h1>Colab Agent Platform</h1><p>Phase 3 product workspace, artifact, knowledge, and tool-control dashboard.</p>
<div class="grid"><section class="card"><h2>New workspace</h2><input id="name" placeholder="Workspace name"><textarea id="goal" placeholder="Product goal"></textarea>
<button onclick="createWorkspace()">Create workspace</button><p id="workspaceResult"></p></section>
<section class="card"><h2>Workspaces</h2><div id="workspaces">Loading…</div></section></div>
<section class="card"><h2>Approved tools</h2><div id="tools">Loading…</div></section>
<script>
async function load(){const [w,t]=await Promise.all([fetch('/api/workspaces').then(r=>r.json()),fetch('/api/tools').then(r=>r.json())]);
document.getElementById('workspaces').innerHTML=w.length?w.map(x=>`<p><strong>${x.name}</strong> <span class="pill">${x.status}</span><br>${x.product_goal}</p>`).join(''):'No workspaces yet.';
document.getElementById('tools').innerHTML=t.map(x=>`<p><strong>${x.name}</strong> — ${x.description}</p>`).join('');}
async function createWorkspace(){const body={name:document.getElementById('name').value,product_goal:document.getElementById('goal').value};const r=await fetch('/api/workspaces',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});document.getElementById('workspaceResult').textContent=r.ok?'Workspace created.':'Creation failed.';load();}
load();
</script></body></html>"""
