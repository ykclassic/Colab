"""API for the Phase 21E quantitative research vertical slice."""
from __future__ import annotations

from datetime import datetime
from math import isnan
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .quant_lab import MarketBar, MarketDataset
from .quant_platform import StrategyRecord
from .quant_vertical_slice import QuantVerticalSlice, QuantVerticalSliceError
from .security import Permission, require_workspace_membership


class VerticalBar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    symbol: str = Field(min_length=1, max_length=32)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)


class VerticalSliceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    dataset_id: UUID | None = None
    strategy_id: UUID | None = None
    strategy_name: str = Field(default="SMA research strategy", min_length=1, max_length=200)
    code_revision: str = Field(default="phase-21e", min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=32)
    bars: list[VerticalBar] = Field(min_length=30)
    fast_candidates: list[int] = Field(default_factory=lambda: [5, 10], min_length=1, max_length=10)
    slow_candidates: list[int] = Field(default_factory=lambda: [20, 30], min_length=1, max_length=10)
    train_size: int = Field(default=100, ge=20, le=10_000)
    test_size: int = Field(default=25, ge=5, le=5_000)
    seed: int = 42
    validation_metadata: dict[str, Any] = Field(default_factory=dict)
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=1.0, gt=0)


def register_quant_vertical_routes(app: Any) -> None:
    router = APIRouter(prefix="/api/quant", tags=["quantitative-research"])

    @router.post("/vertical-slice")
    def vertical_slice(payload: VerticalSliceRequest, request: Request) -> dict[str, Any]:
        require_workspace_membership(request, payload.workspace_id, Permission.RESEARCH_WRITE)
        bars = tuple(MarketBar.model_validate(item.model_dump()) for item in payload.bars)
        dataset = MarketDataset(symbol=payload.symbol, bars=bars, source="api", dataset_id=payload.dataset_id or uuid4())
        if payload.train_size + payload.test_size > len(bars):
            raise HTTPException(status_code=422, detail="train_size + test_size exceeds dataset length")
        strategy = StrategyRecord(
            strategy_id=payload.strategy_id or uuid4(), workspace_id=payload.workspace_id,
            name=payload.strategy_name, code_revision=payload.code_revision,
            parameters={"fast_candidates": payload.fast_candidates, "slow_candidates": payload.slow_candidates},
            dataset_ids=[dataset.dataset_id],
        )

        def signal(context: Any) -> float:
            values = context.features.rows[context.index].values
            fast = values.get(f"sma_{context.parameters['fast']}")
            slow = values.get(f"sma_{context.parameters['slow']}")
            if fast is None or slow is None or isnan(fast) or isnan(slow):
                return 0.0
            return 1.0 if fast > slow else 0.0

        try:
            result = QuantVerticalSlice().run(
                dataset=dataset, strategy=strategy,
                parameter_grid={"fast": payload.fast_candidates, "slow": payload.slow_candidates},
                signal=signal, train_size=payload.train_size, test_size=payload.test_size,
                seed=payload.seed, validation_metadata=payload.validation_metadata,
                commission_bps=payload.commission_bps, slippage_bps=payload.slippage_bps,
            )
        except QuantVerticalSliceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value for key, value in result.items()}

    app.include_router(router)
