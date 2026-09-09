"""Phase 18 quantitative research platform primitives."""
from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol
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
    strategy_version: int = Field(ge=1)
    dataset_ids: list[UUID] = Field(default_factory=list)
    seed: int = 42
    configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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


def _metrics(returns: list[float], annualization: int = 252) -> dict[str, float]:
    if not returns:
        raise QuantPlatformError("returns cannot be empty")
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    mean_return = sum(returns) / len(returns)
    variance = sum((x - mean_return) ** 2 for x in returns) / max(1, len(returns) - 1)
    volatility = math.sqrt(variance) * math.sqrt(annualization)
    downside = [min(0.0, x) for x in returns]
    downside_dev = math.sqrt(sum(x * x for x in downside) / len(returns))
    sharpe = mean_return / math.sqrt(variance) * math.sqrt(annualization) if variance else 0.0
    sortino = mean_return / downside_dev * math.sqrt(annualization) if downside_dev else 0.0
    ordered = sorted(returns)
    cutoff = ordered[max(0, int(len(ordered) * 0.05) - 1)]
    tail = [x for x in returns if x <= cutoff]
    annualized = equity ** (annualization / len(returns)) - 1 if equity > 0 else -1.0
    gains = sum(x for x in returns if x > 0)
    losses = -sum(x for x in returns if x < 0)
    return {
        "total_return": equity - 1,
        "annualized_return": annualized,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": annualized / abs(max_drawdown) if max_drawdown else 0.0,
        "var_95": cutoff,
        "cvar_95": sum(tail) / len(tail),
        "win_rate": sum(x > 0 for x in returns) / len(returns),
        "profit_factor": gains / losses if losses else float("inf"),
    }


def portfolio_risk(returns: list[float]) -> RiskMetrics:
    return RiskMetrics(**_metrics(returns))


def stress_test(returns: list[float], scenarios: dict[str, dict[str, float]], drawdown_limit: float = 0.20) -> list[StressScenario]:
    baseline = _metrics(returns)["total_return"]
    return [StressScenario(name=name, shock=shock, portfolio_return=baseline + sum(shock.values()), breached_limits=["return_floor"] if baseline + sum(shock.values()) < -drawdown_limit else []) for name, shock in scenarios.items()]


def monte_carlo(returns: list[float], simulations: int = 5000, horizon: int = 252, seed: int = 42, drawdown_threshold: float = 0.20) -> MonteCarloResult:
    if not returns or simulations < 1 or horizon < 1:
        raise QuantPlatformError("invalid Monte Carlo inputs")
    rng = random.Random(seed)
    terminals: list[float] = []
    drawdown_hits = 0
    for _ in range(simulations):
        equity = peak = 1.0
        hit = False
        for _ in range(horizon):
            equity *= 1 + rng.choice(returns)
            peak = max(peak, equity)
            hit = hit or equity / peak - 1 <= -drawdown_threshold
        terminals.append(equity - 1)
        drawdown_hits += int(hit)
    terminals.sort()
    def percentile(point: float) -> float:
        return terminals[min(len(terminals) - 1, int(point * len(terminals)))]
    return MonteCarloResult(simulations=simulations, seed=seed, percentiles={"p05": percentile(.05), "p50": percentile(.50), "p95": percentile(.95)}, probability_loss=sum(x < 0 for x in terminals) / simulations, probability_drawdown=drawdown_hits / simulations)


def robustness_analysis(returns: list[float], perturbations: int = 100, seed: int = 42, min_sharpe: float = 0.0) -> RobustnessResult:
    if not returns or perturbations < 1:
        raise QuantPlatformError("invalid robustness inputs")
    rng = random.Random(seed)
    sharpes = [_metrics([x * rng.uniform(.8, 1.2) for x in returns])["sharpe"] for _ in range(perturbations)]
    ordered = sorted(sharpes)
    failures = [f"sharpe<{min_sharpe}" for value in sharpes if value < min_sharpe]
    return RobustnessResult(perturbations=perturbations, median_sharpe=ordered[len(ordered) // 2], worst_sharpe=min(ordered), best_sharpe=max(ordered), pass_rate=sum(x >= min_sharpe for x in ordered) / len(ordered), failures=failures[:10])


def experiment_hash(experiment: ExperimentRecord) -> str:
    canonical = experiment.model_dump(mode="json")
    return sha256(str(sorted(canonical.items())).encode()).hexdigest()
