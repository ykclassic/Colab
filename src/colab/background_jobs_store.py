# ruff: noqa: I001, UP035, F401
"""PostgreSQL implementation of the Phase 21G queue contract."""
from __future__ import annotations
import json
from typing import Any
from uuid import UUID
from collections.abc import Callable
from psycopg import Connection
from .background_jobs import BackgroundJob, JobArtifact, JobEvent

class PostgresJobQueue:
 def __init__(self,connection_factory:Callable[[],Connection[Any]],lease_seconds:int=300)->None:
  if lease_seconds<1:raise ValueError("lease_seconds must be positive")
  self.connection_factory=connection_factory; self.lease_seconds=lease_seconds
 def enqueue(self,workspace_id:UUID,job_type:str,payload:dict[str,Any],idempotency_key:str,workflow_id:UUID|None=None,max_attempts:int=3)->BackgroundJob:
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("INSERT INTO public.background_jobs(workspace_id,workflow_id,job_type,idempotency_key,payload,max_attempts) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,idempotency_key) DO NOTHING RETURNING *",(workspace_id,workflow_id,job_type,idempotency_key,json.dumps(payload),max_attempts)); row=x.fetchone()
   if row is None:x.execute("SELECT * FROM public.background_jobs WHERE workspace_id=%s AND idempotency_key=%s",(workspace_id,idempotency_key)); row=x.fetchone()
   return self._job(row)
 def get(self,job_id:UUID)->BackgroundJob:
  with self.connection_factory() as c,c.cursor() as x:
   x.execute("SELECT * FROM public.background_jobs WHERE job_id=%s",(job_id,)); row=x.fetchone()
   if row is None:raise KeyError(str(job_id))
   return self._job(row)
 def list(self,workspace_id:UUID,limit:int=100)->list[BackgroundJob]:
  with self.connection_factory() as c,c.cursor() as x:
   x.execute("SELECT * FROM public.background_jobs WHERE workspace_id=%s ORDER BY created_at DESC LIMIT %s",(workspace_id,limit)); return [self._job(r) for r in x.fetchall()]
 def claim(self,worker_id:str)->BackgroundJob|None:
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("SELECT * FROM public.phase21g_claim_background_job(%s,%s)",(worker_id,self.lease_seconds)); row=x.fetchone(); return None if row is None else self._job(row)
 def heartbeat(self,job_id:UUID,worker_id:str)->BackgroundJob:
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("UPDATE public.background_jobs SET lease_expires_at=now()+make_interval(secs=>%s) WHERE job_id=%s AND status='running' AND lease_owner=%s RETURNING *",(self.lease_seconds,job_id,worker_id)); row=x.fetchone()
   if row is None:raise PermissionError("worker does not own job lease")
   return self._job(row)
 def progress(self,job_id:UUID,worker_id:str,value:int,message:str)->BackgroundJob:
  if not 0<=value<=100:raise ValueError("progress must be between 0 and 100")
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("UPDATE public.background_jobs SET progress=%s,progress_message=%s WHERE job_id=%s AND status='running' AND lease_owner=%s AND progress<=%s RETURNING *",(value,message,job_id,worker_id,value)); row=x.fetchone()
   if row is None:raise RuntimeError("job is not owned or progress moved backwards")
   x.execute("INSERT INTO public.background_job_events(job_id,workspace_id,status,progress,message) VALUES(%s,%s,'running',%s,%s)",(job_id,row[1],value,message)); return self._job(row)
 def complete(self,job_id:UUID,worker_id:str,result:dict[str,Any],kind:str)->BackgroundJob:
  raw=json.dumps(result,sort_keys=True,separators=(",",":")); digest=__import__('hashlib').sha256(raw.encode()).hexdigest()
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("SELECT * FROM public.background_jobs WHERE job_id=%s AND status='running' AND lease_owner=%s FOR UPDATE",(job_id,worker_id)); row=x.fetchone()
   if row is None:raise PermissionError("worker does not own job lease")
   x.execute("INSERT INTO public.background_job_artifacts(job_id,workspace_id,kind,content,content_hash) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(job_id,content_hash) DO UPDATE SET content=EXCLUDED.content RETURNING artifact_id",(job_id,row[1],kind,raw,digest)); artifact_id=x.fetchone()[0]
   x.execute("UPDATE public.background_jobs SET status='succeeded',progress=100,result=%s,artifact_id=%s,lease_owner=NULL,lease_expires_at=NULL,completed_at=now() WHERE job_id=%s RETURNING *",(raw,artifact_id,job_id)); return self._job(x.fetchone())
 def fail(self,job_id:UUID,worker_id:str,error:str)->BackgroundJob:
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("UPDATE public.background_jobs SET status=CASE WHEN attempt<max_attempts THEN 'queued' ELSE 'failed' END,error=%s,lease_owner=NULL,lease_expires_at=NULL,completed_at=CASE WHEN attempt<max_attempts THEN NULL ELSE now() END WHERE job_id=%s AND status='running' AND lease_owner=%s RETURNING *",(error[:5000],job_id,worker_id)); row=x.fetchone()
   if row is None:raise PermissionError("worker does not own job lease")
   return self._job(row)
 def cancel(self,job_id:UUID)->BackgroundJob:
  with self.connection_factory() as c,c.transaction(),c.cursor() as x:
   x.execute("UPDATE public.background_jobs SET status='cancelled',completed_at=now() WHERE job_id=%s AND status NOT IN ('succeeded','failed','cancelled') RETURNING *",(job_id,)); row=x.fetchone()
   return self._job(row) if row else self.get(job_id)
 def events_for(self,job_id:UUID)->list[JobEvent]:
  with self.connection_factory() as c,c.cursor() as x:
   x.execute("SELECT event_id,job_id,workspace_id,status,progress,message,metadata,created_at FROM public.background_job_events WHERE job_id=%s ORDER BY created_at",(job_id,)); return [JobEvent(event_id=r[0],job_id=r[1],workspace_id=r[2],status=r[3],progress=r[4],message=r[5],metadata=r[6] or {},created_at=r[7]) for r in x.fetchall()]
 def artifact(self,job_id:UUID)->JobArtifact|None:
  with self.connection_factory() as c,c.cursor() as x:
   x.execute("SELECT artifact_id,job_id,workspace_id,kind,content,content_hash,created_at FROM public.background_job_artifacts WHERE job_id=%s ORDER BY created_at DESC LIMIT 1",(job_id,)); r=x.fetchone(); return None if r is None else JobArtifact(artifact_id=r[0],job_id=r[1],workspace_id=r[2],kind=r[3],content=r[4],content_hash=r[5],created_at=r[6])
 def _job(self,r:Any)->BackgroundJob:
  cols=['job_id','workspace_id','workflow_id','job_type','idempotency_key','status','payload','progress','progress_message','attempt','max_attempts','lease_owner','lease_expires_at','artifact_id','result','error','notification_status','notification_error','created_at','started_at','completed_at','updated_at']; return BackgroundJob(**dict(zip(cols,r)))
