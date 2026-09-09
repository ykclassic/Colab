"""HTTP endpoints for the Phase 10 quantitative research lab."""
from __future__ import annotations

from datetime import datetime
from math import isnan
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .quant_lab import (
    FeatureEngineer,
    MarketBar,
    MarketDataset,
    QuantLabError,
    QuantitativeResearchLab,
)


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


def _dataset(request: QuantRunRequest) -> MarketDataset:
    bars = tuple(MarketBar.model_validate(item.model_dump()) for item in request.bars)
    return MarketDataset(symbol=request.symbol, bars=bars, source="api")


def register_quant_routes(app: Any) -> None:
    router = APIRouter(prefix="/api/quant", tags=["quantitative-research"])
    lab = QuantitativeResearchLab()

    @router.post("/backtest")
    def backtest(request: QuantRunRequest) -> dict[str, Any]:
        if request.fast_window >= request.slow_window:
            raise HTTPException(status_code=422, detail="fast_window must be smaller than slow_window")
        dataset = _dataset(request)
        features = FeatureEngineer().build(dataset, (request.fast_window, request.slow_window))

        def moving_average_signal(context: Any) -> float:
            values = context.features.rows[context.index].values
            fast = values.get(f"sma_{context.parameters['fast_window']}")
            slow = values.get(f"sma_{context.parameters['slow_window']}")
            if fast is None or slow is None or isnan(fast) or isnan(slow):
                return 0.0
            return 1.0 if fast > slow else 0.0

        try:
            result = lab.backtest(
                dataset,
                features,
                moving_average_signal,
                {"fast_window": request.fast_window, "slow_window": request.slow_window},
            )
        except QuantLabError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "dataset_checksum": dataset.checksum,
            "features": list(features.feature_names),
            "result": result.model_dump(mode="json"),
        }

    @router.get("/experiments")
    def experiments() -> dict[str, Any]:
        return {"experiments": [record.model_dump(mode="json") for record in lab.experiments()]}

    app.include_router(router)
