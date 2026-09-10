# ruff: noqa: I001, BLE001
"""Phase 21G/21H worker: lease jobs, execute workloads, publish artifacts with traces."""
from __future__ import annotations
import os
import socket
import time
from math import isnan
from typing import Any
from .background_job_handlers import report_generation, research_ingestion
from .background_jobs_store import PostgresJobQueue
from .observability import correlation, job_context, observe_job, registry, span
from .quant_lab import FeatureEngineer, QuantitativeResearchLab
from .quant_platform import monte_carlo, robustness_analysis

def _backtest(payload:dict[str,Any],progress:Any)->dict[str,Any]:
 from .quant_api import QuantRunRequest, _dataset
 r=QuantRunRequest.model_validate(payload); progress(15,"Preparing market dataset"); dataset=_dataset(r); features=FeatureEngineer().build(dataset,(r.fast_window,r.slow_window))
 def strategy(context:Any)->float:
  values=context.features.rows[context.index].values; fast=values.get(f"sma_{context.parameters['fast_window']}"); slow=values.get(f"sma_{context.parameters['slow_window']}")
  if fast is None or slow is None or isnan(fast) or isnan(slow):return 0.0
  return 1.0 if fast>slow else 0.0
 progress(55,"Running backtest"); result=QuantitativeResearchLab().backtest(dataset,features,strategy,{"fast_window":r.fast_window,"slow_window":r.slow_window},initial_capital=r.initial_capital); progress(90,"Finalizing backtest artifact"); return {"workspace_id":str(r.workspace_id),"dataset_checksum":dataset.checksum,"features":list(features.feature_names),"result":result.model_dump(mode="json")}
def _monte_carlo(payload:dict[str,Any],progress:Any)->dict[str,Any]:
 from .quant_api import MonteCarloRequest
 r=MonteCarloRequest.model_validate(payload); progress(20,"Running Monte Carlo simulations"); value=monte_carlo(r.returns,r.simulations,r.horizon,r.seed,r.drawdown_threshold); progress(95,"Finalizing simulation artifact"); return value.model_dump(mode="json")
def _robustness(payload:dict[str,Any],progress:Any)->dict[str,Any]:
 from .quant_api import RobustnessRequest
 r=RobustnessRequest.model_validate(payload); progress(20,"Running robustness perturbations"); value=robustness_analysis(r.returns,r.perturbations,r.seed,r.min_sharpe); progress(95,"Finalizing robustness artifact"); return value.model_dump(mode="json")
def _evaluate(payload:dict[str,Any],progress:Any)->dict[str,Any]:
 from .agent_vertical_slice import AgentPlatformVerticalSlice
 from uuid import UUID
 progress(20,"Preparing agent evaluation"); p=AgentPlatformVerticalSlice(); version=p.register(UUID(payload["agent_id"]),payload.get("config",{})); progress(50,"Running agent evaluation"); evaluation=p.evaluate(version,task_type=payload["task_type"],benchmark_id=payload["benchmark_id"],score=float(payload["score"]),evidence=payload.get("evidence",[])); performance=p.record_performance(evaluation); progress(95,"Finalizing evaluation artifact"); return {"agent_version":version.__dict__,"evaluation":evaluation.__dict__,"performance":performance.__dict__}
HANDLERS={"research_ingestion":research_ingestion,"embedding":research_ingestion,"backtest":_backtest,"monte_carlo":_monte_carlo,"robustness_analysis":_robustness,"report_generation":report_generation,"agent_evaluation":_evaluate}
class BackgroundWorker:
 def __init__(self,queue:PostgresJobQueue,worker_id:str)->None:self.queue=queue; self.worker_id=worker_id
 def run_once(self)->bool:
  job=self.queue.claim(self.worker_id)
  if job is None:return False
  started=time.perf_counter()
  attempt=getattr(job,"attempts",1)
  with correlation(getattr(job,"correlation_id",None)):
   with job_context(str(job.job_id)):
    with span("workflow.job",attributes={"job.type":job.job_type,"job.attempt":attempt,"worker.id":self.worker_id,"workspace.id":job.workspace_id}):
     try:
      handler=HANDLERS[job.job_type]
      with span("agent.handler",attributes={"job.type":job.job_type}):
       def progress(value:int,message:str)->None:
        with span("job.progress",attributes={"progress.value":value}):
         self.queue.progress(job.job_id,self.worker_id,value,message); self.queue.heartbeat(job.job_id,self.worker_id)
       with span("job.execute",attributes={"job.type":job.job_type}): result=handler(job.payload,progress)
      with span("artifact.write",attributes={"job.type":job.job_type}): self.queue.complete(job.job_id,self.worker_id,result,job.job_type)
      registry.increment("jobs.completed"); observe_job("completed",(time.perf_counter()-started)*1000,job.job_type,attempt)
     except Exception as exc:
      with span("job.failure",attributes={"error.type":type(exc).__name__}) as failure_span:
       failure_span.record_exception(exc)
      self.queue.fail(job.job_id,self.worker_id,f"{type(exc).__name__}: {exc}")
      registry.increment("jobs.failed"); observe_job("failed",(time.perf_counter()-started)*1000,job.job_type,attempt)
  return True
 def run_forever(self,poll_seconds:float=2.0)->None:
  while True:
   if not self.run_once():time.sleep(poll_seconds)
def main()->None:
 dsn=os.getenv("COLAB_DATABASE_DSN")
 if not dsn:raise RuntimeError("COLAB_DATABASE_DSN is required for background workers")
 from .service_adapters import production_connection_factory_from_dsn
 q=PostgresJobQueue(production_connection_factory_from_dsn(dsn),int(os.getenv("COLAB_JOB_LEASE_SECONDS","300"))); BackgroundWorker(q,os.getenv("COLAB_WORKER_ID",f"worker-{socket.gethostname()}" )).run_forever(float(os.getenv("COLAB_WORKER_POLL_SECONDS","2")))
if __name__=="__main__":main()
