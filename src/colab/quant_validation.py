"""Deterministic quantitative validation primitives with reproducible results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import hashlib
import json
import math


SignalFn = Callable[[Sequence[float]], Sequence[int]]


@dataclass(frozen=True)
class BacktestResult:
    """Immutable backtest result suitable for persistence and audit."""

    initial_capital: float
    final_equity: float
    total_return: float
    max_drawdown: float
    trade_count: int
    reproducibility_hash: str


@dataclass(frozen=True)
class WalkForwardResult:
    """Chronological walk-forward validation result."""

    train_windows: int
    test_windows: int
    out_of_sample_returns: tuple[float, ...]
    aggregate_out_of_sample_return: float


def _validate_prices(prices: Sequence[float]) -> None:
    if len(prices) < 2:
        raise ValueError("At least two prices are required")
    if any(not math.isfinite(price) or price <= 0 for price in prices):
        raise ValueError("Prices must be finite and strictly positive")


def _validate_signals(signals: Sequence[int], expected_length: int) -> None:
    if len(signals) != expected_length:
        raise ValueError("Signal length must match price length")
    if any(signal not in (-1, 0, 1) for signal in signals):
        raise ValueError("Signals must be -1, 0, or 1")


def backtest(
    prices: Sequence[float],
    signal_fn: SignalFn,
    *,
    initial_capital: float = 100_000.0,
    transaction_cost_bps: float = 0.0,
) -> BacktestResult:
    """Run a deterministic long/flat backtest with transaction costs."""
    _validate_prices(prices)
    if not math.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("Initial capital must be finite and positive")
    if not math.isfinite(transaction_cost_bps) or transaction_cost_bps < 0:
        raise ValueError("Transaction cost must be finite and non-negative")

    signals = tuple(signal_fn(prices))
    _validate_signals(signals, len(prices))

    equity = initial_capital
    peak = equity
    max_drawdown = 0.0
    position = 0
    trade_count = 0
    cost_rate = transaction_cost_bps / 10_000.0

    for index in range(1, len(prices)):
        target_position = 1 if signals[index - 1] > 0 else 0
        if target_position != position:
            equity *= 1.0 - cost_rate
            trade_count += 1
            position = target_position

        period_return = (prices[index] / prices[index - 1]) - 1.0
        equity *= 1.0 + (period_return * position)
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak) - 1.0)

    payload = {
        "prices": list(prices),
        "signals": list(signals),
        "initial_capital": initial_capital,
        "transaction_cost_bps": transaction_cost_bps,
    }
    reproducibility_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return BacktestResult(
        initial_capital=initial_capital,
        final_equity=equity,
        total_return=(equity / initial_capital) - 1.0,
        max_drawdown=max_drawdown,
        trade_count=trade_count,
        reproducibility_hash=reproducibility_hash,
    )


def walk_forward_validate(
    prices: Sequence[float],
    signal_fn: SignalFn,
    *,
    train_size: int,
    test_size: int,
) -> WalkForwardResult:
    """Evaluate strictly chronological out-of-sample windows."""
    _validate_prices(prices)
    if train_size <= 0 or test_size <= 0:
        raise ValueError("Train and test sizes must be positive")
    if train_size + test_size > len(prices):
        raise ValueError("Train and test windows exceed available data")

    out_of_sample_returns: list[float] = []
    start = 0
    train_windows = 0

    while start + train_size + test_size <= len(prices):
        train = prices[start : start + train_size]
        test = prices[start + train_size : start + train_size + test_size]
        signal_fn(train)
        test_signals = tuple(signal_fn(test))
        _validate_signals(test_signals, len(test))
        result = backtest(test, lambda _prices, signals=test_signals: signals)
        out_of_sample_returns.append(result.total_return)
        train_windows += 1
        start += test_size

    return WalkForwardResult(
        train_windows=train_windows,
        test_windows=len(out_of_sample_returns),
        out_of_sample_returns=tuple(out_of_sample_returns),
        aggregate_out_of_sample_return=math.prod(
            1.0 + result for result in out_of_sample_returns
        )
        - 1.0,
    )
