"""Durable workflow/governance state-machine verification primitives."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection

from .contracts import Stage, WorkflowState
from .security import AuthorizationError, Permission, Principal, membership_role, require_permission
from .workflow_integrity import WorkflowIntegrityError, state_hash, validate_event_chain


class GovernanceState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    RISK_REVIEW = "risk_review"
    RISK_APPROVED = "risk_approved"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class GovernanceStateError(ValueError):
    """Raised when a governance transition violates the state machine."""


@dataclass(frozen=True)
class GovernanceEvent:
    event_id: UUID
    approval_id: UUID
    from_state: GovernanceState | None
    to_state: GovernanceState
    actor: str
    occurred_at: datetime
    governed_input_digest: str
    previous_event_hash: str | None
    event_hash: str
    reason: str = ""


@dataclass(frozen=True)
class ApprovalBinding:
    workspace_id: UUID
    workflow_id: UUID
    strategy_version_id: UUID
    artifact_digest: str
    risk_assessment_digest: str
    governed_input_digest: str


class DurableGovernanceStateMachine:
    """In-memory deterministic model used to verify durable DB invariants."""

    _TRANSITIONS: dict[GovernanceState | None, frozenset[GovernanceState]] = {
        None: frozenset({GovernanceState.DRAFT}),
        GovernanceState.DRAFT: frozenset({GovernanceState.SUBMITTED, GovernanceState.REJECTED, GovernanceState.SUPERSEDED}),
        GovernanceState.SUBMITTED: frozenset({GovernanceState.RISK_REVIEW, GovernanceState.REJECTED, GovernanceState.SUPERSEDED, GovernanceState.EXPIRED}),
        GovernanceState.RISK_REVIEW: frozenset({GovernanceState.RISK_APPROVED, GovernanceState.REJECTED, GovernanceState.SUPERSEDED}),
        GovernanceState.RISK_APPROVED: frozenset({GovernanceState.HUMAN_REVIEW, GovernanceState.REJECTED, GovernanceState.INVALIDATED, GovernanceState.SUPERSEDED, GovernanceState.EXPIRED}),
        GovernanceState.HUMAN_REVIEW: frozenset({GovernanceState.APPROVED, GovernanceState.REJECTED, GovernanceState.INVALIDATED, GovernanceState.SUPERSEDED, GovernanceState.EXPIRED}),
        GovernanceState.APPROVED: frozenset({GovernanceState.PROMOTED, GovernanceState.INVALIDATED, GovernanceState.SUPERSEDED, GovernanceState.EXPIRED}),
        GovernanceState.PROMOTED: frozenset(),
        GovernanceState.REJECTED: frozenset(),
        GovernanceState.INVALIDATED: frozenset(),
        GovernanceState.SUPERSEDED: frozenset(),
        GovernanceState.EXPIRED: frozenset(),
    }

    def __init__(self, approval_id: UUID | None = None, binding: ApprovalBinding | None = None) -> None:
        self.approval_id = approval_id or uuid4()
        self.binding = binding
        self._state: GovernanceState | None = None
        self._events: list[GovernanceEvent] = []
        self._expires_at: datetime | None = None

    @property
    def state(self) -> GovernanceState | None:
        return self._state

    @property
    def events(self) -> tuple[GovernanceEvent, ...]:
        return tuple(self._events)

    @property
    def current_input_digest(self) -> str:
        return self.binding.governed_input_digest if self.binding else ""

    def transition(self, target: GovernanceState, actor: str, reason: str = "", *, now: datetime | None = None) -> GovernanceEvent:
        if target not in self._TRANSITIONS[self._state]:
            source = self._state.value if self._state else "none"
            raise GovernanceStateError(f"invalid governance transition: {source} -> {target.value}")
        if not actor.strip():
            raise GovernanceStateError("governance transition requires an actor")
        timestamp = now or datetime.now(UTC)
        previous_hash = self._events[-1].event_hash if self._events else None
        payload = f"{self.approval_id}|{self._state}|{target}|{actor}|{timestamp.isoformat()}|{self.current_input_digest}|{previous_hash}|{reason}"
        event_hash = sha256(payload.encode("utf-8")).hexdigest()
        event = GovernanceEvent(self.approval_id, self.approval_id, self._state, target, actor, timestamp,
                                self.current_input_digest, previous_hash, event_hash, reason.strip())
        self._events.append(event)
        self._state = target
        return event

    def set_expiry(self, expires_at: datetime) -> None:
        if expires_at.tzinfo is None:
            raise GovernanceStateError("expiry must be timezone-aware")
        self._expires_at = expires_at

    def expire_if_due(self, *, now: datetime | None = None, actor: str = "governance-system") -> bool:
        terminal = {GovernanceState.PROMOTED, GovernanceState.REJECTED, GovernanceState.INVALIDATED, GovernanceState.SUPERSEDED, GovernanceState.EXPIRED}
        if self._expires_at is None or self._state in {None, *terminal}:
            return False
        timestamp = now or datetime.now(UTC)
        if timestamp < self._expires_at:
            return False
        self.transition(GovernanceState.EXPIRED, actor, "approval expired", now=timestamp)
        return True

    def invalidate_for_input_change(self, new_input_digest: str, reason: str, *, actor: str = "governance-system", now: datetime | None = None) -> GovernanceEvent:
        if self._state not in {GovernanceState.RISK_APPROVED, GovernanceState.HUMAN_REVIEW, GovernanceState.APPROVED}:
            raise GovernanceStateError("only review/approved governance can be invalidated")
        if not reason.strip():
            raise GovernanceStateError("invalidation reason is required")
        if new_input_digest == self.current_input_digest:
            raise GovernanceStateError("governed input digest did not change")
        return self.transition(GovernanceState.INVALIDATED, actor, reason, now=now)

    def supersede(self, reason: str, *, actor: str = "governance-system", now: datetime | None = None) -> GovernanceEvent:
        active = {GovernanceState.DRAFT, GovernanceState.SUBMITTED, GovernanceState.RISK_REVIEW, GovernanceState.RISK_APPROVED, GovernanceState.HUMAN_REVIEW, GovernanceState.APPROVED}
        if self._state not in active:
            raise GovernanceStateError("only active governance can be superseded")
        return self.transition(GovernanceState.SUPERSEDED, actor, reason, now=now)

    def verify_event_chain(self) -> None:
        previous: str | None = None
        for index, event in enumerate(self._events, 1):
            if event.previous_event_hash != previous:
                raise WorkflowIntegrityError(f"governance event {index} has invalid previous hash")
            payload = f"{event.approval_id}|{event.from_state}|{event.to_state}|{event.actor}|{event.occurred_at.isoformat()}|{event.governed_input_digest}|{event.previous_event_hash}|{event.reason}"
            if event.event_hash != sha256(payload.encode("utf-8")).hexdigest():
                raise WorkflowIntegrityError(f"governance event {index} hash mismatch")
            previous = event.event_hash
        if self._events and self._events[-1].to_state != self._state:
            raise WorkflowIntegrityError("governance terminal state does not match event chain")


def require_workflow_replay_access(principal: Principal, workspace_id: UUID, connection_factory: Callable[[], Connection[Any]]) -> None:
    """Require audit permission and workspace membership before replay/restore."""
    require_permission(principal, Permission.AUDIT_READ)
    if membership_role(connection_factory, workspace_id, principal.user_id) is None:
        raise AuthorizationError("principal is not a member of the workflow workspace")


def verify_workflow_replay(original: WorkflowState, snapshots: list[dict[str, Any]], events: list[dict[str, Any]]) -> WorkflowState:
    """Verify durable snapshots/events and return the final replayed state."""
    if not snapshots or not events:
        raise WorkflowIntegrityError("replay requires at least one checkpoint and event")
    validate_event_chain(events)
    by_version = {int(item["version"]): item for item in snapshots}
    for event in events:
        snapshot = by_version.get(int(event["snapshot_version"]))
        if snapshot is None:
            raise WorkflowIntegrityError("event references missing checkpoint")
        state = WorkflowState.model_validate(snapshot["state"])
        if snapshot.get("state_hash") != state_hash(state):
            raise WorkflowIntegrityError("checkpoint state hash mismatch")
        if snapshot["state_hash"] != event["resulting_state_hash"]:
            raise WorkflowIntegrityError("event/checkpoint hash mismatch")
        if state.workflow_id != original.workflow_id:
            raise WorkflowIntegrityError("replay crossed workflow identity")
    final_version = max(by_version)
    final_state = WorkflowState.model_validate(by_version[final_version]["state"])
    if final_state.workflow_id != original.workflow_id:
        raise WorkflowIntegrityError("replay final state belongs to another workflow")
    return final_state


def expiry_after(days: int, *, now: datetime | None = None) -> datetime:
    if days < 1:
        raise ValueError("expiry must be at least one day")
    return (now or datetime.now(UTC)) + timedelta(days=days)
