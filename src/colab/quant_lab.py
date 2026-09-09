"""Deterministic quantitative research and strategy lab.

The lab is intentionally dependency-light and research-only. It provides
canonical OHLCV datasets, leakage-aware feature engineering, event-driven
backtesting, parameter sweeps, walk-forward/OOS evaluation, and immutable
experiment tracking. It never places trades or mutates workflow state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from itertools import product
from math import sqrt
from statistics import mean, pstdev
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class QuantLabError(ValueError):
    """Raised when a research experiment violates a lab invariant."""


class MarketBar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    symbol: str = Field(min_length=1, max_length=32)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    def model_post_init(self, __context: Any) -> None:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC bounds are invalid")


class MarketDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID = Field(default_factory=uuid4)
    symbol: str = Field(min_length=1, max_length=32)
    bars: tuple[MarketBar, ...] = Field(min_length=2)
    source: str = Field(default="research_upload", min_length=1, max_length=200)
    checksum: str = ""

    def model_post_init(self, __context: Any) -> None:
        previous: datetime | None = None
        for bar in self.bars:
            if bar.symbol != self.symbol:
                raise QuantLabError("all bars must use the dataset symbol")
            if previous is not None and bar.timestamp <= previous:
                raise QuantLabError("bars must be strictly chronological")
            previous = bar.timestamp
        if not self.checksum:
            canonical = "|".join(
                f"{b.timestamp.isoformat()}:{b.open:.12g}:{b.high:.12g}:{b.low:.12g}:{b.close:.12g}:{b.volume:.12g}"
                for b in self.bars
            )
            object.__setattr__(self, "checksum", sha256(canonical.encode()).hexdigest())


class FeatureRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    symbol: str
    values: dict[str, float]


class FeatureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    dataset_checksum: str
    rows: tuple[FeatureRow, ...]
    feature_names: tuple[str, ...]
    warmup: int = Field(ge=0)


class Trade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    side: str
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    pnl: float
    commission: float = Field(ge=0)


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    trade_count: int = Field(ge=0)
    exposure: float = Field(ge=0, le=1)


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_capital: float = Field(gt=0)
    equity_curve: tuple[float, ...]
    trades: tuple[Trade, ...]
    metrics: BacktestMetrics
    parameters: dict[str, Any]


class SweepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: UUID
    results: tuple[BacktestResult, ...]
    objective: str
    best_index: int | None


class WalkForwardWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    train_start: int = Field(ge=0)
    train_end: int = Field(ge=1)
    test_start: int = Field(ge=0)
    test_end: int = Field(ge=1)
    test_metrics: BacktestMetrics
    parameters: dict[str, Any]


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    windows: tuple[WalkForwardWindow, ...]
    stitched_metrics: BacktestMetrics
    oos_observations: int = Field(ge=0)


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    experiment_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dataset_checksum: str
    feature_set: str
    strategy: str
    parameters: dict[str, Any]
    result_type: str
    result: dict[str, Any]
    tags: tuple[str, ...] = ()


class ExperimentTracker:
    """Append-only in-memory tracker suitable for tests and local research."""

    def __init__(self) -> None:
        self._records: list[ExperimentRecord] = []

    def record(self, record: ExperimentRecord) -> ExperimentRecord:
        if any(existing.experiment_id == record.experiment_id for existing in self._records):
            raise QuantLabError("experiment ID already exists")
        self._records.append(record)
        return record

    def list(self) -> tuple[ExperimentRecord, ...]:
        return tuple(self._records)

    def get(self, experiment_id: UUID) -> ExperimentRecord:
        for record in self._records:
            if record.experiment_id == experiment_id:
                return record
        raise QuantLabError("experiment not found")


@dataclass(frozen=True)
class StrategyContext:
    dataset: MarketDataset
    features: FeatureSet
    index: int
    parameters: Mapping[str, Any]


SignalFunction = Callable[[StrategyContext], float]


class FeatureEngineer:
    """Causal technical features. Every feature at t uses data through t only."""

    def build(self, dataset: MarketDataset, windows: Sequence[int] = (5, 20)) -> FeatureSet:
        normalized = tuple(sorted(set(windows)))
        if not normalized or normalized[0] < 2:
            raise QuantLabError("feature windows must contain values >= 2")
        closes = [bar.close for bar in dataset.bars]
        rows: list[FeatureRow] = []
        names = ["return_1", "volatility_5", "volume_zscore_20"]
        names.extend(f"sma_{window}" for window in normalized)
        for index, bar in enumerate(dataset.bars):
            values: dict[str, float] = {"return_1": float("nan")}
            if index:
                values["return_1"] = closes[index] / closes[index - 1] - 1.0
            vol_window = closes[max(0, index - 4) : index + 1]
            returns = [vol_window[i] / vol_window[i - 1] - 1 for i in range(1, len(vol_window))]
            values["volatility_5"] = pstdev(returns) if len(returns) > 1 else 0.0
            volume_window = [b.volume for b in dataset.bars[max(0, index - 19) : index + 1]]
            if len(volume_window) > 1:
                mu = mean(volume_window)
                sigma = pstdev(volume_window)
                values["volume_zscore_20"] = (bar.volume - mu) / sigma if sigma else 0.0
            else:
                values["volume_zscore_20"] = 0.0
            for window in normalized:
                if index + 1 >= window:
                    values[f"sma_{window}"] = mean(closes[index - window + 1 : index + 1])
                else:
                    values[f"sma_{window}"] = float("nan")
            rows.append(FeatureRow(timestamp=bar.timestamp, symbol=bar.symbol, values=values))
        return FeatureSet(
            name="causal_market_features",
            dataset_checksum=dataset.checksum,
            rows=tuple(rows),
            feature_names=tuple(names),
            warmup=max(normalized),
        )


@dataclass
class _Position:
    quantity: float = 0.0
    entry_price: float = 0.0


class Backtester:
    """Long/flat, next-bar execution backtester with costs and no look-ahead."""

    def run(
        self,
        dataset: MarketDataset,
        features: FeatureSet,
        signal: SignalFunction,
        parameters: Mapping[str, Any],
        *,
        initial_capital: float = 100_000.0,
        commission_bps: float = 1.0,
        slippage_bps: float = 1.0,
    ) -> BacktestResult:
        if features.dataset_checksum != dataset.checksum:
            raise QuantLabError("feature set belongs to a different dataset")
        if initial_capital <= 0 or commission_bps < 0 or slippage_bps < 0:
            raise QuantLabError("capital and trading costs must be valid")
        if len(features.rows) != len(dataset.bars):
            raise QuantLabError("feature and market row counts must match")
        cash = initial_capital
        position = _Position()
        equity: list[float] = []
        trades: list[Trade] = []
        exposure_bars = 0
        for index in range(len(dataset.bars) - 1):
            context = StrategyContext(dataset=dataset, features=features, index=index, parameters=parameters)
            raw_signal = signal(context)
            if raw_signal not in (-1.0, 0.0, 1.0):
                raise QuantLabError("strategy signal must be -1, 0, or 1")
            execution_bar = dataset.bars[index + 1]
            execution_price = execution_bar.open
            if raw_signal > 0 and position.quantity == 0:
                fill = execution_price * (1 + slippage_bps / 10_000)
                qty = cash / fill
                fee = qty * fill * commission_bps / 10_000
                cash -= qty * fill + fee
                position = _Position(qty, fill)
                trades.append(Trade(timestamp=execution_bar.timestamp, side="buy", price=fill, quantity=qty, pnl=0.0, commission=fee))
            elif raw_signal <= 0 and position.quantity > 0:
                fill = execution_price * (1 - slippage_bps / 10_000)
                gross = (fill - position.entry_price) * position.quantity
                fee = fill * position.quantity * commission_bps / 10_000
                cash += fill * position.quantity - fee
                trades.append(Trade(timestamp=execution_bar.timestamp, side="sell", price=fill, quantity=position.quantity, pnl=gross - fee, commission=fee))
                position = _Position()
            if position.quantity:
                exposure_bars += 1
            equity.append(cash + position.quantity * dataset.bars[index + 1].close)
        if position.quantity:
            bar = dataset.bars[-1]
            fill = bar.close * (1 - slippage_bps / 10_000)
            gross = (fill - position.entry_price) * position.quantity
            fee = fill * position.quantity * commission_bps / 10_000
            cash += fill * position.quantity - fee
            trades.append(Trade(timestamp=bar.timestamp, side="sell", price=fill, quantity=position.quantity, pnl=gross - fee, commission=fee))
            equity.append(cash)
        metrics = self._metrics(initial_capital, equity, trades, exposure_bars, max(1, len(dataset.bars) - 1))
        return BacktestResult(initial_capital=initial_capital, equity_curve=tuple(equity), trades=tuple(trades), metrics=metrics, parameters=dict(parameters))

    @staticmethod
    def _metrics(initial: float, equity: list[float], trades: list[Trade], exposure: int, bars: int) -> BacktestMetrics:
        if not equity:
            return BacktestMetrics(total_return=0, annualized_return=0, annualized_volatility=0, sharpe=0, max_drawdown=0, win_rate=0, profit_factor=0, trade_count=0, exposure=0)
        total = equity[-1] / initial - 1
        periods = max(len(equity), 1)
        annualized = (equity[-1] / initial) ** (252 / periods) - 1 if equity[-1] > 0 else -1
        returns = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]
        volatility = pstdev(returns) * sqrt(252) if len(returns) > 1 else 0.0
        sharpe = (mean(returns) / pstdev(returns) * sqrt(252)) if len(returns) > 1 and pstdev(returns) else 0.0
        peak = equity[0]
        drawdown = 0.0
        for value in equity:
            peak = max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
        closed = [trade.pnl for trade in trades if trade.side == "sell"]
        wins = [pnl for pnl in closed if pnl > 0]
        losses = [-pnl for pnl in closed if pnl < 0]
        profit_factor = sum(wins) / sum(losses) if losses else (float("inf") if wins else 0.0)
        return BacktestMetrics(total_return=total, annualized_return=annualized, annualized_volatility=volatility, sharpe=sharpe, max_drawdown=drawdown, win_rate=len(wins) / len(closed) if closed else 0.0, profit_factor=profit_factor, trade_count=len(closed), exposure=exposure / bars)


class ParameterSweeper:
    """Deterministic Cartesian parameter sweep with explicit objective."""

    def run(self, experiment_id: UUID, dataset: MarketDataset, features: FeatureSet, signal: SignalFunction, grid: Mapping[str, Sequence[Any]], *, objective: str = "sharpe") -> SweepResult:
        if not grid or any(not values for values in grid.values()):
            raise QuantLabError("parameter grid cannot be empty")
        names = tuple(sorted(grid))
        results: list[BacktestResult] = []
        for values in product(*(grid[name] for name in names)):
            parameters = dict(zip(names, values))
            results.append(Backtester().run(dataset, features, signal, parameters))
        if not hasattr(results[0].metrics, objective):
            raise QuantLabError(f"unknown objective: {objective}")
        best_index = max(range(len(results)), key=lambda i: getattr(results[i].metrics, objective))
        return SweepResult(experiment_id=experiment_id, results=tuple(results), objective=objective, best_index=best_index)


class WalkForwardEvaluator:
    """Rolling train/test evaluator. Test observations are never used to select parameters."""

    def run(self, dataset: MarketDataset, features: FeatureSet, signal: SignalFunction, parameter_grid: Mapping[str, Sequence[Any]], *, train_size: int, test_size: int, objective: str = "sharpe") -> WalkForwardResult:
        if train_size < 2 or test_size < 1 or train_size + test_size > len(dataset.bars):
            raise QuantLabError("invalid walk-forward window sizes")
        windows: list[WalkForwardWindow] = []
        oos_equity: list[float] = []
        oos_trades: list[Trade] = []
        start = 0
        while start + train_size + test_size <= len(dataset.bars):
            train_ds = MarketDataset(symbol=dataset.symbol, bars=dataset.bars[start : start + train_size], source=dataset.source)
            train_fs = FeatureEngineer().build(train_ds)
            sweep = ParameterSweeper().run(uuid4(), train_ds, train_fs, signal, parameter_grid, objective=objective)
            assert sweep.best_index is not None
            chosen = sweep.results[sweep.best_index].parameters
            test_start = start + train_size
            test_end = test_start + test_size
            test_ds = MarketDataset(symbol=dataset.symbol, bars=dataset.bars[test_start : test_end], source=dataset.source)
            test_fs = FeatureEngineer().build(test_ds)
            result = Backtester().run(test_ds, test_fs, signal, chosen)
            windows.append(WalkForwardWindow(train_start=start, train_end=start + train_size, test_start=test_start, test_end=test_end, test_metrics=result.metrics, parameters=chosen))
            oos_equity.extend(result.equity_curve)
            oos_trades.extend(result.trades)
            start += test_size
        if not windows:
            raise QuantLabError("walk-forward produced no windows")
        stitched = Backtester._metrics(100_000, oos_equity, oos_trades, 0, max(1, len(oos_equity))) if oos_equity else BacktestMetrics(total_return=0, annualized_return=0, annualized_volatility=0, sharpe=0, max_drawdown=0, win_rate=0, profit_factor=0, trade_count=0, exposure=0)
        return WalkForwardResult(windows=tuple(windows), stitched_metrics=stitched, oos_observations=len(oos_equity))


@dataclass(frozen=True)
class QuantitativeResearchLab:
    """Facade composing dataset, features, backtest, sweep, OOS, and tracking."""
    tracker: ExperimentTracker = field(default_factory=ExperimentTracker)

    def features(self, dataset: MarketDataset, windows: Sequence[int] = (5, 20)) -> FeatureSet:
        return FeatureEngineer().build(dataset, windows)

    def backtest(self, dataset: MarketDataset, features: FeatureSet, signal: SignalFunction, parameters: Mapping[str, Any]) -> BacktestResult:
        return Backtester().run(dataset, features, signal, parameters)

    def sweep(self, dataset: MarketDataset, features: FeatureSet, signal: SignalFunction, grid: Mapping[str, Sequence[Any]], objective: str = "sharpe") -> SweepResult:
        experiment_id = uuid4()
        result = ParameterSweeper().run(experiment_id, dataset, features, signal, grid, objective=objective)
        self.tracker.record(ExperimentRecord(name="parameter_sweep", dataset_checksum=dataset.checksum, feature_set=features.name, strategy=getattr(signal, "__name__", "strategy"), parameters={k: list(v) for k, v in grid.items()}, result_type="sweep", result=result.model_dump(mode="json"), tags=("sweep",)))
        return result

    def walk_forward(self, dataset: MarketDataset, features: FeatureSet, signal: SignalFunction, grid: Mapping[str, Sequence[Any]], train_size: int, test_size: int, objective: str = "sharpe") -> WalkForwardResult:
        result = WalkForwardEvaluator().run(dataset, features, signal, grid, train_size=train_size, test_size=test_size, objective=objective)
        self.tracker.record(ExperimentRecord(name="walk_forward_oos", dataset_checksum=dataset.checksum, feature_set=features.name, strategy=getattr(signal, "__name__", "strategy"), parameters={k: list(v) for k, v in grid.items()}, result_type="walk_forward", result=result.model_dump(mode="json"), tags=("walk-forward", "oos")))
        return result

    def experiments(self) -> tuple[ExperimentRecord, ...]:
        return self.tracker.list()
