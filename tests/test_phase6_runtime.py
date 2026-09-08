import pytest
from pydantic import BaseModel, ConfigDict

from colab.agents import ModelBackedAgent
from colab.contracts import AgentRole, WorkflowState
from colab.llm_runtime import (
    BudgetExceeded,
    DeterministicModelProvider,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    ModelRuntime,
    ModelProvider,
    StructuredOutputError,
)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


def runtime(max_requests: int = 2) -> ModelRuntime:
    return ModelRuntime({"deterministic": DeterministicModelProvider()})


def test_runtime_validates_structured_output() -> None:
    class JsonProvider(ModelProvider):
        name = "json"

        def complete(self, request: ModelRequest, policy: ModelPolicy) -> ModelResponse:
            return ModelResponse('{"answer":"ok"}', input_tokens=2, output_tokens=2)

    result = ModelRuntime({"json": JsonProvider()}).structured(
        ModelRequest(prompt="return JSON"),
        ModelPolicy(provider="json", model="test"),
        Output,
    )
    assert result.answer == "ok"


def test_runtime_rejects_invalid_structured_output() -> None:
    class BadProvider(ModelProvider):
        name = "bad"

        def complete(self, request: ModelRequest, policy: ModelPolicy) -> ModelResponse:
            return ModelResponse('{"unexpected":true}', input_tokens=2, output_tokens=2)

    with pytest.raises(StructuredOutputError):
        ModelRuntime({"bad": BadProvider()}).structured(
            ModelRequest(prompt="return JSON"),
            ModelPolicy(provider="bad", model="test"),
            Output,
        )


def test_runtime_enforces_hard_request_budget() -> None:
    provider = DeterministicModelProvider()
    runtime = ModelRuntime({"deterministic": provider})
    policy = ModelPolicy(provider="deterministic", model="test", max_requests=1)
    request = ModelRequest(prompt="one")
    runtime.complete(request, policy)
    with pytest.raises(BudgetExceeded, match="request budget exhausted"):
        runtime.complete(request, policy)


def test_runtime_rejects_input_that_exceeds_policy() -> None:
    runtime = ModelRuntime({"deterministic": DeterministicModelProvider()})
    policy = ModelPolicy(provider="deterministic", model="test", max_input_tokens=1)
    with pytest.raises(BudgetExceeded, match="exceeds model policy limit"):
        runtime.complete(ModelRequest(prompt="this is too long"), policy)


def test_model_backed_agent_emits_typed_artifact() -> None:
    class AgentProvider(ModelProvider):
        name = "agent-test"

        def complete(self, request: ModelRequest, policy: ModelPolicy) -> ModelResponse:
            return ModelResponse(
                '{"content":{"finding":"validated"},"notes":["bounded"]}',
                input_tokens=10,
                output_tokens=8,
            )

    runtime = ModelRuntime({"agent-test": AgentProvider()})
    policy = ModelPolicy(provider="agent-test", model="test")
    state = WorkflowState(product_goal="research")
    result = ModelBackedAgent(AgentRole.RESEARCHER, runtime, policy).run(state, "evaluate evidence")
    assert result.artifacts[0].content == {"finding": "validated"}
    assert result.artifacts[0].producer == AgentRole.RESEARCHER
    assert result.notes == ("bounded",)
