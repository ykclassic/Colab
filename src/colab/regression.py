"""Deterministic regression-suite primitives for release validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field


class RegressionError(ValueError):
    """Raised when a regression suite is malformed."""


class RegressionCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=200)
    expected: float
    tolerance: float = Field(ge=0)
    critical: bool = True


class RegressionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    expected: float
    actual: float
    tolerance: float
    passed: bool
    critical: bool


class RegressionSuiteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    suite_name: str
    passed: bool
    cases: tuple[RegressionResult, ...]
    critical_failures: tuple[str, ...]


@dataclass(frozen=True)
class RegressionSuite:
    name: str
    cases: tuple[RegressionCase, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise RegressionError("suite name cannot be empty")
        if not self.cases:
            raise RegressionError("regression suite must contain at least one case")
        names = [case.name for case in self.cases]
        if len(names) != len(set(names)):
            raise RegressionError("regression case names must be unique")

    def run(self, evaluator: Callable[[RegressionCase], float]) -> RegressionSuiteResult:
        results: list[RegressionResult] = []
        for case in self.cases:
            actual = float(evaluator(case))
            passed = abs(actual - case.expected) <= case.tolerance
            results.append(
                RegressionResult(
                    name=case.name,
                    expected=case.expected,
                    actual=actual,
                    tolerance=case.tolerance,
                    passed=passed,
                    critical=case.critical,
                )
            )
        critical_failures = tuple(result.name for result in results if result.critical and not result.passed)
        return RegressionSuiteResult(
            suite_name=self.name,
            passed=not critical_failures,
            cases=tuple(results),
            critical_failures=critical_failures,
        )


def default_quant_regression_suite() -> RegressionSuite:
    """Stable smoke cases for the Phase 10 quantitative engine."""
    return RegressionSuite(
        name="quantitative-research-core",
        cases=(
            RegressionCase(name="feature_checksum_stable", expected=1.0, tolerance=0.0),
            RegressionCase(name="backtest_next_bar_execution", expected=1.0, tolerance=0.0),
            RegressionCase(name="parameter_grid_deterministic", expected=1.0, tolerance=0.0),
            RegressionCase(name="walk_forward_oos_only", expected=1.0, tolerance=0.0),
        ),
    )
