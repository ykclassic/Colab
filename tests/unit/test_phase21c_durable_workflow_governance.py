"""Phase 21C durable workflow and governance verification tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from colab.contracts import Stage, WorkflowState
from colab.durable_workflow_governance import (
    ApprovalBinding,
    DurableGovernanceStateMachine,
    GovernanceState,
    GovernanceStateError,
    expiry_after,
    verify_workflow_replay,
)
from colab.workflow_integrity import WorkflowIntegrityError, state_hash


def _event(sequence: int, previous: str | None, source: Stage, target: Stage, digest: str, snapshot_version: int) -> dict[str, object]:
    return {
        "sequence_no": sequence,
        "previous_state_hash": previous,
        "resulting_state_hash": digest,
        "from_stage": source.value,
        "to_stage": target.value,
        "snapshot_version": snapshot_version,
    }


def _workflow() -> WorkflowState:
    return WorkflowState(product_goal="verify durable workflow", workspace_id=uuid4())


def test_full_governance_lifecycle_is_deterministic_and_append_only() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    machine = DurableGovernanceStateMachine(
        binding=ApprovalBinding(uuid4(), uuid4(), uuid4(), "artifact-v1", "risk-v1", "inputs-v1")
    )
    expected = [
        GovernanceState.DRAFT,
        GovernanceState.SUBMITTED,
        GovernanceState.RISK_REVIEW,
        GovernanceState.RISK_APPROVED,
        GovernanceState.HUMAN_REVIEW,
        GovernanceState.APPROVED,
        GovernanceState.PROMOTED,
    ]
    for index, target in enumerate(expected):
        machine.transition(target, "actor", now=now + timedelta(minutes=index))
    machine.verify_event_chain()
    assert machine.state == GovernanceState.PROMOTED
    assert [event.to_state for event in machine.events] == expected
    assert machine.events[-1].previous_event_hash == machine.events[-2].event_hash


def test_governance_rejects_illegal_jumps_and_post_terminal_mutations() -> None:
    machine = DurableGovernanceStateMachine()
    machine.transition(GovernanceState.DRAFT, "creator")
    with pytest.raises(GovernanceStateError):
        machine.transition(GovernanceState.APPROVED, "reviewer")
    machine.transition(GovernanceState.SUBMITTED, "creator")
    machine.transition(GovernanceState.REJECTED, "reviewer", "failed review")
    with pytest.raises(GovernanceStateError):
        machine.transition(GovernanceState.DRAFT, "creator")


def test_rejection_invalidation_supersession_and_expiry_paths() -> None:
    rejected = DurableGovernanceStateMachine()
    rejected.transition(GovernanceState.DRAFT, "creator")
    rejected.transition(GovernanceState.SUBMITTED, "creator")
    rejected.transition(GovernanceState.REJECTED, "reviewer", "insufficient evidence")
    assert rejected.state == GovernanceState.REJECTED

    invalidated = DurableGovernanceStateMachine(binding=ApprovalBinding(uuid4(), uuid4(), uuid4(), "a", "r", "digest-a"))
    for state in (GovernanceState.DRAFT, GovernanceState.SUBMITTED, GovernanceState.RISK_REVIEW, GovernanceState.RISK_APPROVED):
        invalidated.transition(state, "actor")
    invalidated.invalidate_for_input_change("digest-b", "artifact changed")
    assert invalidated.state == GovernanceState.INVALIDATED

    superseded = DurableGovernanceStateMachine()
    superseded.transition(GovernanceState.DRAFT, "creator")
    superseded.supersede("newer candidate created")
    assert superseded.state == GovernanceState.SUPERSEDED

    base = datetime(2026, 9, 9, tzinfo=UTC)
    expired = DurableGovernanceStateMachine()
    expired.transition(GovernanceState.DRAFT, "creator", now=base)
    expired.transition(GovernanceState.SUBMITTED, "creator", now=base)
    expired.set_expiry(expiry_after(1, now=base))
    assert expired.expire_if_due(now=base + timedelta(days=1, seconds=1)) is True
    assert expired.state == GovernanceState.EXPIRED


def test_approved_governance_is_invalidated_when_any_bound_digest_changes() -> None:
    machine = DurableGovernanceStateMachine(binding=ApprovalBinding(uuid4(), uuid4(), uuid4(), "artifact-a", "risk-a", "digest-a"))
    for state in (
        GovernanceState.DRAFT,
        GovernanceState.SUBMITTED,
        GovernanceState.RISK_REVIEW,
        GovernanceState.RISK_APPROVED,
        GovernanceState.HUMAN_REVIEW,
        GovernanceState.APPROVED,
    ):
        machine.transition(state, "actor")
    machine.invalidate_for_input_change("digest-b", "strategy parameters changed")
    assert machine.state == GovernanceState.INVALIDATED
    assert machine.events[-1].reason == "strategy parameters changed"
    with pytest.raises(GovernanceStateError):
        machine.invalidate_for_input_change("digest-c", "second change")


def test_governance_event_tampering_is_detected() -> None:
    machine = DurableGovernanceStateMachine()
    machine.transition(GovernanceState.DRAFT, "creator")
    machine.transition(GovernanceState.SUBMITTED, "creator")
    original = machine.events
    object.__setattr__(original[0], "reason", "tampered")
    with pytest.raises(WorkflowIntegrityError):
        machine.verify_event_chain()


def test_workflow_replay_accepts_complete_chain_and_rejects_tampering() -> None:
    original = _workflow()
    state_v1 = original.model_copy(deep=True)
    state_v2 = original.model_copy(update={"current_stage": Stage.DECOMPOSITION}, deep=True)
    state_v3 = state_v2.model_copy(update={"current_stage": Stage.RESEARCH}, deep=True)
    digest1, digest2, digest3 = state_hash(state_v1), state_hash(state_v2), state_hash(state_v3)
    snapshots = [
        {"version": 1, "state": state_v1.model_dump(mode="json"), "state_hash": digest1},
        {"version": 2, "state": state_v2.model_dump(mode="json"), "state_hash": digest2},
        {"version": 3, "state": state_v3.model_dump(mode="json"), "state_hash": digest3},
    ]
    events = [
        _event(1, None, Stage.INTAKE, Stage.INTAKE, digest1, 1),
        _event(2, digest1, Stage.INTAKE, Stage.DECOMPOSITION, digest2, 2),
        _event(3, digest2, Stage.DECOMPOSITION, Stage.RESEARCH, digest3, 3),
    ]
    replayed = verify_workflow_replay(original, snapshots, events)
    assert replayed.current_stage == Stage.RESEARCH
    events[2]["resulting_state_hash"] = "0" * 64
    with pytest.raises(WorkflowIntegrityError):
        verify_workflow_replay(original, snapshots, events)


def test_workflow_replay_cannot_cross_workflow_identity() -> None:
    original = _workflow()
    foreign = _workflow()
    digest = state_hash(foreign)
    snapshots = [{"version": 1, "state": foreign.model_dump(mode="json"), "state_hash": digest}]
    events = [_event(1, None, Stage.INTAKE, Stage.INTAKE, digest, 1)]
    with pytest.raises(WorkflowIntegrityError):
        verify_workflow_replay(original, snapshots, events)
