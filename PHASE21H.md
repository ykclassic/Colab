# Phase 21H — Observability & Reliability

Phase 21H adds production observability around the Phase 21G durable job system.

## Runtime path

`HTTP request → workflow/job → agent boundary → LLM/tool boundary hooks → DB/artifact boundaries → notification-ready job state`

The OpenTelemetry primitives in `colab.observability` provide a common tracer and context. Integrations should use `instrument_boundary("agent.invoke")`, `instrument_boundary("llm.call")`, `instrument_boundary("tool.call")`, `instrument_boundary("db.query")`, and `instrument_boundary("artifact.write")` around provider-specific boundaries.

## Correlation

Every HTTP request receives or creates an `X-Correlation-ID`. The ID is returned on the response and propagated through the worker context when a job carries a correlation ID. Job spans also attach `job.id`, `job.type`, `workspace.id`, `worker.id`, and attempt metadata.

## OpenTelemetry

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable OTLP HTTP span export. Without an endpoint, spans remain local and the application continues to operate without an external telemetry dependency. Never put secrets, prompts, document contents, access tokens, or database credentials in span attributes.

## Structured logs

Application logs are JSON records containing timestamp, severity, logger, message, correlation ID and job ID. Set `COLAB_LOG_LEVEL` to control verbosity.

## Metrics

The SDK exposes HTTP request count/latency and job completion/failure/retry count/latency metrics. `/api/observability/metrics` provides a small in-process operational snapshot for environments without a metrics backend.

## Health

`/health` remains the liveness endpoint. `/ready` remains the database readiness endpoint. `/api/observability/health` reports the queue/database mode. Production deployments should monitor both API readiness and worker process health.

## Failure and retry behavior

Worker failures are traced with exception events and recorded as failed job attempts through the existing Phase 21G queue. Lease expiry remains the recovery mechanism for abandoned workers. The observability layer does not change retry semantics or hide failures.

## Operational guidance

1. Export traces to an OTLP collector in production.
2. Aggregate metrics in a monitoring backend and alert on latency, failure rate, retry rate, queue age and worker absence.
3. Propagate `X-Correlation-ID` from API gateways and clients when available.
4. Keep telemetry attributes low-cardinality; use IDs only where operationally useful.
5. Redact credentials and sensitive payloads from logs and traces.
