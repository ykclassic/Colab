from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from colab.quant_lab import FeatureEngineer, MarketBar, MarketDataset
from colab.quant_platform import StrategyRecord
from colab.quant_validation import QuantScientificValidator
from colab.quant_vertical_slice import QuantVerticalSlice, QuantVerticalSliceError


def dataset(size: int = 90) -> MarketDataset:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = tuple(
        MarketBar(
            timestamp=start + timedelta(days=i), symbol="TEST", open=100 + i * 0.1,
            high=101 + i * 0.1, low=99 + i * 0.1, close=100 + i * 0.15,
            volume=1000 + i,
        ) for i in range(size)
    )
    return MarketDataset(symbol="TEST", bars=bars, source="synthetic")


def valid_metadata() -> dict[str, object]:
    return {
        "data_quality_checked": True,
        "universe_policy": "point_in_time_including_delisted",
        "corporate_actions_policy": "adjusted_prices_with_split_dividend_metadata",
        "fill_policy": "next_bar_open_with_slippage",
        "stale_data_policy": "reject_gap_over_one_interval",
    }


def signal(context: object) -> float:
    values = context.features.rows[context.index].values
    fast = values.get(f"sma_{context.parameters['fast']}")
    slow = values.get(f"sma_{context.parameters['slow']}")
    if fast != fast or slow != slow:
        return 0.0
    return 1.0 if fast > slow else 0.0


def test_scientific_validator_covers_all_required_bias_and_execution_controls() -> None:
    data = dataset()
    features = FeatureEngineer().build(data, (5, 20))
    result = QuantScientificValidator().validate(data, features, metadata=valid_metadata(), execution_timing="next_bar_open", parameter_selection="train", commission_bps=1, slippage_bps=2)
    assert result.passed
    assert {x.check for x in result.findings} >= {
        "look_ahead_leakage", "survivorship_bias", "selection_bias", "timestamp_data_leakage",
        "feature_parameter_leakage", "corporate_actions", "missing_stale_data", "duplicate_data",
        "spread_slippage", "realistic_fills", "stale_data_policy", "feature_timestamp_alignment",
    }


def test_validator_rejects_hindsight_execution_and_missing_survivorship_policy() -> None:
    data = dataset()
    features = FeatureEngineer().build(data, (5, 20))
    result = QuantScientificValidator().validate(data, features, metadata={}, execution_timing="same_bar_close", parameter_selection="test", commission_bps=0, slippage_bps=0)
    assert not result.passed
    failures = {x.check for x in result.failures}
    assert {"look_ahead_leakage", "survivorship_bias", "selection_bias", "spread_slippage", "realistic_fills"} <= failures


def test_quant_vertical_slice_runs_through_oos_risk_stress_monte_carlo_robustness() -> None:
    data = dataset()
    strategy = StrategyRecord(workspace_id=uuid4(), name="Causal SMA", code_revision="test", parameters={"fast": 5, "slow": 20}, dataset_ids=[data.dataset_id])
    result = QuantVerticalSlice().run(
        dataset=data, strategy=strategy, parameter_grid={"fast": [5, 10], "slow": [20, 30]}, signal=signal,
        train_size=50, test_size=10, seed=7, validation_metadata=valid_metadata(), commission_bps=1, slippage_bps=2,
    )
    assert result["experiment"].workspace_id == strategy.workspace_id
    assert result["backtest"].metrics.trade_count >= 0
    assert result["walk_forward_oos"].oos_observations > 0
    assert result["risk"].sharpe == result["risk"].sharpe
    assert result["stress"]
    assert result["monte_carlo"].seed == 7
    assert result["robustness"].perturbations == 100
    assert len(result["experiment_hash"]) == 64
    assert len(result["scientific_validation"].validation_hash) == 64
    assert len(result["reproducibility_hash"]) == 64


def test_quant_vertical_slice_rejects_dataset_not_bound_to_strategy() -> None:
    data = dataset()
    strategy = StrategyRecord(workspace_id=uuid4(), name="Bound", code_revision="test", dataset_ids=[uuid4()])
    with pytest.raises(QuantVerticalSliceError, match="not bound"):
        QuantVerticalSlice().run(
            dataset=data, strategy=strategy, parameter_grid={"fast": [5], "slow": [20]}, signal=signal,
            train_size=50, test_size=10, validation_metadata=valid_metadata(), slippage_bps=1,
        )
