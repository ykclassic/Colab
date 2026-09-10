from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

from colab.observability import JsonFormatter, correlation, correlation_id, job_context, registry, span


def test_correlation_id_is_stable_inside_context() -> None:
    with correlation("corr-21h"):
        assert correlation_id() == "corr-21h"
        with job_context("job-21h"):
            assert correlation_id() == "corr-21h"
    assert correlation_id() != "corr-21h"


def test_span_records_context_attributes() -> None:
    with correlation("corr-span"):
        with job_context(str(uuid4())):
            with span("test.boundary", attributes={"workflow.id": UUID(int=0), "attempt": 2}) as current:
                assert current.is_recording()


def test_structured_formatter_is_json() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    with correlation("corr-log"):
        payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["correlation_id"] == "corr-log"


def test_metrics_registry_increments_and_snapshots() -> None:
    registry.increment("phase21h.test")
    registry.increment("phase21h.test", 2)
    assert registry.snapshot()["phase21h.test"] >= 3
