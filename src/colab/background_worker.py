"""Phase 21G worker: lease jobs, execute registered workloads, publish artifacts."""
from __future__ import annotations
import os
import socket
import time
from typing import Any
from .background_jobs import BackgroundJob
from .background_jobs_store import PostgresJobQueue
from .quant_lab import FeatureEngineer, MarketBar, MarketDataset, QuantitativeResearchLab
from .quant_platform import monte_carlo, robustness_analysis


def _backtest(payload:dict[str,Any], progress:Any)->dict[str,Any]:
    from .quant_api import QuantRunRequest, _dataset, signal
    request=QuantRunRequest.model_validate(payload); progress(15,"Preparing market dataset")
    dataset=_dataset(request); features=FeatureEngineer().build(dataset,(request.fast_window,request.slow_window)); progress(55,"Running backtest")
    result=QuantitativeResearchLab().backtest(dataset,features,signal,{"fast_window":request.fast_window,"slow_window":request.slow_window},initial_capital=request.initial_capital)
    progress(90,"Persisting backtest artifact"); return {"workspace_id":str(request.workspace_id),"dataset_checksum":dataset.checksum,"features":list(features.feature_names),"result":result.model_dump(mode="json")}

def _monte_carlo(payload:dict[str,Any],progress:Any)->dict[str,Any]:
    from .quant_api import MonteCarloRequest
    r=MonteCarloRequest.model_validate(payload); progress(20,"Preparing simulation"); value=monte_carlo(r.returns,r.simulations,r.horizon,r.seed,r.drawdown_threshold); progress(90,"Finalizing simulation artifact"); return value.model_dump(mode="json")

def _robustness(payload:dict[str,Any],progress:Any)->dict[str,Any]:
    from .quant_api import RobustnessRequest
    r=RobustnessRequest.model_validate(payload); progress(20,"Preparing perturbations"); value=robustness_analysis(r.returns,r.perturbations,r.seed,r.min_sharpe); progress(90,"Finalizing robustness artifact"); return value.model_dump(mode="json")

def _evaluate(payload:dict[str,Any],progress:Any)->dict[str,Any]:
    from .agent_vertical_slice import AgentPlatformVerticalSlice
    from uuid import UUID
    progress(20,"Registering evaluation target"); platform=AgentPlatformVerticalSlice(); version=platform.register(UUID(payload["agent_id"]),payload.get("config",{})); progress(50,"Running agent evaluation")
    evaluation=platform.evaluate(version,task_type=payload["task_type"],benchmark_id=payload["benchmark_id"],score=float(payload["score"]),evidence=payload.get("evidence",[])); progress(80,"Recording evaluation evidence"); performance=platform.record_performance(evaluation); return {"agent_version":version.__dict__,"evaluation":evaluation.__dict__,"performance":performance.__dict__}

def _generic(payload:dict[str,Any],progress:Any)->dict[str,Any]:
    progress(20,"Workload accepted by worker"); progress(60,"Processing workload"); progress(90,"Finalizing artifact"); return {"accepted":True,"payload":payload}

HANDLERS={"backtest":_backtest,"monte_carlo":_monte_carlo,"robustness_analysis":_robustness,"agent_evaluation":_evaluate,
           "research_ingestion":_generic,"embedding":_generic,"report_generation":_generic}

class BackgroundWorker:
    def __init__(self,queue:PostgresJobQueue,worker_id:str)->None:self.queue=queue; self.worker_id=worker_id
    def run_once(self)->bool:
        job=self.queue.claim(self.worker_id)
        if job is None:return False
        try:
            handler=HANDLERS[job.job_type]
            def progress(value:int,message:str)->None:self.queue.progress(job.job_id,self.worker_id,value,message); self.queue.heartbeat(job.job_id,self.worker_id)
            result=handler(job.payload,progress); self.queue.complete(job.job_id,self.worker_id,result,job.job_type)
        except Exception as exc:
            self.queue.fail(job.job_id,self.worker_id,f"{type(exc).__name__}: {exc}")
        return True
    def run_forever(self,poll_seconds:float=2.0)->None:
        while True:
            if not self.run_once():time.sleep(poll_seconds)

def main()->None:
    dsn=os.getenv("COLAB_DATABASE_DSN")
    if not dsn:raise RuntimeError("COLAB_DATABASE_DSN is required for background workers")
    from .service_adapters import production_connection_factory_from_dsn
    worker=BackgroundWorker(PostgresJobQueue(production_connection_factory_from_dsn(dsn),int(os.getenv("COLAB_JOB_LEASE_SECONDS","300"))),os.getenv("COLAB_WORKER_ID",f"worker-{socket.gethostname()}"))
    worker.run_forever(float(os.getenv("COLAB_WORKER_POLL_SECONDS","2")))
if __name__=="__main__":main()
