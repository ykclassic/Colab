from uuid import uuid4
import pytest
from colab.background_jobs import InMemoryJobQueue, JobStatus, JOB_TYPES


def test_enqueue_is_idempotent_and_claims_in_order():
    q=InMemoryJobQueue(lease_seconds=60); workspace=uuid4()
    a=q.enqueue(workspace,"monte_carlo",{"returns":[0.1,0.2]},"same")
    b=q.enqueue(workspace,"monte_carlo",{"returns":[9]},"same")
    assert a.job_id==b.job_id and a.status==JobStatus.QUEUED
    claimed=q.claim("worker-a")
    assert claimed is not None and claimed.attempt==1 and claimed.lease_owner=="worker-a"


def test_progress_must_be_monotonic_and_completion_creates_artifact():
    q=InMemoryJobQueue(); job=q.enqueue(uuid4(),"backtest",{},"k"); claimed=q.claim("w")
    assert claimed is not None
    q.progress(job.job_id,"w",40,"running")
    with pytest.raises(ValueError): q.progress(job.job_id,"w",20,"backwards")
    done=q.complete(job.job_id,"w",{"metric":1},"backtest")
    assert done.status==JobStatus.SUCCEEDED and done.progress==100 and done.artifact_id in q.artifacts


def test_wrong_worker_and_retry_are_rejected_or_requeued():
    q=InMemoryJobQueue(); job=q.enqueue(uuid4(),"robustness_analysis",{},"k",max_attempts=2); q.claim("w")
    with pytest.raises(PermissionError): q.progress(job.job_id,"other",10,"x")
    retried=q.fail(job.job_id,"w","temporary")
    assert retried.status==JobStatus.QUEUED and retried.attempt==1
    q.claim("w2"); failed=q.fail(job.job_id,"w2","permanent")
    assert failed.status==JobStatus.FAILED


def test_supported_workload_contract_is_explicit():
    assert JOB_TYPES==frozenset({"research_ingestion","embedding","backtest","monte_carlo","robustness_analysis","report_generation","agent_evaluation"})
    with pytest.raises(ValueError): InMemoryJobQueue().enqueue(uuid4(),"unknown",{},"x")
