"""Phase 18 quantitative research platform primitives."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class QuantPlatformError(RuntimeError):
    """Base quant-platform error."""


class StrategyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    code_revision: str = Field(min_length=1, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dataset_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    strategy_id: UUID
    strategy_version: int
    dataset_ids: list[UUID] = Field(default_factory=list)
    seed: int = 0
    configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WindowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    metrics: dict[str, float]


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    windows: list[WindowResult]
    aggregate_metrics: dict[str, float]
    out_of_sample: bool = True


class RiskMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_return: float
    annualized_return: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    var_95: float
    cvar_95: float
    win_rate: float
    profit_factor: float


class StressScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    shock: dict[str, float]
    portfolio_return: float
    breached_limits: list[str] = Field(default_factory=list)


class MonteCarloResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulations: int
    seed: int
    percentiles: dict[str, float]
    probability_loss: float
    probability_drawdown: float


class RobustnessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    perturbations: int
    median_sharpe: float
    worst_sharpe: float
    best_sharpe: float
    pass_rate: float
    failures: list[str] = Field(default_factory=list)


class StrategyRegistry(Protocol):
    def register(self, strategy: StrategyRecord) -> StrategyRecord: ...
    def list(self, workspace_id: UUID) -> list[StrategyRecord]: ...


class InMemoryStrategyRegistry:
    def __init__(self) -> None:
        self._items: dict[UUID, StrategyRecord] = {}

    def register(self, strategy: StrategyRecord) -> StrategyRecord:
        self._items[strategy.strategy_id] = strategy
        return strategy

    def list(self, workspace_id: UUID) -> list[StrategyRecord]:
        return sorted((x for x in self._items.values() if x.workspace_id == workspace_id), key=lambda x: (x.name, x.version))


def _basic_metrics(returns: list[float], annualization: int = 252) -> dict[str, float]:
    if not returns:
        return {k: 0.0 for k in ("total_return", "annualized_return", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "var_95", "cvar_95", "win_rate", "profit_factor")}
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
    mean = sum(returns) / len(returns)
    variance = sum((x - mean) ** 2 for x in returns) / max(1, len(returns) - 1)
    vol = math.sqrt(max(0.0, variance)) * math.sqrt(annualization)
    downside = [min(0.0, x) for x in returns]
    down_dev = math.sqrt(sum(x * x for x in downside) / len(returns)) * math.sqrt(annualization)
    sharpe = mean / math.sqrt(variance) * math.sqrt(annualization) if variance > 0 else 0.0
    sortino = mean / (down_dev / math.sqrt(annualization)) * math.sqrt(annualization) if down_dev > 0 else 0.0
    gains = sum(x for x in returns if x > 0)
    losses = -sum(x for x in returns if x < 0)
    return {"total_return": equity - 1.0, "annualized_return": equity ** (annualization / len(returns)) - 1.0,
            "volatility": vol, "sharpe": sharpe, "sortino": sortino, "max_drawdown": max_dd,
            "calmar": (equity ** (annualization / len(returns)) - 1.0) / abs(max_dd) if max_dd < 0 else 0.0,
            "var_95": sorted(returns)[max(0, int(len(returns) * 0.05) - 1)],
            "cvar_95": sum(x for x in returns if x <= sorted(returns)[max(0, int(len(returns) * 0.05) - 1)]) / max(1, len([x for x in returns if x <= sorted(returns)[max(0, int(len(returns) * 0.05) - 1)])),
            "win_rate": sum(x > 0 for x in returns) / len(returns), "profit_factor": gains / losses if losses else float("inf")}


def walk_forward(returns: list[float], train_size: int, test_size: int, step: int | None = None) -> WalkForwardResult:
    if train_size < 1 or test_size < 1 or len(returns) < train_size + test_size:
        raise QuantPlatformError("insufficient observations for walk-forward analysis")
    step = step or test_size
    windows: list[WindowResult] = []
    start = 0
    wid = 0
    while start + train_size + test_size <= len(returns):
        test = returns[start + train_size:start + train_size + test_size]
        windows.append(WindowResult(window_id=wid, train_start=start, train_end=start + train_size,
                                    test_start=start + train_size, test_end=start + train_size + test_size,
                                    metrics=_basic_metrics(test)))
        wid += 1
        start += step
    aggregate = _basic_metrics([x for w in windows for x in returns[w.test_start:w.test_end]])
    return WalkForwardResult(windows=windows, aggregate_metrics=aggregate)


def portfolio_risk(returns: list[float]) -> RiskMetrics:
    return RiskMetrics(**_basic_metrics(returns))


def stress_test(returns: list[float], scenarios: dict[str, dict[str, float]], drawdown_limit: float = 0.20) -> list[StressScenario]:
    baseline = _basic_metrics(returns)["total_return"]
    results = []
    for name, shock in scenarios.items():
        stressed = baseline + sum(shock.values())
        breached = ["return_floor"] if stressed < -drawdown_limit else []
        results.append(StressScenario(name=name, shock=shock, portfolio_return=stressed, breached_limits=breached))
    return results


def monte_carlo(returns: list[float], simulations: int = 5000, horizon: int = 252, seed: int = 42, drawdown_threshold: float = 0.20) -> MonteCarloResult:
    if not returns or simulations < 1 or horizon < 1:
        raise QuantPlatformError("invalid Monte Carlo inputs")
    rng = random.Random(seed)
    terminal: list[float] = []
    drawdown_hits = 0
    for _ in range(simulations):
        equity = peak = 1.0
        hit = False
        for _ in range(horizon):
            equity *= 1.0 + rng.choice(returns)
            peak = max(peak, equity)
            if equity / peak - 1.0 <= -drawdown_threshold:
                hit = True
        terminal.append(equity - 1.0)
        drawdown_hits += hit
    terminal.sort()
    percentile = lambda p: terminal[min(len(terminal) - 1, max(0, int(p * len(terminal))))]
    return MonteCarloResult(simulations=simulations, seed=seed,
                            percentiles={"p05": percentile(0.05), "p50": percentile(0.50), "p95": percentile(0.95)},
                            probability_loss=sum(x < 0 for x in terminal) / simulations,
                            probability_drawdown=drawdown_hits / simulations)


def robustness_analysis(returns: list[float], perturbations: int = 100, seed: int = 42, min_sharpe: float = 0.0) -> RobustnessResult:
    rng = random.Random(seed)
    sharpes = []
    for _ in range(perturbations):
        sample = [x * rng.uniform(0.8, 1.2) for x in returns]
        sharpes.append(_basic_metrics(sample)["sharpe"])
    failures = [f"sharpe<{min_sharpe}" for x in sharpes if x < min_sharpe]
    return RobustnessResult(perturbations=perturbations, median_sharpe=sorted(sharpes)[len(sharpes)//2],
                            worst_sharpe=min(sharpes), best_sharpe=max(sharpes),
                            pass_rate=sum(x >= min_sharpe for x in sharpes) / len(sharpes), failures=failures[:10])


def experiment_hash(experiment: ExperimentRecord) -> str:
    return sha256(experiment.model_dump_json(sort_keys=True).encode()).hexdigest()
