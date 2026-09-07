"""Deterministic quantitative validation primitives with reproducible results."""

from __future__ import annotations

import hashlib
import json
import math

from collections.abc import Callable, Sequence
from dataclasses import dataclass


SignalFn = Callable[[Sequence[float]], Sequence[int]]


@dataclass(frozen=True)
class BacktestResult:
    """Immutable backtest result suitable for persistence and audit."""

    initial_capital: float
    final_equity: float
    total_return: float
    max_drawdown: float
    trades: int
    equity_curve: tuple[float, ...]
    reproducibility_hash: str


@dataclass(frozen=True)
class WalkForwardWindow:
    """One chronological train/test window."""

    train_start: int
    train_end: int
    test_start: int
    test_end: int
    result: BacktestResult


def _validate_prices(prices: Sequence[float]) -> None:
    if len(prices) < 2:
        raise ValueError("at least two prices are required")
    if any(not math.isfinite(price) or price <= 0 for price in prices):
        raise ValueError("prices must be finite and positive")


def run_backtest(
    prices: Sequence[float],
    signals: Sequence[int],
    *,
    initial_capital: float = 100_000.0,
    transaction_cost_bps: float = 0.0,
) -> BacktestResult:
    """Run a long/flat, close-to-close backtest without look-ahead execution."""
    _validate_prices(prices)
    if len(signals) != len(prices):
        raise ValueError("signals and prices must have equal length")
    if initial_capital <= 0 or not math.isfinite(initial_capital):
        raise ValueError("initial_capital must be finite and positive")
    if transaction_cost_bps < 0 or not math.isfinite(transaction_cost_bps):
        raise ValueError("transaction_cost_bps must be finite and non-negative")
    if any(signal not in {-1, 0, 1} for signal in signals):
        raise ValueError("signals must be -1, 0, or 1")

    equity = initial_capital
    curve = [equity]
    trades = 0
    previous_signal = 0
    cost = transaction_cost_bps / 10_000.0
    for index in range(1, len(prices)):
        signal = signals[index - 1]
        if signal != previous_signal:
            trades += 1
            equity *= 1.0 - cost
            previous_signal = signal
        period_return = (prices[index] / prices[index - 1]) - 1.0
        equity *= 1.0 + signal * period_return
        curve.append(equity)

    peak = curve[0]
    max_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak)
    total_return = equity / initial_capital - 1.0
    payload = json.dumps(
        {
            "initial_capital": initial_capital,
            "final_equity": equity,
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "trades": trades,
            "equity_curve": curve,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return BacktestResult(
        initial_capital=initial_capital,
        final_equity=equity,
        total_return=total_return,
        max_drawdown=max_drawdown,
        trades=trades,
        equity_curve=tuple(curve),
        reproducibility_hash=digest,
    )


def walk_forward_validate(
    prices: Sequence[float],
    signal_fn: SignalFn,
    *,
    train_size: int,
    test_size: int,
    step: int | None = None,
    initial_capital: float = 100_000.0,
    transaction_cost_bps: float = 0.0,
) -> tuple[WalkForwardWindow, ...]:
    """Evaluate chronological out-of-sample windows without shuffling or leakage."""
    _validate_prices(prices)
    if train_size < 1 or test_size < 1:
        raise ValueError("train_size and test_size must be positive")
    step = test_size if step is None else step
    if step < 1:
        raise ValueError("step must be positive")

    windows: list[WalkForwardWindow] = []
    start = 0
    while start + train_size + test_size <= len(prices):
        train_end = start + train_size
        test_end = train_end + test_size
        train_prices = prices[start:train_end]
        test_prices = prices[train_end:test_end]
        # Strategy calibration is deliberately separated from evaluation. The
        # current deterministic contract accepts the training history as context.
        train_signals = list(signal_fn(train_prices))
        if len(train_signals) != len(train_prices):
            raise ValueError("signal_fn must return one signal per training price")
        test_signals = list(signal_fn(prices[start:test_end]))[-test_size:]
        result = run_backtest(
            test_prices,
            test_signals,
            initial_capital=initial_capital,
            transaction_cost_bps=transaction_cost_bps,
        )
        windows.append(WalkForwardWindow(start, train_end, train_end, test_end, result))
        start += step
    if not windows:
        raise ValueError("insufficient data for one train/test window")
    return tuple(windows)
