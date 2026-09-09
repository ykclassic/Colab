import pytest

from colab.contracts import Decision, RiskAssessment, Stage, WorkflowState
from colab.orchestrator import Orchestrator, WorkflowError
from colab.workflow_integrity import (
    WorkflowIntegrityError,
    state_hash,
    validate_event_chain,
    validate_stage_transition,
)


def test_state_hash_is_deterministic_and_changes_with_state() -> None:
    state = WorkflowState(product_goal="integrity")
    first = state_hash(state)
    second = state_hash(WorkflowState.model_validate(state.model_dump()))
    assert first == second
    state.product_goal = "tampered"
    assert state_hash(state) != first


def test_event_chain_requires_contiguous_sequences_and_hash_links() -> None:
    events = [
        {
            "sequence_no": 1, "from_stage": "intake", "to_stage": "intake",
            "previous_state_hash": None, "resulting_state_hash": "a" * 64,
        },
        {
            "sequence_no": 2, "from_stage": "intake", "to_stage": "decomposition",
            "previous_state_hash": "a" * 64, "resulting_state_hash": "b" * 64,
        },
    ]
    validate_event_chain(events)
    events[1]["previous_state_hash"] = "c" * 64
    with pytest.raises(WorkflowIntegrityError, match="previous state hash"):
        validate_event_chain(events)


def test_event_chain_rejects_stage_skipping() -> None:
    events = [
        {
            "sequence_no": 1, "from_stage": "intake", "to_stage": "intake",
            "previous_state_hash": None, "resulting_state_hash": "a" * 64,
        },
        {
            "sequence_no": 2, "from_stage": "intake", "to_stage": "research",
            "previous_state_hash": "a" * 64, "resulting_state_hash": "b" * 64,
        },
    ]
    with pytest.raises(WorkflowIntegrityError, match="skips a stage"):
        validate_event_chain(events)


def test_direct_state_mutation_cannot_skip_stages_when_persisting() -> None:
    state = WorkflowState(product_goal="integrity", current_stage=Stage.RESEARCH)
    with pytest.raises(WorkflowIntegrityError, match="invalid workflow transition"):
        validate_stage_transition(Stage.INTAKE, state.current_stage, state)


def test_risk_and_human_gates_remain_required() -> None:
    state = WorkflowState(product_goal="integrity", current_stage=Stage.RISK)
    with pytest.raises(WorkflowIntegrityError, match="approved risk assessment"):
        validate_stage_transition(Stage.RISK, Stage.IMPLEMENTATION, state)
    state.risk_assessments.append(RiskAssessment(decision=Decision.APPROVE))
    validate_stage_transition(Stage.RISK, Stage.IMPLEMENTATION, state)

    state.current_stage = Stage.HUMAN_REVIEW
    with pytest.raises(WorkflowIntegrityError, match="human approval"):
        validate_stage_transition(Stage.HUMAN_REVIEW, Stage.COMPLETE, state)


def test_orchestrator_still_enforces_no_stage_skipping() -> None:
    state = WorkflowState(product_goal="integrity")
    state.current_stage = Stage.RESEARCH
    with pytest.raises(WorkflowError):
        Orchestrator().advance(state)
