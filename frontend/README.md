# Colab Command Center

Phase 5.5 adds a dedicated Next.js interface over the existing FastAPI read APIs. It is intentionally a visual/read-only operating surface; it does not duplicate workflow business logic.

## Run locally

```bash
cd frontend
npm install
NEXT_PUBLIC_COLAB_API_URL=http://localhost:8000 npm run dev
```

The FastAPI service should be running separately. For a deployed frontend, set `NEXT_PUBLIC_COLAB_API_URL` to the deployed API origin.

## Routes

- `/` — platform dashboard
- `/workflows` — lifecycle and agent responsibilities
- `/workspaces` — active workspace portfolio
- `/research` — research/knowledge surface
- `/artifacts` — artifact lineage surface
- `/operations` — execution and telemetry
- `/governance` — risk and human approval boundaries

## Security boundary

Phase 5.5 does not expose approval mutations. Phase 5 provides JWT/RBAC primitives, but endpoint authentication/authorization and durable approval APIs must be wired before this frontend becomes a write-capable governance console.
