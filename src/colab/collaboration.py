"""Advanced multi-agent collaboration primitives."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .agents import Agent, AgentResult
from .contracts import AgentRole, Artifact, WorkflowState


class CollaborationError(RuntimeError):
    """Raised when collaboration invariants are violated."""


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageType(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    CHALLENGE = "challenge"
    CONSENSUS = "consensus"
    HANDOFF = "handoff"


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID = Field(default_factory=uuid4)
    role: AgentRole
    objective: str = Field(min_length=1, max_length=10000)
    stage: str = Field(min_length=1, max_length=100)
    priority: int = Field(default=100, ge=0, le=1000)
    dependencies: tuple[UUID, ...] = ()
    budget: int = Field(default=1, ge=1, le=1000)


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    role: AgentRole
    status: TaskStatus
    artifacts: tuple[Artifact, ...] = ()
    notes: tuple[str, ...] = ()
    error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID = Field(default_factory=uuid4)
    sender: AgentRole
    recipient: AgentRole
    message_type: MessageType
    task_id: UUID
    content: str = Field(min_length=1, max_length=20000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflict_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    positions: dict[AgentRole, str]
    reason: str = Field(min_length=1, max_length=5000)


class ArbitrationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflict_id: UUID
    winner: AgentRole
    rationale: str = Field(min_length=1, max_length=10000)
    arbitrator: AgentRole = AgentRole.CEO
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CollaborationResult:
    results: tuple[TaskResult, ...]
    messages: tuple[AgentMessage, ...]
    decisions: tuple[ArbitrationDecision, ...]


class CollaborationEngine:
    """Execute independent agent tasks concurrently and arbitrate conflicts."""

    def __init__(self, agents: Mapping[AgentRole, Agent], max_workers: int = 4) -> None:
        if not agents:
            raise ValueError("at least one agent is required")
        if max_workers < 1 or max_workers > 32:
            raise ValueError("max_workers must be between 1 and 32")
        self._agents = dict(agents)
        self._max_workers = max_workers
        self._lock = Lock()
        self._messages: list[AgentMessage] = []

    def delegate(
        self,
        role: AgentRole,
        objective: str,
        stage: str,
        *,
        priority: int = 100,
        dependencies: tuple[UUID, ...] = (),
        budget: int = 1,
    ) -> TaskSpec:
        if role not in self._agents:
            raise CollaborationError(f"no agent registered for role {role.value}")
        return TaskSpec(
            role=role, objective=objective, stage=stage, priority=priority,
            dependencies=dependencies, budget=budget,
        )

    @staticmethod
    def _ready(tasks: list[TaskSpec], completed: set[UUID]) -> list[TaskSpec]:
        return sorted(
            (
                task for task in tasks
                if task.task_id not in completed
                and all(dep in completed for dep in task.dependencies)
            ),
            key=lambda task: (-task.priority, str(task.task_id)),
        )

    def _run_one(self, task: TaskSpec, state: WorkflowState) -> TaskResult:
        agent = self._agents[task.role]
        started = datetime.now(UTC)
        snapshot = state.model_copy(deep=True)
        try:
            result: AgentResult = agent.run(snapshot, task.objective)
            return TaskResult(
                task_id=task.task_id, role=task.role, status=TaskStatus.SUCCEEDED,
                artifacts=result.artifacts, notes=result.notes,
                started_at=started, completed_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001 - isolate agent failures per task
            return TaskResult(
                task_id=task.task_id, role=task.role, status=TaskStatus.FAILED,
                error=str(exc), started_at=started, completed_at=datetime.now(UTC),
            )

    def execute_parallel(self, tasks: list[TaskSpec], state: WorkflowState) -> tuple[TaskResult, ...]:
        """Run dependency-ready tasks in parallel, advancing in deterministic waves."""
        by_id = {task.task_id: task for task in tasks}
        if len(by_id) != len(tasks):
            raise CollaborationError("task IDs must be unique")
        unknown = {dep for task in tasks for dep in task.dependencies if dep not in by_id}
        if unknown:
            raise CollaborationError("task dependency references an unknown task")
        completed: set[UUID] = set()
        results: list[TaskResult] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            while len(completed) < len(tasks):
                ready = self._ready(tasks, completed)
                if not ready:
                    raise CollaborationError("task dependency graph contains a cycle")
                futures = {pool.submit(self._run_one, task, state): task for task in ready}
                wave: list[TaskResult] = []
                for future in as_completed(futures):
                    wave.append(future.result())
                wave.sort(key=lambda result: (-by_id[result.task_id].priority, str(result.task_id)))
                results.extend(wave)
                completed.update(result.task_id for result in wave)
                failed = [result for result in wave if result.status == TaskStatus.FAILED]
                if failed:
                    failed_ids = {result.task_id for result in failed}
                    blocked = [
                        task for task in tasks
                        if any(dep in failed_ids for dep in task.dependencies)
                    ]
                    if blocked:
                        raise CollaborationError("dependency failed; downstream task cannot execute")
        return tuple(results)

    def send(
        self,
        sender: AgentRole,
        recipient: AgentRole,
        task_id: UUID,
        content: str,
        message_type: MessageType = MessageType.REQUEST,
        conversation_id: UUID | None = None,
    ) -> AgentMessage:
        if sender not in self._agents or recipient not in self._agents:
            raise CollaborationError("both message participants must be registered agents")
        message = AgentMessage(
            sender=sender, recipient=recipient, task_id=task_id, content=content,
            message_type=message_type, conversation_id=conversation_id or uuid4(),
        )
        with self._lock:
            self._messages.append(message)
        return message

    def messages(self) -> tuple[AgentMessage, ...]:
        with self._lock:
            return tuple(self._messages)

    def detect_conflict(
        self, task_id: UUID, positions: dict[AgentRole, str], reason: str
    ) -> Conflict:
        if len(positions) < 2:
            raise CollaborationError("a conflict requires at least two agent positions")
        if not all(role in self._agents for role in positions):
            raise CollaborationError("conflict positions contain an unregistered agent")
        return Conflict(task_id=task_id, positions=positions, reason=reason)

    def arbitrate(
        self,
        conflict: Conflict,
        scorer: Callable[[AgentRole, str], float] | None = None,
    ) -> ArbitrationDecision:
        """Choose the highest-scoring position deterministically; CEO arbitrates."""
        score = scorer or (lambda _role, position: float(len(position.strip())))
        ranked = sorted(
            ((score(role, position), role) for role, position in conflict.positions.items()),
            key=lambda item: (-item[0], item[1].value),
        )
        if not ranked:
            raise CollaborationError("cannot arbitrate an empty conflict")
        winner_score, winner = ranked[0]
        total = sum(max(item[0], 0.0) for item in ranked)
        confidence = 1.0 if len(ranked) == 1 else (winner_score / total if total > 0 else 0.5)
        return ArbitrationDecision(
            conflict_id=conflict.conflict_id, winner=winner,
            rationale=f"Selected {winner.value} by deterministic arbitration score.",
            confidence=min(max(confidence, 0.0), 1.0),
        )

    def collaborate(self, tasks: list[TaskSpec], state: WorkflowState) -> CollaborationResult:
        results = self.execute_parallel(tasks, state)
        decisions: list[ArbitrationDecision] = []
        successful = [result for result in results if result.status == TaskStatus.SUCCEEDED]
        if len(successful) > 1:
            positions = {
                result.role: str(result.artifacts[0].content) if result.artifacts else "no artifact"
                for result in successful
            }
            if len(set(positions.values())) > 1:
                conflict = self.detect_conflict(
                    successful[0].task_id, positions, "parallel outputs differ"
                )
                decisions.append(self.arbitrate(conflict))
        return CollaborationResult(
            results=results, messages=self.messages(), decisions=tuple(decisions)
        )
