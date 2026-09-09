"""Phase 21E quantitative research vertical-slice orchestration."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any
from uuid import uuid4

from .quant_lab import (
    BacktestResult,
    FeatureEngineer,
    MarketDataset,
    ParameterSweeper,
    QuantitativeResearchLab,
    SignalFunction,
    WalkForwardResult,
)
from .quant_platform import ExperimentRecord, StrategyRecord, experiment_hash, monte_carlo, portfolio_risk, robustness_analysis, stress_test
from .quant_validation import QuantScientificValidator, ScientificValidation


class QuantVerticalSliceError(ValueError):
    """Raised when the quantitative vertical slice cannot be completed safely."""


class QuantVerticalSlice:
    """Run dataset → strategy → experiment → OOS → risk analytics as one auditable unit."""

    def __init__(self, *, validator: QuantScientificValidator | None = None) -> None:
        self.validator = validator or QuantScientificValidator()
        self.lab = QuantitativeResearchLab()

    def run(
        self,
        *,
        dataset: MarketDataset,
        strategy: StrategyRecord,
        parameter_grid: Mapping[str, Sequence[Any]],
        signal: SignalFunction,
        train_size: int,
        test_size: int,
        seed: int = 42,
        scenarios: dict[str, dict[str, float]] | None = None,
        validation_metadata: dict[str, Any] | None = None,
        commission_bps: float = 1.0,
        slippage_bps: float = 1.0,
    ) -> dict[str, Any]:
        if strategy.dataset_ids and dataset.dataset_id not in strategy.dataset_ids:
            raise QuantVerticalSliceError("strategy is not bound to the supplied dataset")
        if train_size + test_size > len(dataset.bars):
            raise QuantVerticalSliceError("train_size + test_size exceeds dataset length")

        features = FeatureEngineer().build(dataset, sorted({int(x) for values in parameter_grid.values() for x in values if isinstance(x, int) and x >= 2}) or (5, 20))
        validation = self.validator.validate(
            dataset, features,
            train_end=dataset.bars[train_size - 1].timestamp,
            test_start=dataset.bars[train_size].timestamp,
            metadata=validation_metadata,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
        if not validation.passed:
            raise QuantVerticalSliceError("scientific validation failed: " + ", ".join(x.check for x in validation.failures))

        sweep = ParameterSweeper().run(uuid4(), dataset, features, signal, parameter_grid)
        backtest = sweep.results[sweep.best_index or 0]
        walk_forward = self.lab.walk_forward(dataset, features, signal, parameter_grid, train_size=train_size, test_size=test_size)
        returns = self._returns(backtest)
        risk = portfolio_risk(returns)
        stress = stress_test(returns, scenarios or {"market_shock": {"market": -0.10}})
        mc = monte_carlo(returns, seed=seed)
        robust = robustness_analysis(returns, seed=seed)
        experiment = ExperimentRecord(
            workspace_id=strategy.workspace_id,
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.version,
            dataset_ids=[dataset.dataset_id],
            seed=seed,
            configuration={"parameter_grid": dict(parameter_grid), "train_size": train_size, "test_size": test_size},
            metrics={"backtest_sharpe": backtest.metrics.sharpe, "oos_sharpe": walk_forward.stitched_metrics.sharpe},
        )
        digest = experiment_hash(experiment)
        reproducibility = self._reproducibility(dataset, strategy, experiment, validation, backtest, walk_forward, digest)
        return {
            "workspace_id": strategy.workspace_id, "dataset": dataset, "strategy": strategy, "experiment": experiment,
            "experiment_hash": digest, "scientific_validation": validation, "backtest": backtest,
            "walk_forward_oos": walk_forward, "risk": risk, "stress": tuple(stress), "monte_carlo": mc,
            "robustness": robust, "reproducibility_hash": reproducibility,
        }

    @staticmethod
    def _returns(result: BacktestResult) -> list[float]:
        if len(result.equity_curve) < 2:
            raise QuantVerticalSliceError("backtest did not produce enough observations")
        return [result.equity_curve[i] / result.equity_curve[i - 1] - 1 for i in range(1, len(result.equity_curve)) if result.equity_curve[i - 1] > 0]

    @staticmethod
    def _reproducibility(dataset: MarketDataset, strategy: StrategyRecord, experiment: ExperimentRecord,
                         validation: ScientificValidation, backtest: BacktestResult,
                         walk_forward: WalkForwardResult, experiment_digest: str) -> str:
        canonical = repr({
            "workspace": str(strategy.workspace_id), "dataset": dataset.checksum,
            "strategy": strategy.model_dump(mode="json"), "experiment": experiment.model_dump(mode="json"),
            "experiment_hash": experiment_digest, "validation": validation.validation_hash,
            "backtest": backtest.model_dump(mode="json"), "walk_forward": walk_forward.model_dump(mode="json"),
        })
        return sha256(canonical.encode()).hexdigest()
