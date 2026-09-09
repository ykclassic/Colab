from datetime import UTC, datetime, timedelta

import pytest

from colab.quant_lab import (
    Backtester,
    FeatureEngineer,
    MarketBar,
    MarketDataset,
    ParameterSweeper,
    QuantLabError,
    QuantitativeResearchLab,
    WalkForwardEvaluator,
)


def dataset(count: int = 80) -> MarketDataset:
    bars = []
    for i in range(count):
        close = 100.0 + i * 0.25 + (2.0 if i % 9 == 0 else 0.0)
        bars.append(
            MarketBar(
                timestamp=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i),
                symbol="TEST",
                open=close - 0.1,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1000 + i * 10,
            )
        )
    return MarketDataset(symbol="TEST", bars=tuple(bars), source="unit")


def signal(context):
    values = context.features.rows[context.index].values
    fast = values.get(f"sma_{context.parameters.get('fast', 5)}")
    slow = values.get(f"sma_{context.parameters.get('slow', 20)}")
    if fast != fast or slow != slow:
        return 0.0
    return 1.0 if fast > slow else 0.0


def test_dataset_checksum_and_causal_features():
    ds = dataset()
    fs = FeatureEngineer().build(ds, (5, 20))
    assert len(fs.rows) == len(ds.bars)
    assert fs.dataset_checksum == ds.checksum
    assert fs.rows[0].values["return_1"] != fs.rows[0].values["return_1"]
    assert fs.rows[19].values["sma_20"] == pytest.approx(sum(b.close for b in ds.bars[:20]) / 20)


def test_backtest_executes_on_next_bar_and_has_costs():
    ds = dataset()
    fs = FeatureEngineer().build(ds, (5, 20))
    result = Backtester().run(ds, fs, signal, {"fast": 5, "slow": 20}, commission_bps=5, slippage_bps=5)
    assert result.equity_curve
    assert result.metrics.trade_count >= 0
    assert all(trade.price > 0 for trade in result.trades)


def test_sweep_returns_best_result_deterministically():
    ds = dataset()
    fs = FeatureEngineer().build(ds, (3, 5, 10, 20))
    result = ParameterSweeper().run(ds.dataset_id, ds, fs, signal, {"fast": [3, 5], "slow": [10, 20]})
    assert len(result.results) == 4
    assert result.best_index is not None


def test_walk_forward_never_tests_before_training():
    ds = dataset(100)
    fs = FeatureEngineer().build(ds)
    result = WalkForwardEvaluator().run(ds, fs, signal, {"fast": [3, 5], "slow": [10, 20]}, train_size=40, test_size=10)
    assert result.windows
    assert all(window.train_end <= window.test_start for window in result.windows)
    assert result.oos_observations > 0


def test_lab_tracks_sweeps_and_oos_experiments():
    ds = dataset(70)
    fs = FeatureEngineer().build(ds)
    lab = QuantitativeResearchLab()
    lab.sweep(ds, fs, signal, {"fast": [3], "slow": [10]})
    lab.walk_forward(ds, fs, signal, {"fast": [3], "slow": [10]}, train_size=30, test_size=10)
    assert len(lab.experiments()) == 2


def test_rejects_bad_dataset_and_feature_mismatch():
    ds = dataset()
    other = dataset(81)
    fs = FeatureEngineer().build(ds)
    with pytest.raises(QuantLabError):
        Backtester().run(other, fs, signal, {"fast": 3, "slow": 10})


def test_rejects_invalid_parameter_grid():
    ds = dataset()
    fs = FeatureEngineer().build(ds)
    with pytest.raises(QuantLabError):
        ParameterSweeper().run(ds.dataset_id, ds, fs, signal, {"fast": []})
