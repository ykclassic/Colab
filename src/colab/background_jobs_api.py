# ruff: noqa: I001
"""Phase 21G API: accept work quickly and expose durable progress/results."""
from __future__ import annotations
import os
from typing import Any
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .background_jobs import InMemoryJobQueue
from .background_jobs_store import PostgresJobQueue
from .security import Permission, require_workspace_membership
class JobCreate(BaseModel):
 model_config=ConfigDict(extra="forbid")
 workspace_id:UUID; job_type:str; payload:dict[str,Any]=Field(default_factory=dict); idempotency_key:str=Field(min_length=1,max_length=255); workflow_id:UUID|None=None; max_attempts:int=Field(3,ge=1,le=20)
def register_background_job_routes(app:Any,queue:Any=None)->None:
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
 def enqueue(payload:JobCreate,request:Request):
  require_workspace_membership(request,payload.workspace_id,Permission.RESEARCH_WRITE)
  try:return q.enqueue(payload.workspace_id,payload.job_type,payload.payload,payload.idempotency_key,payload.workflow_id,payload.max_attempts)
  except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc
 @router.get("")
 def list_jobs(request:Request,workspace_id:UUID,limit:int=Query(100,ge=1,le=1000)):
  require_workspace_membership(request,workspace_id,Permission.WORKSPACE_READ); return q.list(workspace_id,limit)
 @router.get("/{job_id}")
 def status(job_id:UUID,request:Request):
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.WORKSPACE_READ); return j
 @router.get("/{job_id}/events")
 def events(job_id:UUID,request:Request):
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.WORKSPACE_READ); return q.events_for(job_id)
 @router.get("/{job_id}/artifact")
 def artifact(job_id:UUID,request:Request):
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.WORKSPACE_READ)
  if j.artifact_id is None:return {"status":j.status,"artifact":None}
  if hasattr(q,"artifacts"):return q.artifacts[j.artifact_id]
  return q.artifact(job_id)
 @router.post("/{job_id}/cancel")
 def cancel(job_id:UUID,request:Request):
  try:j=q.get(job_id)
  except KeyError as exc:raise HTTPException(status_code=404,detail="job not found") from exc
  require_workspace_membership(request,j.workspace_id,Permission.RESEARCH_WRITE); return q.cancel(job_id)
 app.include_router(router)
