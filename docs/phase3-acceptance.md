# Phase 3 acceptance

- Web dashboard and API are available from the application package.
- Workspace scheduling is bounded and priority-aware.
- Artifacts are content-addressed and versioned.
- Knowledge and tools have explicit service boundaries.
- Persistence tables are protected with RLS and browser access is denied until tenant identity exists.
- No live exchange execution capability is introduced.
- CI must pass Ruff, mypy, pytest, and the existing 90% coverage gate before merge.
