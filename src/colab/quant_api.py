"""HTTP endpoints for quantitative research and the Phase 18 quant platform."""
from __future__ import annotations

from datetime import datetime
from math import isnan
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .quant_lab import FeatureEngineer, MarketBar, MarketDataset, QuantitativeResearchLab, QuantLabError
from .quant_platform import (ExperimentRecord as DurableExperiment, InMemoryStrategyRegistry, StrategyRecord,
                             monte_carlo, portfolio_risk, robustness_analysis, stress_test)
from .quant_persistence import PostgresQuantStore
from .security import Permission, require_workspace_membership
from .service_adapters import production_connection_factory_from_dsn


class BarInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    symbol: str = Field(min_length=1, max_length=32)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)


class QuantRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=32)
    bars: list[BarInput] = Field(min_length=2)
    fast_window: int = Field(default=5, ge=2, le=250)
    slow_window: int = Field(default=20, ge=3, le=500)
    initial_capital: float = Field(default=100000, gt=0)


class StrategyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    code_revision: str = Field(min_length=1, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ReturnsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    returns: list[float] = Field(min_length=2, max_length=100_000)


class StressRequest(ReturnsRequest):
    scenarios: dict[str, dict[str, float]] = Field(default_factory=dict, max_length=50)
    drawdown_limit: float = Field(default=0.20, gt=0, lt=1)


class MonteCarloRequest(ReturnsRequest):
    simulations: int = Field(default=5000, ge=100, le=100_000)
    horizon: int = Field(default=252, ge=1, le=10_000)
    seed: int = Field(default=42)
    drawdown_threshold: float = Field(default=0.20, gt=0, lt=1)


class RobustnessRequest(ReturnsRequest):
    perturbations: int = Field(default=100, ge=10, le=10_000)
    seed: int = Field(default=42)
    min_sharpe: float = 0.0


class WalkForwardRequest(QuantRunRequest):
    train_size: int = Field(default=100, ge=2, le=10_000)
    test_size: int = Field(default=25, ge=1, le=5_000)
    fast_candidates: list[int] = Field(default_factory=lambda: [5, 10], min_length=1, max_length=20)
    slow_candidates: list[int] = Field(default_factory=lambda: [20, 50], min_length=1, max_length=20)


def _dataset(request: QuantRunRequest) -> MarketDataset:
    bars = tuple(MarketBar.model_validate(item.model_dump()) for item in request.bars)
    return MarketDataset(symbol=request.symbol, bars=bars, source="api")


def register_quant_routes(app: Any) -> None:
    router = APIRouter(prefix="/api/quant", tags=["quantitative-research"])
    lab = QuantitativeResearchLab()
    local_registry = InMemoryStrategyRegistry()
    dsn = os.getenv("COLAB_DATABASE_DSN")
    durable_store = PostgresQuantStore(production_connection_factory_from_dsn(dsn)) if dsn else None

    def authorize(request: Request, workspace_id: UUID, permission: Permission = Permission.WORKSPACE_READ) -> None:
        require_workspace_membership(request, workspace_id, permission)

    def signal(context: Any) -> float:
        values = context.features.rows[context.index].values
        fast = values.get(f"sma_{context.parameters['fast_window']}")
        slow = values.get(f"sma_{context.parameters['slow_window']}")
        if fast is None or slow is None or isnan(fast) or isnan(slow):
            return 0.0
        return 1.0 if fast > slow else 0.0

    @router.post("/backtest")
    def backtest(request: QuantRunRequest) -> dict[str, Any]:
        if request.fast_window >= request.slow_window:
            raise HTTPException(status_code=422, detail="fast_window must be smaller than slow_window")
        dataset = _dataset(request)
        features = FeatureEngineer().build(dataset, (request.fast_window, request.slow_window))
        try:
            result = lab.backtest(dataset, features, signal, {"fast_window": request.fast_window, "slow_window": request.slow_window}, initial_capital=request.initial_capital)
        except QuantLabError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"dataset_checksum": dataset.checksum, "features": list(features.feature_names), "result": result.model_dump(mode="json")}

    @router.post("/walk-forward")
    def walk_forward(request: WalkForwardRequest) -> dict[str, Any]:
        if request.fast_window >= request.slow_window:
            raise HTTPException(status_code=422, detail="fast_window must be smaller than slow_window")
        dataset = _dataset(request)
        features = FeatureEngineer().build(dataset, (min(request.fast_candidates + request.slow_candidates), max(request.fast_candidates + request.slow_candidates)))
        grid = {"fast_window": request.fast_candidates, "slow_window": request.slow_candidates}
        try:
            result = lab.walk_forward(dataset, features, signal, grid, train_size=request.train_size, test_size=request.test_size)
        except QuantLabError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"dataset_checksum": dataset.checksum, "train_size": request.train_size, "test_size": request.test_size, "result": result.model_dump(mode="json")}

    @router.post("/strategies", response_model=StrategyRecord, status_code=201)
    def register_strategy(payload: StrategyCreate, request: Request) -> StrategyRecord:
        authorize(request, payload.workspace_id, Permission.RESEARCH_WRITE)
        existing = (durable_store.list_strategies(payload.workspace_id) if durable_store else local_registry.list(payload.workspace_id))
        version = max((x.version for x in existing if x.name == payload.name), default=0) + 1
        record = StrategyRecord(workspace_id=payload.workspace_id, name=payload.name, version=version,
                                code_revision=payload.code_revision, parameters=payload.parameters, dataset_ids=payload.dataset_ids)
        return durable_store.register_strategy(record) if durable_store else local_registry.register(record)

    @router.get("/strategies", response_model=list[StrategyRecord])
    def list_strategies(request: Request, workspace_id: UUID) -> list[StrategyRecord]:
        authorize(request, workspace_id)
        return durable_store.list_strategies(workspace_id) if durable_store else local_registry.list(workspace_id)

    @router.get("/experiments")
    def experiments(request: Request, workspace_id: UUID | None = None) -> dict[str, Any]:
        if workspace_id is not None:
            authorize(request, workspace_id)
            if durable_store:
                return {"experiments": durable_store.list_experiments(workspace_id)}
        return {"experiments": [record.model_dump(mode="json") for record in lab.experiments()]}

    @router.post("/risk")
    def risk(payload: ReturnsRequest, request: Request) -> dict[str, Any]:
        authorize(request, payload.workspace_id)
        return portfolio_risk(payload.returns).model_dump()

    @router.post("/stress")
    def stress(payload: StressRequest, request: Request) -> list[dict[str, Any]]:
        authorize(request, payload.workspace_id)
        return [x.model_dump() for x in stress_test(payload.returns, payload.scenarios, payload.drawdown_limit)]

    @router.post("/monte-carlo")
    def monte_carlo_endpoint(payload: MonteCarloRequest, request: Request) -> dict[str, Any]:
        authorize(request, payload.workspace_id)
        return monte_carlo(payload.returns, payload.simulations, payload.horizon, payload.seed, payload.drawdown_threshold).model_dump()

    @router.post("/robustness")
    def robustness(payload: RobustnessRequest, request: Request) -> dict[str, Any]:
        authorize(request, payload.workspace_id)
        return robustness_analysis(payload.returns, payload.perturbations, payload.seed, payload.min_sharpe).model_dump()

    app.include_router(router)
