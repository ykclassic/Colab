"""Production validation and release governance primitives.

This module keeps production promotion deterministic and auditable. It models
immutable strategy/model versions, reproducibility manifests, regression gate
results, promotion gates, and a weighted production-readiness score. It does
not deploy or execute trading activity.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class GovernanceError(ValueError):
    """Raised when a release-governance invariant is violated."""


class ReproducibilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_checksum: str = Field(min_length=1)
    feature_config: dict[str, Any]
    strategy_parameters: dict[str, Any]
    code_revision: str = Field(min_length=1)
    dependency_lock_hash: str = Field(min_length=1)
    random_seed: int | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    manifest_hash: str = ""

    def model_post_init(self, __context: Any, /) -> None:
        if self.manifest_hash:
            return
        canonical = repr(
            (
                self.dataset_checksum,
                sorted(self.feature_config.items()),
                sorted(self.strategy_parameters.items()),
                self.code_revision,
                self.dependency_lock_hash,
                self.random_seed,
                sorted(self.environment.items()),
            )
        )
        object.__setattr__(self, "manifest_hash", sha256(canonical.encode()).hexdigest())


class StrategyVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    artifact_digest: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    gate: str = Field(min_length=1, max_length=100)
    passed: bool
    score: float = Field(ge=0, le=100)
    required: bool = True
    evidence: str = ""
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision_id: UUID = Field(default_factory=uuid4)
    version_id: UUID
    from_stage: str
    to_stage: str
    approved: bool
    readiness_score: float = Field(ge=0, le=100)
    gates: tuple[GateResult, ...]
    reasons: tuple[str, ...] = ()
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version_id: UUID
    score: float = Field(ge=0, le=100)
    rating: str
    dimensions: dict[str, float]
    blocking_gates: tuple[str, ...]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class GatePolicy:
    minimum_score: float
    required_gates: tuple[str, ...]


class ReleaseGovernance:
    """Append-only release governance service for research-to-production promotion."""

    POLICIES: Mapping[str, GatePolicy] = {
        "candidate": GatePolicy(70.0, ("reproducibility", "version_integrity", "regression")),
        "staging": GatePolicy(80.0, ("reproducibility", "version_integrity", "regression", "operational_readiness")),
        "production": GatePolicy(90.0, ("reproducibility", "version_integrity", "regression", "operational_readiness", "risk")),
    }

    def __init__(self) -> None:
        self._versions: dict[UUID, StrategyVersion] = {}
        self._decisions: list[PromotionDecision] = []

    def register_version(self, version: StrategyVersion) -> StrategyVersion:
        if version.version_id in self._versions:
            raise GovernanceError("strategy version ID already exists")
        if any(v.name == version.name and v.version == version.version for v in self._versions.values()):
            raise GovernanceError("strategy version already registered")
        self._versions[version.version_id] = version
        return version

    def get_version(self, version_id: UUID) -> StrategyVersion:
        try:
            return self._versions[version_id]
        except KeyError as exc:
            raise GovernanceError("strategy version not found") from exc

    def readiness(self, version_id: UUID, gates: tuple[GateResult, ...]) -> ReadinessReport:
        self.get_version(version_id)
        if not gates:
            raise GovernanceError("at least one gate result is required")
        dimensions = {gate.gate: gate.score for gate in gates}
        score = sum(dimensions.values()) / len(dimensions)
        blocking = tuple(gate.gate for gate in gates if gate.required and not gate.passed)
        if score >= 90 and not blocking:
            rating = "production-ready"
        elif score >= 80 and not blocking:
            rating = "staging-ready"
        elif score >= 70 and not blocking:
            rating = "candidate-ready"
        else:
            rating = "not-ready"
        return ReadinessReport(version_id=version_id, score=score, rating=rating, dimensions=dimensions, blocking_gates=blocking)

    def promote(self, version_id: UUID, from_stage: str, to_stage: str, gates: tuple[GateResult, ...]) -> PromotionDecision:
        policy = self.POLICIES.get(to_stage)
        if policy is None:
            raise GovernanceError(f"unsupported promotion stage: {to_stage}")
        if from_stage == to_stage:
            raise GovernanceError("source and target stages must differ")
        report = self.readiness(version_id, gates)
        by_name = {gate.gate: gate for gate in gates}
        reasons: list[str] = []
        for required in policy.required_gates:
            gate = by_name.get(required)
            if gate is None:
                reasons.append(f"missing required gate: {required}")
            elif not gate.passed:
                reasons.append(f"required gate failed: {required}")
        if report.score < policy.minimum_score:
            reasons.append(f"readiness score {report.score:.2f} is below {policy.minimum_score:.2f}")
        decision = PromotionDecision(
            version_id=version_id,
            from_stage=from_stage,
            to_stage=to_stage,
            approved=not reasons,
            readiness_score=report.score,
            gates=gates,
            reasons=tuple(reasons),
        )
        self._decisions.append(decision)
        return decision

    def decisions(self) -> tuple[PromotionDecision, ...]:
        return tuple(self._decisions)

    def versions(self) -> tuple[StrategyVersion, ...]:
        return tuple(self._versions.values())
