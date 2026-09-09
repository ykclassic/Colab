"""Scientific validation gates for quantitative research experiments."""
from __future__ import annotations

from collections import pairwise
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from .quant_lab import FeatureSet, MarketDataset


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

    def validate(
        self,
        dataset: MarketDataset,
        features: FeatureSet,
        *,
        train_end: datetime | None = None,
        test_start: datetime | None = None,
        expected_interval: timedelta | None = None,
        max_stale_intervals: int = 1,
        metadata: dict[str, Any] | None = None,
        parameter_selection: str = "train",
        execution_timing: str = "next_bar_open",
        commission_bps: float = 1.0,
        slippage_bps: float = 1.0,
    ) -> ScientificValidation:
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
