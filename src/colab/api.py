"""HTTP interface for Phase 3 productization and Phase 4 operations."""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .background_jobs_api import register_background_job_routes
from .collaboration_api import register_collaboration_routes
from .operations import (
    EventLevel,
    ExecutionCoordinator,
    ExecutionJob,
    MetricsSnapshot,
    ObservabilityRecorder,
    OperationalEvent,
)
from .production_persistence import PostgresPlatformStore
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
from .quant_api import register_quant_routes
from .release_governance_api import register_release_governance_routes
from .research_api import router as research_router
from .research_intelligence import ResearchIntelligence
from .research_platform_api import router as research_platform_router, ResearchPlatformServices
from .security import Permission, require_workspace_membership
from .service_adapters import (
    PostgresArtifactStore,
    PostgresExecutionCoordinator,
    PostgresKnowledgeBase,
    PostgresObservabilityRecorder,
    PostgresToolRegistry,
    PostgresWorkspaceManager,
    production_connection_factory_from_dsn,
)
from .service_contracts import (
    ArtifactService,
    ExecutionService,
    KnowledgeService,
    ObservabilityService,
    ToolService,
    WorkspaceService,
)
from .workspace_api import register_workspace_routes

_KNOWLEDGE_QUERY = Query(min_length=1)
_KNOWLEDGE_WORKSPACE = Query(...)
_KNOWLEDGE_LIMIT = Query(default=10, ge=1, le=100)

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
    workspace_id: UUID
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=200000)
    source: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list)

class ExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: UUID
    workspace_id: UUID
    stage: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=255)
    max_attempts: int = Field(default=3, ge=1, le=20)

class ExecutionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=255)

class ExecutionFailure(ExecutionAction):
    error: str = Field(min_length=1, max_length=5000)

class PlatformServices:
    """Compose local deterministic services or durable PostgreSQL services."""
    def __init__(self, max_concurrent: int = 2, database_dsn: str | None = None) -> None:
        dsn = database_dsn or os.getenv("COLAB_DATABASE_DSN")
        production = os.getenv("COLAB_ENV", "development").lower() == "production"
        if production and not dsn:
            raise RuntimeError("COLAB_DATABASE_DSN is required when COLAB_ENV=production")
        self.database: PostgresPlatformStore | None = None
        self.workspaces: WorkspaceService
        self.artifacts: ArtifactService
        self.knowledge: KnowledgeService
        self.tools: ToolService
        self.execution: ExecutionService
        self.observability: ObservabilityService
        lease_seconds = int(os.getenv("COLAB_EXECUTION_LEASE_SECONDS", "300"))
        if dsn:
            store = PostgresPlatformStore(production_connection_factory_from_dsn(dsn), max_concurrent)
            self.database = store
            self.workspaces = PostgresWorkspaceManager(store)
            self.artifacts = PostgresArtifactStore(store)
            self.knowledge = PostgresKnowledgeBase(store)
            self.tools = PostgresToolRegistry(store)
            self.execution = PostgresExecutionCoordinator(store, lease_seconds)
            self.observability = PostgresObservabilityRecorder(store)
        else:
            self.workspaces = WorkspaceManager(max_concurrent=max_concurrent)
            self.artifacts = InMemoryArtifactStore()
            self.knowledge = KnowledgeBase()
            self.tools = ToolRegistry()
            self.execution = ExecutionCoordinator(lease_seconds=lease_seconds)
            self.observability = ObservabilityRecorder()
        self._register_safe_defaults()

    def _register_safe_defaults(self) -> None:
        defaults = (
            ToolDefinition(name="market_data", description="Provider-neutral market-data lookup; execution is not permitted."),
            ToolDefinition(name="research_search", description="Search approved research and knowledge sources."),
            ToolDefinition(name="quant_sandbox", description="Run trusted quantitative analysis inside the configured sandbox."),
            ToolDefinition(name="backtest", description="Run deterministic backtests and validation workloads."),
            ToolDefinition(name="artifact_store", description="Read and write versioned workflow artifacts."),
        )
        for tool in defaults:
            self.tools.register(tool)

