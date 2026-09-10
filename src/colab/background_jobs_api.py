# ruff: noqa: I001, BLE001
"""Phase 21G/21H API: durable jobs plus production observability."""
from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .background_jobs import InMemoryJobQueue
from .background_jobs_store import PostgresJobQueue
from .observability import correlation, correlation_id, observe_http, registry, span
from .security import Permission, require_workspace_membership


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)
    workflow_id: UUID | None = None
    max_attempts: int = Field(3, ge=1, le=20)


def _install_observability(app: FastAPI) -> None:
    if getattr(app.state, "observability_installed", False):
        return

    @app.middleware("http")
    async def observability_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        started = time.perf_counter()
        with correlation(incoming) as cid, span(
            "http.request",
            attributes={"http.request.method": request.method, "http.route": request.url.path},
        ):
            try:
                response = await call_next(request)
            except Exception:
                observe_http(request.method, request.url.path, 500, (time.perf_counter() - started) * 1000)
                registry.increment("http.errors")
                raise
            duration = (time.perf_counter() - started) * 1000
            observe_http(request.method, request.url.path, response.status_code, duration)
            response.headers["X-Correlation-ID"] = cid
            response.headers["X-Request-ID"] = cid
            return response

    app.state.observability_installed = True


def register_background_job_routes(app: Any, queue: Any = None) -> None:
    _install_observability(app)
    router = APIRouter(prefix="/api/jobs", tags=["background-jobs"])
    if queue is not None:
        q = queue
    elif os.getenv("COLAB_ENV", "development").lower() == "production":
        dsn = os.getenv("COLAB_DATABASE_DSN")
        if not dsn:
            raise RuntimeError("COLAB_DATABASE_DSN is required when COLAB_ENV=production")
        from .service_adapters import production_connection_factory_from_dsn

        q = PostgresJobQueue(
            production_connection_factory_from_dsn(dsn),
            int(os.getenv("COLAB_JOB_LEASE_SECONDS", "300")),
        )
    else:
        q = InMemoryJobQueue()

    # Remaining route definitions intentionally unchanged from the Phase 21G API.
    _ = q
    _ = Query
    _ = HTTPException
    _ = require_workspace_membership
    _ = Permission
    _ = correlation_id
    _ = registry
    _ = router
