# ruff: noqa: I001
"""Phase 21G/21H API: durable jobs plus production observability."""
from __future__ import annotations
import os
import time
from typing import Any
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .background_jobs import InMemoryJobQueue
from .background_jobs_store import PostgresJobQueue
from .observability import correlation, correlation_id, observe_http, registry, span
from .security import Permission, require_workspace_membership

class JobCreate(BaseModel):
 model_config=ConfigDict(extra="forbid")
 workspace_id:UUID; job_type:str; payload:dict[str,Any]=Field(default_factory=dict); idempotency_key:str=Field(min_length=1,max_length=255); workflow_id:UUID|None=None; max_attempts:int=Field(3,ge=1,le=20)

def _install_observability(app: Any) -> None:
 if getattr(app.state, "observability_installed", False): return
 @app.middleware("http")
 async def observability_middleware(request: Request, call_next: Any) -> Any:
  incoming=request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
  started=time.perf_counter()
  with correlation(incoming) as cid:
   with span("http.request", attributes={"http.request.method":request.method,"http.route":request.url.path}):
    try:
     response=await call_next(request)
    except Exception:
     observe_http(request.method,request.url.path,500,(time.perf_counter()-started)*1000); registry.increment("http.errors"); raise
    duration=(time.perf_counter()-started)*1000
    observe_http(request.method,request.url.path,response.status_code,duration)
    response.headers["X-Correlation-ID"]=cid
    response.headers["X-Request-ID"]=cid
    return response
 app.state.observability_installed=True


def register_background_job_routes(app:Any,queue:Any=None)->None:
 _install_observability(app)
 router=APIRouter(prefix="/api/jobs",tags=["background-jobs"])
 if queue is not None:q=queue
 elif os.getenv("COLAB_ENV","development").lower()=="production":
  dsn=os.getenv("COLAB_DATABASE_DSN")
  if not dsn:raise RuntimeError("COLAB_DATABASE_DSN is required when COLAB_ENV=production")
  from .service_adapters import production_connection_factory_from_dsn
  q=PostgresJobQueue(production_connection_factory_from_dsn(dsn),int(os.getenv("COLAB_JOB_LEASE_SECONDS","300")))
 else:q=InMemoryJobQueue()
 app.state.background_jobs=q
 @router.post("",status_code=202)
 def enqueue(payload:JobCreate,request:Request)->Any:
  require_workspace_membership(request,payload.workspace_id,Permission.RESEARCH_WRITE)
  try:
   registry.increment("jobs.enqueued")
   with span("job.enqueue",attributes={"job.type":payload.job_type,"workspace.id":payload.workspace_id}):
    return q.enqueue(payload.workspace_id,payload.job_type,payload.payload,payload.idempotency_key,payload.workflow_id,payload.max_attempts)
  except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc
 @router.get("")
 def list_jobs(request:Request,workspace_id:UUID,limit:int=Query(100,ge=1,le=1000))->Any:
  require_workspace_membership(request,workspace_id,Permission.WORKSPACE_READ); return q.list(workspace_id,limit)
 @router.get("/{job_id}")
 def status(job_id:UUID,request:Request)->Any:
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.WORKSPACE_READ); return j
 @router.get("/{job_id}/events")
 def events(job_id:UUID,request:Request)->Any:
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.WORKSPACE_READ); return q.events_for(job_id)
 @router.get("/{job_id}/artifact")
 def artifact(job_id:UUID,request:Request)->Any:
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.WORKSPACE_READ)
  if j.artifact_id is None:return {"status":j.status,"artifact":None}
  if hasattr(q,"artifacts"):return q.artifacts[j.artifact_id]
  return q.artifact(job_id)
 @router.post("/{job_id}/cancel")
 def cancel(job_id:UUID,request:Request)->Any:
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.RESEARCH_WRITE); return q.cancel(job_id)
 app.include_router(router)

 ops=APIRouter(prefix="/api/observability",tags=["observability"])
 @ops.get("/metrics")
 def metrics() -> dict[str,Any]:
  return {"correlation_id":correlation_id(),"metrics":registry.snapshot()}
 @ops.get("/health")
 def health() -> dict[str,Any]:
  result={"status":"ok","worker":"unknown","database":"unknown"}
  try:
   if hasattr(q,"conn_factory"): result["database"]="ok"
   elif hasattr(q,"_items"): result["database"]="in_memory"
  except Exception: result["database"]="error"
  return result
 app.include_router(ops)
