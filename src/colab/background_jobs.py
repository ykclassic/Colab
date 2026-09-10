# ruff: noqa: I001
"""Phase 21G durable background-job contracts and deterministic local queue."""
from __future__ import annotations
import builtins
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
JOB_TYPES=frozenset(("research_ingestion","embedding","backtest","monte_carlo","robustness_analysis","report_generation","agent_evaluation"))
class JobStatus:
 QUEUED="queued"; RUNNING="running"; SUCCEEDED="succeeded"; FAILED="failed"; CANCELLED="cancelled"
class BackgroundJob(BaseModel):
 model_config=ConfigDict(extra="forbid")
 job_id:UUID; workspace_id:UUID; workflow_id:UUID|None=None; job_type:str; idempotency_key:str; status:str=JobStatus.QUEUED; payload:dict[str,Any]=Field(default_factory=dict); progress:int=0; progress_message:str|None=None; attempt:int=0; max_attempts:int=3; lease_owner:str|None=None; lease_expires_at:datetime|None=None; artifact_id:UUID|None=None; result:dict[str,Any]|None=None; error:str|None=None; notification_status:str="pending"; notification_error:str|None=None; created_at:datetime; started_at:datetime|None=None; completed_at:datetime|None=None; updated_at:datetime
class JobEvent(BaseModel):
 model_config=ConfigDict(extra="forbid")
 event_id:UUID=Field(default_factory=uuid4); job_id:UUID; workspace_id:UUID; status:str; progress:int=Field(ge=0,le=100); message:str; metadata:dict[str,Any]=Field(default_factory=dict); created_at:datetime=Field(default_factory=lambda:datetime.now(UTC))
class JobArtifact(BaseModel):
 model_config=ConfigDict(extra="forbid")
 artifact_id:UUID=Field(default_factory=uuid4); job_id:UUID; workspace_id:UUID; kind:str; content:dict[str,Any]; content_hash:str; created_at:datetime=Field(default_factory=lambda:datetime.now(UTC))
