import pytest

from colab.contracts import Decision, RiskAssessment, Stage, WorkflowState
from colab.langgraph_workflow import (
    build_workflow_graph,
    recover_workflow,
    resume_with_human_decision,
)
from colab.quant_validation import run_backtest, walk_forward_validate
from colab.sandbox import QuantSandbox, SandboxError


def test_langgraph_reaches_human_gate_and_recovers() -> None:
    state = WorkflowState(product_goal="test", current_stage=Stage.RISK)
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    graph = build_workflow_graph()
    config = {"configurable": {"thread_id": "phase2-test"}}

    result = graph.invoke({"workflow": state.model_dump(mode="json")}, config)
    assert "__interrupt__" in result
    assert result["workflow"]["current_stage"] == Stage.HUMAN_REVIEW.value

    recovered = recover_workflow(graph, "phase2-test")
    assert recovered.current_stage == Stage.HUMAN_REVIEW
    assert recovered.workflow_id == state.workflow_id

    resumed = resume_with_human_decision(graph, "phase2-test", Decision.APPROVE)
    assert resumed["workflow"]["current_stage"] == Stage.COMPLETE.value
    assert resumed["workflow"]["approvals"][-1]["decision"] == Decision.APPROVE.value


def test_langgraph_human_rejection_is_terminal() -> None:
    state = WorkflowState(product_goal="test", current_stage=Stage.RISK)
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    graph = build_workflow_graph()
    graph.invoke(
        {"workflow": state.model_dump(mode="json")},
        {"configurable": {"thread_id": "phase2-reject"}},
    )
    resumed = resume_with_human_decision(graph, "phase2-reject", Decision.REJECT)
    assert resumed["workflow"]["current_stage"] == Stage.REJECTED.value


def test_langgraph_rejects_invalid_human_decision() -> None:
    with pytest.raises(ValueError, match="human decision"):
        resume_with_human_decision(build_workflow_graph(), "thread", Decision.REVISE)


def test_backtest_is_reproducible_and_has_no_lookahead_execution() -> None:
    prices = [100.0, 102.0, 101.0, 104.0]
    result = run_backtest(prices, [0, 1, 0, 1], transaction_cost_bps=10)
    repeat = run_backtest(prices, [0, 1, 0, 1], transaction_cost_bps=10)
    assert result.reproducibility_hash == repeat.reproducibility_hash
    assert result.trades == 3
    assert result.equity_curve[1] == result.initial_capital


def test_walk_forward_produces_chronological_oos_windows() -> None:
    prices = [float(100 + index) for index in range(16)]

    def always_long(history: list[float] | tuple[float, ...]) -> list[int]:
        return [1] * len(history)

    windows = walk_forward_validate(prices, always_long, train_size=5, test_size=3)
    assert len(windows) == 2
    assert windows[0].train_end == windows[0].test_start
    assert windows[0].test_end == windows[1].train_start


def test_sandbox_runs_bounded_trusted_job() -> None:
    sandbox = QuantSandbox(timeout_seconds=2)
    result = sandbox.run("print('ok')")
    assert result.return_code == 0
    assert result.stdout.strip() == "ok"


def test_sandbox_enforces_timeout() -> None:
    sandbox = QuantSandbox(timeout_seconds=0.1)
    with pytest.raises(SandboxError, match="timeout"):
        sandbox.run("import time; time.sleep(1)")
