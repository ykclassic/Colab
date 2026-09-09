from uuid import uuid4

import pytest

from colab.release_governance import (
    GateResult,
    GovernanceError,
    ReadinessReport,
    ReleaseGovernance,
    ReproducibilityManifest,
    StrategyVersion,
)
from colab.regression import RegressionCase, RegressionError, RegressionSuite


WORKSPACE_ID = uuid4()


def version() -> StrategyVersion:
    manifest = ReproducibilityManifest(
        dataset_checksum="dataset-123",
        feature_config={"windows": [5, 20]},
        strategy_parameters={"fast": 5, "slow": 20},
        code_revision="abc123",
        dependency_lock_hash="lock456",
        random_seed=7,
    )
    return StrategyVersion(
        workspace_id=WORKSPACE_ID,
        name="momentum",
        version="1.0.0",
        artifact_digest="artifact-789",
        manifest_hash=manifest.manifest_hash,
    )


def gates(*, production: bool = True, regression: bool = True) -> tuple[GateResult, ...]:
    return (
        GateResult(gate="reproducibility", passed=True, score=100, evidence="manifest verified"),
        GateResult(gate="version_integrity", passed=True, score=100, evidence="digest verified"),
        GateResult(gate="regression", passed=regression, score=100 if regression else 40, evidence="suite"),
        GateResult(gate="operational_readiness", passed=True, score=100, evidence="health checks"),
        GateResult(gate="risk", passed=production, score=100 if production else 40, evidence="risk review"),
    )


def test_manifest_is_reproducible_and_changes_when_inputs_change() -> None:
    first = ReproducibilityManifest(dataset_checksum="d", feature_config={"window": 5}, strategy_parameters={"x": 1}, code_revision="c", dependency_lock_hash="l")
    second = ReproducibilityManifest(dataset_checksum="d", feature_config={"window": 6}, strategy_parameters={"x": 1}, code_revision="c", dependency_lock_hash="l")
    assert first.manifest_hash != second.manifest_hash
    assert first.manifest_hash == ReproducibilityManifest.model_validate(first.model_dump()).manifest_hash


def test_versions_are_immutable_and_unique_per_workspace() -> None:
    governance = ReleaseGovernance()
    first = governance.register_version(version())
    assert governance.get_version(first.version_id) == first
    with pytest.raises(GovernanceError):
        governance.register_version(StrategyVersion(version_id=uuid4(), workspace_id=WORKSPACE_ID, name=first.name, version=first.version, artifact_digest="other", manifest_hash=first.manifest_hash))


def test_readiness_scores_dimensions_and_blocks_failed_required_gates() -> None:
    governance = ReleaseGovernance()
    item = governance.register_version(version())
    report = governance.readiness(item.version_id, gates(regression=False))
    assert isinstance(report, ReadinessReport)
    assert report.workspace_id == WORKSPACE_ID
    assert report.rating == "not-ready"
    assert "regression" in report.blocking_gates


def test_production_promotion_requires_all_gates_and_score() -> None:
    governance = ReleaseGovernance()
    item = governance.register_version(version())
    denied = governance.promote(item.version_id, "staging", "production", gates(regression=False))
    assert not denied.approved
    assert denied.workspace_id == WORKSPACE_ID
    assert any("regression" in reason for reason in denied.reasons)
    approved = governance.promote(item.version_id, "staging", "production", gates())
    assert approved.approved
    assert approved.readiness_score == 100


def test_unknown_promotion_stage_is_rejected() -> None:
    governance = ReleaseGovernance()
    item = governance.register_version(version())
    with pytest.raises(GovernanceError):
        governance.promote(item.version_id, "candidate", "live", gates())


def test_regression_suite_passes_within_tolerance_and_fails_critical_case() -> None:
    suite = RegressionSuite("core", (RegressionCase(name="metric", expected=10, tolerance=0.1), RegressionCase(name="critical", expected=1, tolerance=0, critical=True)))
    passed = suite.run(lambda case: 10.05 if case.name == "metric" else 1)
    assert passed.passed
    failed = suite.run(lambda case: 0 if case.name == "critical" else 10)
    assert not failed.passed
    assert failed.critical_failures == ("critical",)


def test_regression_case_names_must_be_unique() -> None:
    with pytest.raises(RegressionError):
        RegressionSuite("bad", (RegressionCase(name="x", expected=1, tolerance=0), RegressionCase(name="x", expected=1, tolerance=0)))