def create_app(services: PlatformServices | None = None) -> FastAPI:
    services = services or PlatformServices(max_concurrent=int(os.getenv("COLAB_MAX_CONCURRENT_WORKSPACES", "2")))
    app = FastAPI(title="Colab Agent Platform", version="0.7.0")
    app.state.services = services
    app.state.research_intelligence = ResearchIntelligence()
    app.state.research_platform = ResearchPlatformServices(
        database_dsn=os.getenv("COLAB_DATABASE_DSN"),
        production=os.getenv("COLAB_ENV", "development").lower() == "production",
    )
    app.include_router(research_router)
    app.include_router(research_platform_router)
    register_collaboration_routes(app)
    register_quant_routes(app)
    register_release_governance_routes(app)
    register_background_job_routes(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "colab-agent-platform"}

    @app.get("/ready")
    def readiness() -> dict[str, str]:
        if services.database is None:
            return {"status": "ready", "database": "not_configured"}
        try:
            services.database.check_ready()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database is not ready") from exc
        return {"status": "ready", "database": "ok"}

    @app.get("/api/operations/metrics", response_model=MetricsSnapshot)
    def operations_metrics() -> MetricsSnapshot:
        return services.execution.snapshot()

    @app.get("/api/operations/events", response_model=list[OperationalEvent])
    def operations_events(workflow_id: UUID | None = None, workspace_id: UUID | None = None, job_id: UUID | None = None, limit: int = Query(default=100, ge=1, le=1000)) -> list[OperationalEvent]:
        if workspace_id is None:
            raise HTTPException(status_code=422, detail="workspace_id is required")
        return services.observability.query(workflow_id, workspace_id, job_id, limit)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _DASHBOARD_HTML

    @app.post("/api/workspaces", response_model=Workspace, status_code=201)
    def create_workspace(payload: WorkspaceCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> Workspace:
        return services.workspaces.submit(Workspace(**payload.model_dump()), idempotency_key)

    @app.get("/api/workspaces", response_model=list[Workspace])
    def list_workspaces(include_archived: bool = Query(default=False)) -> list[Workspace]:
        return services.workspaces.list(include_archived)

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
    def add_knowledge(payload: KnowledgeCreate, request: Request) -> KnowledgeDocument:
        require_workspace_membership(request, payload.workspace_id, Permission.RESEARCH_WRITE)
        try:
            return services.knowledge.upsert(KnowledgeDocument(**payload.model_dump()))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="knowledge document belongs to another workspace") from exc

    @app.get("/api/knowledge/search", response_model=list[KnowledgeDocument])
    def search_knowledge(request: Request, q: str = _KNOWLEDGE_QUERY, workspace_id: UUID = _KNOWLEDGE_WORKSPACE, limit: int = _KNOWLEDGE_LIMIT) -> list[KnowledgeDocument]:
        require_workspace_membership(request, workspace_id, Permission.WORKSPACE_READ)
        return services.knowledge.search(q, limit, workspace_id)

    @app.get("/api/tools", response_model=list[ToolDefinition])
    def list_tools() -> list[ToolDefinition]:
        return services.tools.list()

    @app.post("/api/executions", response_model=ExecutionJob, status_code=201)
    def enqueue_execution(payload: ExecutionCreate) -> ExecutionJob:
        job = services.execution.enqueue(**payload.model_dump())
        services.observability.record(OperationalEvent(workflow_id=job.workflow_id, workspace_id=job.workspace_id, job_id=job.job_id, event_type="execution_enqueued", actor="api", message="Execution job accepted by coordinator."))
        return job

    @app.post("/api/executions/claim", response_model=ExecutionJob)
    def claim_execution(payload: ExecutionAction) -> ExecutionJob:
        job = services.execution.claim(payload.worker_id)
        if job is None:
            raise HTTPException(status_code=409, detail="no execution job available")
        services.observability.record(OperationalEvent(workflow_id=job.workflow_id, workspace_id=job.workspace_id, job_id=job.job_id, event_type="execution_claimed", actor=payload.worker_id, message="Execution lease claimed."))
        return job

    @app.post("/api/executions/{job_id}/heartbeat", response_model=ExecutionJob)
    def heartbeat_execution(job_id: UUID, payload: ExecutionAction) -> ExecutionJob:
        try:
            return services.execution.heartbeat(job_id, payload.worker_id)
        except (KeyError, PermissionError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/executions/{job_id}/complete", response_model=ExecutionJob)
    def complete_execution(job_id: UUID, payload: ExecutionAction) -> ExecutionJob:
        try:
            job = services.execution.complete(job_id, payload.worker_id)
        except (KeyError, PermissionError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        services.observability.record(OperationalEvent(workflow_id=job.workflow_id, workspace_id=job.workspace_id, job_id=job.job_id, event_type="execution_succeeded", actor=payload.worker_id, message="Execution completed successfully."))
        return job

    @app.post("/api/executions/{job_id}/fail", response_model=ExecutionJob)
    def fail_execution(job_id: UUID, payload: ExecutionFailure) -> ExecutionJob:
        try:
            job = services.execution.fail(job_id, payload.worker_id, payload.error)
        except (KeyError, PermissionError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        services.observability.record(OperationalEvent(workflow_id=job.workflow_id, workspace_id=job.workspace_id, job_id=job.job_id, event_type=("execution_failed" if job.status == "failed" else "execution_retry_scheduled"), level=EventLevel.ERROR if job.status == "failed" else EventLevel.WARNING, actor=payload.worker_id, message=job.error or "Execution failed."))
        return job

    @app.post("/api/executions/{job_id}/cancel", response_model=ExecutionJob)
    def cancel_execution(job_id: UUID) -> ExecutionJob:
        try:
            return services.execution.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="execution job not found") from exc

    return app

app = create_app()
register_workspace_routes(app)

_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Colab Agent Platform</title><style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px;background:#f7f7f8;color:#171717}
.card{background:white;border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0;box-shadow:0 2px 8px #0000000d}
input,textarea,button{font:inherit;padding:10px;border:1px solid #bbb;border-radius:8px;margin:5px 0;width:100%;box-sizing:border-box}
button{cursor:pointer;width:auto}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#eee}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head><body>
<h1>Colab Agent Platform</h1><p>Phase 11 adds production validation, reproducibility manifests, immutable strategy versions, regression gates, promotion controls, and readiness scoring.</p>
<div class="grid"><section class="card"><h2>New workspace</h2><input id="name" placeholder="Workspace name"><textarea id="goal" placeholder="Product goal"></textarea><button onclick="createWorkspace()">Create workspace</button><p id="workspaceResult"></p></section>
<section class="card"><h2>Operations</h2><div id="metrics">Loading…</div></section></div>
<section class="card"><h2>Workspaces</h2><div id="workspaces">Loading…</div></section>
<section class="card"><h2>Approved tools</h2><div id="tools">Loading…</div></section>
<script>
async function load(){const [w,t,m]=await Promise.all([fetch('/api/workspaces').then(r=>r.json()),fetch('/api/tools').then(r=>r.json()),fetch('/api/operations/metrics').then(r=>r.json())]);
document.getElementById('workspaces').innerHTML=w.length?w.map(x=>`<p><strong>${x.name}</strong> <span class="pill">${x.status}</span><br>${x.product_goal}</p>`).join(''):'No workspaces yet.';
document.getElementById('tools').innerHTML=t.map(x=>`<p><strong>${x.name}</strong> — ${x.description}</p>`).join('');
document.getElementById('metrics').innerHTML=`Pending: ${m.pending} · Running: ${m.running} · Succeeded: ${m.succeeded} · Failed: ${m.failed} · Retries: ${m.retries}`;}
async function createWorkspace(){const body={name:document.getElementById('name').value,product_goal:document.getElementById('goal').value};const key=crypto.randomUUID();const button=event.currentTarget;button.disabled=true;button.textContent='Creating…';try{const r=await fetch('/api/workspaces',{method:'POST',headers:{'content-type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)});document.getElementById('workspaceResult').textContent=r.ok?'Workspace created.':(await r.text());await load();}finally{button.disabled=false;button.textContent='Create workspace';}}
load();
</script></body></html>"""
