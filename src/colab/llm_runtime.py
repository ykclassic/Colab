"""Provider-neutral model runtime with structured output and hard budgets.

The runtime deliberately knows nothing about any vendor SDK. Providers implement
``ModelProvider`` and return normalized ``ModelResponse`` values. The runtime owns
validation, request limits, and accounting so an agent cannot silently bypass them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import monotonic
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ModelRuntimeError(RuntimeError):
    """Base error for model-runtime failures."""


class ModelProviderError(ModelRuntimeError):
    """Raised when a provider cannot complete a model request."""


class BudgetExceeded(ModelRuntimeError):
    """Raised before a request when the configured hard budget is exhausted."""


class StructuredOutputError(ModelRuntimeError):
    """Raised when a model response cannot satisfy its required schema."""


class ModelPolicy(BaseModel):
    """Explicit model policy selected by the application, not by the model."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_output_tokens: int = Field(default=2048, ge=1, le=100_000)
    max_requests: int = Field(default=20, ge=1)
    max_input_tokens: int = Field(default=20_000, ge=1)


class ModelRequest(BaseModel):
    """Normalized request sent to a provider adapter."""

    model_config = ConfigDict(extra="forbid")

    system: str = Field(default="", max_length=100_000)
    prompt: str = Field(min_length=1, max_length=200_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


@dataclass(frozen=True)
class ModelResponse:
    """Normalized provider response."""

    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider_request_id: str | None = None


class ModelProvider(ABC):
    """Vendor-neutral provider contract.

    Implementations must enforce the supplied timeout and must not expose API
    credentials through exceptions, response metadata, or logs.
    """

    name: str

    @abstractmethod
    def complete(self, request: ModelRequest, policy: ModelPolicy) -> ModelResponse:
        raise NotImplementedError


class DeterministicModelProvider(ModelProvider):
    """Offline provider used for tests and deterministic local development."""

    name = "deterministic"

    def complete(self, request: ModelRequest, policy: ModelPolicy) -> ModelResponse:
        del policy
        return ModelResponse(
            output=request.prompt,
            input_tokens=_estimate_tokens(request.system + request.prompt),
            output_tokens=_estimate_tokens(request.prompt),
            provider_request_id="deterministic",
        )


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    requests: int
    input_tokens: int
    output_tokens: int


class BudgetLedger:
    """Process-local hard budget ledger.

    A production deployment should persist or centrally coordinate these counters
    when workflows can span multiple processes. The runtime still enforces the
    policy locally before every request.
    """

    def __init__(self) -> None:
        self._requests = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def reserve(self, policy: ModelPolicy, estimated_input_tokens: int) -> None:
        if self._requests >= policy.max_requests:
            raise BudgetExceeded("model request budget exhausted")
        if estimated_input_tokens > policy.max_input_tokens:
            raise BudgetExceeded("estimated input exceeds model policy limit")
        if self._input_tokens + estimated_input_tokens > policy.max_input_tokens:
            raise BudgetExceeded("input token budget exhausted")

    def record(self, response: ModelResponse) -> None:
        self._requests += 1
        self._input_tokens += max(response.input_tokens, 0)
        self._output_tokens += max(response.output_tokens, 0)

    def usage(self) -> Usage:
        return Usage(self._requests, self._input_tokens, self._output_tokens)


class ModelRuntime:
    """Execute bounded model calls and validate structured responses."""

    def __init__(self, providers: dict[str, ModelProvider], ledger: BudgetLedger | None = None) -> None:
        if not providers:
            raise ValueError("at least one model provider is required")
        self._providers = dict(providers)
        self._ledger = ledger or BudgetLedger()

    @property
    def usage(self) -> Usage:
        return self._ledger.usage()

    def complete(self, request: ModelRequest, policy: ModelPolicy) -> ModelResponse:
        provider = self._providers.get(policy.provider)
        if provider is None:
            raise ModelProviderError(f"model provider is not configured: {policy.provider}")
        estimated = _estimate_tokens(request.system + request.prompt)
        self._ledger.reserve(policy, estimated)
        started = monotonic()
        try:
            response = provider.complete(request, policy)
        except ModelRuntimeError:
            raise
        except TimeoutError as exc:
            raise ModelProviderError("model provider timed out") from exc
        except Exception as exc:
            raise ModelProviderError("model provider request failed") from exc
        elapsed = monotonic() - started
        if elapsed > policy.timeout_seconds:
            raise ModelProviderError("model provider exceeded configured timeout")
        if response.output_tokens > policy.max_output_tokens:
            raise ModelProviderError("provider response exceeded output token limit")
        self._ledger.record(response)
        return response

    def structured(self, request: ModelRequest, policy: ModelPolicy, schema: type[T]) -> T:
        response = self.complete(request, policy)
        try:
            return schema.model_validate_json(response.output)
        except (ValidationError, ValueError, TypeError) as exc:
            raise StructuredOutputError("model response did not match required schema") from exc


def _estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate used only for preflight budgeting."""
    return max(1, (len(text) + 3) // 4) if text else 0