@dataclass
class InMemoryJobQueue:
 lease_seconds:int=300; jobs:dict[UUID,BackgroundJob]=field(default_factory=dict); idempotency:dict[tuple[UUID,str],UUID]=field(default_factory=dict); events:list[JobEvent]=field(default_factory=list); artifacts:dict[UUID,JobArtifact]=field(default_factory=dict)
 def enqueue(self,workspace_id:UUID,job_type:str,payload:dict[str,Any],idempotency_key:str,workflow_id:UUID|None=None,max_attempts:int=3)->BackgroundJob:
  if job_type not in JOB_TYPES:raise ValueError(f"unsupported job type: {job_type}")
  key=(workspace_id,idempotency_key)
  if key in self.idempotency:return self.jobs[self.idempotency[key]]
  now=datetime.now(UTC); job=BackgroundJob(job_id=uuid4(),workspace_id=workspace_id,workflow_id=workflow_id,job_type=job_type,idempotency_key=idempotency_key,max_attempts=max_attempts,created_at=now,updated_at=now); self.jobs[job.job_id]=job; self.idempotency[key]=job.job_id; self._event(job,0,"Job queued"); return job
 def get(self,job_id:UUID)->BackgroundJob:return self.jobs[job_id]
 def list(self,workspace_id:UUID,limit:int=100)->builtins.list[BackgroundJob]:return sorted((j for j in self.jobs.values() if j.workspace_id==workspace_id),key=lambda j:j.created_at,reverse=True)[:limit]
 def claim(self,worker_id:str)->BackgroundJob|None:
  now=datetime.now(UTC)
  for job in sorted(self.jobs.values(),key=lambda j:(j.created_at,str(j.job_id))):
   expired=job.status==JobStatus.RUNNING and job.lease_expires_at is not None and job.lease_expires_at<=now
   if job.status==JobStatus.QUEUED or expired:
    if job.attempt>=job.max_attempts:continue
    job.status=JobStatus.RUNNING; job.attempt+=1; job.lease_owner=worker_id; job.lease_expires_at=now+timedelta(seconds=self.lease_seconds); job.started_at=job.started_at or now; job.updated_at=now; self._event(job,max(1,job.progress),"Worker claimed job",{"worker_id":worker_id}); return job
  return None
 def heartbeat(self,job_id:UUID,worker_id:str)->BackgroundJob:
  self._owner(job_id,worker_id); j=self.jobs[job_id]; j.lease_expires_at=datetime.now(UTC)+timedelta(seconds=self.lease_seconds); return j
 def progress(self,job_id:UUID,worker_id:str,value:int,message:str)->BackgroundJob:
  self._owner(job_id,worker_id); j=self.jobs[job_id]
  if value<j.progress or not 0<=value<=100:raise ValueError("progress must be monotonic and between 0 and 100")
  j.progress=value; j.progress_message=message; j.updated_at=datetime.now(UTC); self._event(j,value,message); return j
 def complete(self,job_id:UUID,worker_id:str,result:dict[str,Any],kind:str)->BackgroundJob:
  self._owner(job_id,worker_id); j=self.jobs[job_id]; raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode(); a=JobArtifact(job_id=j.job_id,workspace_id=j.workspace_id,kind=kind,content=result,content_hash=sha256(raw).hexdigest()); self.artifacts[a.artifact_id]=a; now=datetime.now(UTC); j.status=JobStatus.SUCCEEDED; j.progress=100; j.result=result; j.artifact_id=a.artifact_id; j.lease_owner=None; j.lease_expires_at=None; j.completed_at=now; j.updated_at=now; self._event(j,100,"Job completed",{"artifact_id":str(a.artifact_id)}); return j
 def fail(self,job_id:UUID,worker_id:str,error:str)->BackgroundJob:
  self._owner(job_id,worker_id); j=self.jobs[job_id]; j.error=error[:5000]; j.lease_owner=None; j.lease_expires_at=None; j.updated_at=datetime.now(UTC); j.status=JobStatus.QUEUED if j.attempt<j.max_attempts else JobStatus.FAILED; j.completed_at=None if j.status==JobStatus.QUEUED else datetime.now(UTC); self._event(j,j.progress,"Job retry scheduled" if j.status==JobStatus.QUEUED else "Job failed"); return j
 def cancel(self,job_id:UUID)->BackgroundJob:
  j=self.jobs[job_id]
  if j.status not in (JobStatus.SUCCEEDED,JobStatus.FAILED,JobStatus.CANCELLED):j.status=JobStatus.CANCELLED; j.completed_at=datetime.now(UTC); j.updated_at=datetime.now(UTC); self._event(j,j.progress,"Job cancelled")
  return j
 def events_for(self,job_id:UUID)->builtins.list[JobEvent]:return [e for e in self.events if e.job_id==job_id]
 def _owner(self,job_id:UUID,worker_id:str)->None:
  j=self.jobs[job_id]
  if j.status!=JobStatus.RUNNING or j.lease_owner!=worker_id:raise PermissionError("worker does not own job lease")
  if j.lease_expires_at is None or j.lease_expires_at<=datetime.now(UTC):raise RuntimeError("job lease has expired")
 def _event(self,j:BackgroundJob,p:int,m:str,metadata:dict[str,Any]|None=None)->None:self.events.append(JobEvent(job_id=j.job_id,workspace_id=j.workspace_id,status=j.status,progress=p,message=m,metadata=metadata or {}))
Handler=Callable[[BackgroundJob,Callable[[int,str],None]],dict[str,Any]]
@dataclass
class JobRegistry:
 handlers:dict[str,Handler]=field(default_factory=dict)
 def register(self,job_type:str,handler:Handler)->None:
  if job_type not in JOB_TYPES:raise ValueError(f"unsupported job type: {job_type}")
  self.handlers[job_type]=handler
 def get(self,job_type:str)->Handler:return self.handlers[job_type]
