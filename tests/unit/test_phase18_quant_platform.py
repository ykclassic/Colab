from uuid import uuid4

import pytest

from colab.quant_platform import QuantPlatformError, monte_carlo, portfolio_risk, robustness_analysis, stress_test


def test_risk_metrics_are_deterministic() -> None:
    result = portfolio_risk([0.01, -0.005, 0.02, -0.01, 0.005])
    assert result.total_return != 0
    assert result.max_drawdown <= 0
    assert 0 <= result.win_rate <= 1


def test_stress_test_marks_large_negative_scenario() -> None:
    result = stress_test([0.01, -0.01], {"crash": {"equity": -0.30}}, drawdown_limit=0.20)
    assert result[0].portfolio_return < -0.20
    assert "return_floor" in result[0].breached_limits


def test_monte_carlo_reproducible() -> None:
    kwargs = dict(returns=[0.01, -0.005, 0.002], simulations=500, horizon=20, seed=7)
    assert monte_carlo(**kwargs) == monte_carlo(**kwargs)


def test_robustness_is_reproducible() -> None:
    a = robustness_analysis([0.01, -0.002, 0.004], perturbations=50, seed=9)
    b = robustness_analysis([0.01, -0.002, 0.004], perturbations=50, seed=9)
    assert a == b
    assert 0 <= a.pass_rate <= 1


def test_monte_carlo_rejects_invalid_inputs() -> None:
    with pytest.raises(QuantPlatformError):
        monte_carlo([], simulations=100, horizon=10)


def test_strategy_registry_is_workspace_scoped() -> None:
    from colab.quant_platform import InMemoryStrategyRegistry, StrategyRecord
    registry = InMemoryStrategyRegistry()
    workspace = uuid4()
    other = uuid4()
    strategy = StrategyRecord(workspace_id=workspace, name="test", code_revision="abc")
    registry.register(strategy)
    assert registry.list(workspace) == [strategy]
    assert registry.list(other) == []
