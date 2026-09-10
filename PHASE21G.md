# Phase 21G — Production Background Jobs

Phase 21G moves expensive work out of synchronous API requests:

`API → Job → Queue → Worker → Progress → Artifact → Notification`

## Workloads

The durable job contract supports `research_ingestion`, `embedding`, `backtest`, `monte_carlo`, `robustness_analysis`, `report_generation`, and `agent_evaluation`.

## API

- `POST /api/jobs` accepts a serializable payload and returns HTTP 202.
- `GET /api/jobs/{job_id}` returns status, attempt, lease and progress state.
- `GET /api/jobs/{job_id}/events` returns progress history.
- `GET /api/jobs/{job_id}/artifact` returns the immutable result artifact after success.
- `POST /api/jobs/{job_id}/cancel` requests cancellation.
- `GET /api/jobs?workspace_id=...` lists recent jobs for a workspace.

Every enqueue requires a workspace-scoped idempotency key, preventing duplicate expensive work from retried HTTP requests.

## Queue and worker

Production uses PostgreSQL with `FOR UPDATE SKIP LOCKED` claiming and expiring worker leases. A crashed worker therefore does not permanently own a job. Failed jobs are retried up to `max_attempts`.

Start a worker with:

```bash
COLAB_ENV=production COLAB_DATABASE_DSN=... colab-worker
```

Useful settings are `COLAB_JOB_LEASE_SECONDS`, `COLAB_WORKER_ID`, and `COLAB_WORKER_POLL_SECONDS`.

## Artifacts and safety

Worker results are persisted as content-addressed JSON artifacts and linked to the job. API clients never receive a long-running synchronous request for these workloads. RLS restricts job, event, and artifact reads to workspace members.

No live trading or order-execution capability is introduced by Phase 21G.
