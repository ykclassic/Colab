"""Deterministic quantitative validation primitives and Phase 21E scientific gates."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from .quant_lab import FeatureSet, MarketDataset

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


def run_backtest(prices: Sequence[float], signals: Sequence[int], *, initial_capital: float = 100_000.0, transaction_cost_bps: float = 0.0) -> BacktestResult:
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
    cost = transaction_cost_bps / 10_000.0
    for index in range(1, len(prices)):
        held_signal = signals[index - 1]
        signal = signals[index]
        period_return = (prices[index] / prices[index - 1]) - 1.0
        equity *= 1.0 + held_signal * period_return
        curve.append(equity)
        if signal != held_signal:
            trades += 1
            equity *= 1.0 - cost
    peak = curve[0]
    max_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak)
    total_return = equity / initial_capital - 1.0
    payload = json.dumps({"initial_capital": initial_capital, "final_equity": equity, "total_return": total_return, "max_drawdown": max_drawdown, "trades": trades, "equity_curve": curve}, sort_keys=True, separators=(",", ":")).encode()
    return BacktestResult(initial_capital, equity, total_return, max_drawdown, trades, tuple(curve), hashlib.sha256(payload).hexdigest())


def walk_forward_validate(prices: Sequence[float], signal_fn: SignalFn, *, train_size: int, test_size: int, step: int | None = None, initial_capital: float = 100_000.0, transaction_cost_bps: float = 0.0) -> tuple[WalkForwardWindow, ...]:
    """Evaluate chronological out-of-sample windows without shuffling or leakage."""
    _validate_prices(prices)
    if train_size < 1 or test_size < 1:
        raise ValueError("train_size and test_size must be positive")
    step = train_size + test_size if step is None else step
    if step < 1:
        raise ValueError("step must be positive")
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + train_size + test_size <= len(prices):
        train_end = start + train_size
        test_end = train_end + test_size
        train_prices = prices[start:train_end]
        test_prices = prices[train_end:test_end]
        train_signals = list(signal_fn(train_prices))
        if len(train_signals) != len(train_prices):
            raise ValueError("signal_fn must return one signal per training price")
        test_signals = list(signal_fn(prices[start:test_end]))[-test_size:]
        result = run_backtest(test_prices, test_signals, initial_capital=initial_capital, transaction_cost_bps=transaction_cost_bps)
        windows.append(WalkForwardWindow(start, train_end, train_end, test_end, result))
        start += step
    if not windows:
        raise ValueError("insufficient data for one train/test window")
    return tuple(windows)


@dataclass(frozen=True)
class ValidationFinding:
    check: str
    passed: bool
    severity: str
    message: str


@dataclass(frozen=True)
class ScientificValidation:
    passed: bool
    findings: tuple[ValidationFinding, ...]
    validation_hash: str

    @property
    def failures(self) -> tuple[ValidationFinding, ...]:
        return tuple(x for x in self.findings if not x.passed)


class QuantScientificValidator:
    """Reject common backtest pathologies before results can be treated as research evidence."""

    def validate(self, dataset: MarketDataset, features: FeatureSet, *, train_end: datetime | None = None,
                 test_start: datetime | None = None, expected_interval: timedelta | None = None,
                 max_stale_intervals: int = 1, metadata: dict[str, Any] | None = None,
                 parameter_selection: str = "train", execution_timing: str = "next_bar_open",
                 commission_bps: float = 1.0, slippage_bps: float = 1.0) -> ScientificValidation:
        meta = metadata or {}
        findings: list[ValidationFinding] = []
        timestamps = [bar.timestamp for bar in dataset.bars]
        findings.append(self._check("timestamp_data_leakage", all(ts.tzinfo is not None and ts.utcoffset() is not None for ts in timestamps), "All market timestamps must be timezone-aware."))
        findings.append(self._check("duplicate_data", len(timestamps) == len(set(timestamps)), "Duplicate timestamps are not allowed."))
        findings.append(self._check("chronology", all(a < b for a, b in pairwise(timestamps)), "Market bars must be strictly chronological."))
        if expected_interval is not None and len(timestamps) > 1:
            gaps = [b - a for a, b in pairwise(timestamps)]
            stale = sum(1 for gap in gaps if gap > expected_interval * (max_stale_intervals + 1))
            findings.append(self._check("missing_stale_data", stale == 0, "Detected gaps beyond the configured stale-data tolerance."))
        else:
            findings.append(self._check("missing_stale_data", bool(meta.get("data_quality_checked", False)), "Provide expected interval/data-quality evidence before production research."))
        findings.append(self._check("look_ahead_leakage", execution_timing == "next_bar_open", "Signals must be generated before the next-bar execution."))
        findings.append(self._check("feature_parameter_leakage", features.dataset_checksum == dataset.checksum and features.warmup >= 0, "Features must be derived from the exact dataset and causal windows."))
        findings.append(self._check("train_test_separation", (train_end is None and test_start is None) or (train_end is not None and test_start is not None and train_end < test_start), "Training selection must precede OOS testing."))
        findings.append(self._check("selection_bias", parameter_selection == "train", "Parameters must be selected using training data only."))
        findings.append(self._check("survivorship_bias", bool(meta.get("universe_policy")), "Record a point-in-time universe policy including delisted constituents."))
        findings.append(self._check("corporate_actions", bool(meta.get("corporate_actions_policy")), "Record whether prices are adjusted and how splits/dividends are handled."))
        findings.append(self._check("spread_slippage", commission_bps >= 0 and slippage_bps > 0, "Backtests must model non-negative commissions and positive slippage."))
        findings.append(self._check("realistic_fills", execution_timing == "next_bar_open" and bool(meta.get("fill_policy")), "Execution must use an explicit causal fill policy rather than current-bar hindsight."))
        findings.append(self._check("stale_data_policy", bool(meta.get("stale_data_policy")), "Record how stale observations are detected and handled."))
        findings.append(self._check("feature_timestamp_alignment", all(row.timestamp == bar.timestamp for row, bar in zip(features.rows, dataset.bars, strict=True)), "Feature timestamps must exactly align to source bars."))
        canonical = "|".join(f"{x.check}:{x.passed}:{x.severity}:{x.message}" for x in findings)
        return ScientificValidation(passed=all(x.passed for x in findings), findings=tuple(findings), validation_hash=sha256(canonical.encode()).hexdigest())

    @staticmethod
    def _check(check: str, passed: bool, message: str) -> ValidationFinding:
        return ValidationFinding(check=check, passed=passed, severity="error" if not passed else "info", message=message)
