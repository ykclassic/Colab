# Phase 3 API

- `GET /health` — service health.
- `GET /` — product dashboard.
- `POST /api/workspaces` — create a product workspace.
- `GET /api/workspaces` — list workspaces by priority.
- `GET /api/workspaces/{workspace_id}` — inspect a workspace.
- `POST /api/workspaces/{workspace_id}/artifacts` — create a versioned artifact.
- `GET /api/workspaces/{workspace_id}/artifacts` — list artifact history.
- `POST /api/knowledge` — add a knowledge document.
- `GET /api/knowledge/search?q=...` — deterministic knowledge search.
- `GET /api/tools` — inspect the current tool allow-list.

The Phase 3 API is intentionally not an execution API. It does not expose live order submission or exchange credentials.
