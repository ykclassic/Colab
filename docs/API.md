# Colab API

## Overview

Colab exposes a FastAPI HTTP API.

Base path:

```text
/api
```

Health endpoints:

```text
GET /health
GET /ready
```

## API Domains

The API is organized around workspaces, workflows, research, quantitative research, artifacts, operations and governance.

Representative resources include:

```text
/api/workspaces
/api/workspaces/{workspace_id}
/api/operations/metrics
/api/operations/events
```

Research, quant and governance routes are exposed through their respective API routers.

## Authentication

Protected requests should use:

```http
Authorization: Bearer <JWT>
```

The authenticated principal should be resolved before protected operations are executed.

## Authorization

Workspace-scoped requests must verify membership and the required permission. Never rely on a client-supplied workspace ID as proof of authorization.

## Idempotency

Retryable write operations should use an idempotency key where appropriate:

```http
Idempotency-Key: <unique-request-id>
```

## API Design Requirements

Endpoints should enforce:

- schema validation
- authentication
- authorization
- workspace isolation
- rate limiting
- bounded payloads
- deterministic errors
- auditability
- idempotency where required

## Production Security Requirement

Every workspace-scoped endpoint must be audited for authentication, authorization and tenant isolation. Database RLS is defense-in-depth, not a substitute for HTTP authorization.
