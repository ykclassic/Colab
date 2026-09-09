"""Cryptographic workflow integrity primitives and replay validation."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from .contracts import Decision, Stage, WorkflowState
from .orchestrator import WorkflowError


class WorkflowIntegrityError(WorkflowError):
    """Raised when a workflow event/snapshot chain is invalid."""


def canonical_state_payload(state: WorkflowState) -> dict[str, Any]:
    """Return state data suitable for deterministic hashing."""
    payload = state.model_dump(mode="json")
    payload.pop("audit_events", None)
    return payload


def state_hash(state: WorkflowState) -> str:
    """Return a stable SHA-256 digest for canonical workflow state."""
    encoded = json.dumps(
        canonical_state_payload(state),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_stage_transition(source: Stage, target: Stage, state: WorkflowState) -> None:
    """Reject stage jumps that cannot be produced by the deterministic workflow."""
    allowed = {
        Stage.INTAKE: {Stage.INTAKE, Stage.DECOMPOSITION},
        Stage.DECOMPOSITION: {Stage.DECOMPOSITION, Stage.RESEARCH},
        Stage.RESEARCH: {Stage.RESEARCH, Stage.STRATEGY},
        Stage.STRATEGY: {Stage.STRATEGY, Stage.RISK},
        Stage.RISK: {Stage.RISK, Stage.IMPLEMENTATION, Stage.STRATEGY, Stage.REJECTED},
        Stage.IMPLEMENTATION: {Stage.IMPLEMENTATION, Stage.VALIDATION},
        Stage.VALIDATION: {Stage.VALIDATION, Stage.SYNTHESIS},
        Stage.SYNTHESIS: {Stage.SYNTHESIS, Stage.HUMAN_REVIEW},
        Stage.HUMAN_REVIEW: {Stage.HUMAN_REVIEW, Stage.COMPLETE, Stage.REJECTED},
        Stage.COMPLETE: {Stage.COMPLETE},
        Stage.REJECTED: {Stage.REJECTED},
    }
    if target not in allowed[source]:
        raise WorkflowIntegrityError(f"invalid workflow transition: {source.value} -> {target.value}")
    if (
        source == Stage.RISK
        and target == Stage.IMPLEMENTATION
        and (not state.risk_assessments or state.risk_assessments[-1].decision != Decision.APPROVE)
    ):
        raise WorkflowIntegrityError("implementation requires an explicit approved risk assessment")
    if (
        source == Stage.HUMAN_REVIEW
        and target == Stage.COMPLETE
        and (not state.approvals or state.approvals[-1].get("decision") != Decision.APPROVE)
    ):
        raise WorkflowIntegrityError("completion requires explicit human approval")


def validate_event_chain(events: Iterable[dict[str, Any]]) -> None:
    """Validate sequence numbers, hash chaining, and stage transitions."""
    ordered = sorted(events, key=lambda event: int(event["sequence_no"]))
    previous_hash: str | None = None
    previous_stage: Stage | None = None
    expected_sequence = 1
    allowed = {
        Stage.INTAKE: {Stage.INTAKE, Stage.DECOMPOSITION},
        Stage.DECOMPOSITION: {Stage.DECOMPOSITION, Stage.RESEARCH},
        Stage.RESEARCH: {Stage.RESEARCH, Stage.STRATEGY},
        Stage.STRATEGY: {Stage.STRATEGY, Stage.RISK},
        Stage.RISK: {Stage.RISK, Stage.IMPLEMENTATION, Stage.STRATEGY, Stage.REJECTED},
        Stage.IMPLEMENTATION: {Stage.IMPLEMENTATION, Stage.VALIDATION},
        Stage.VALIDATION: {Stage.VALIDATION, Stage.SYNTHESIS},
        Stage.SYNTHESIS: {Stage.SYNTHESIS, Stage.HUMAN_REVIEW},
        Stage.HUMAN_REVIEW: {Stage.HUMAN_REVIEW, Stage.COMPLETE, Stage.REJECTED},
        Stage.COMPLETE: {Stage.COMPLETE},
        Stage.REJECTED: {Stage.REJECTED},
    }
    for event in ordered:
        sequence = int(event["sequence_no"])
        if sequence != expected_sequence:
            raise WorkflowIntegrityError(f"workflow event sequence gap: expected {expected_sequence}, got {sequence}")
        if event.get("previous_state_hash") != previous_hash:
            raise WorkflowIntegrityError(f"workflow event {sequence} has an invalid previous state hash")
        resulting_hash = event.get("resulting_state_hash")
        if not isinstance(resulting_hash, str) or len(resulting_hash) != 64:
            raise WorkflowIntegrityError(f"workflow event {sequence} has an invalid resulting state hash")
        source = Stage(event["from_stage"])
        target = Stage(event["to_stage"])
        if previous_stage is not None and source != previous_stage:
            raise WorkflowIntegrityError(f"workflow event {sequence} has a broken stage chain")
        if target not in allowed[source]:
            raise WorkflowIntegrityError(f"workflow event {sequence} skips a stage: {source.value} -> {target.value}")
        previous_hash = resulting_hash
        previous_stage = target
        expected_sequence += 1


def validate_snapshot_hash(snapshot: dict[str, Any]) -> None:
    """Validate the persisted snapshot's declared hash."""
    state = WorkflowState.model_validate(snapshot["state"])
    expected = state_hash(state)
    if snapshot.get("state_hash") != expected:
        raise WorkflowIntegrityError(f"snapshot {snapshot.get('version', '?')} failed state hash validation")
