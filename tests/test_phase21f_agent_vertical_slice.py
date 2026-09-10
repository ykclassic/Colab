from hashlib import sha256
from uuid import uuid4

import pytest

from colab.agent_vertical_slice import (
    AgentGovernanceError,
    AgentPlatformStore,
    AgentPlatformVerticalSlice,
    AgentVersion,
)


def test_register_hashes_config_and_uses_supplied_agent_id() -> None:
    agent_id = uuid4()
    platform = AgentPlatformVerticalSlice()
    version = platform.register(agent_id, {"model": "test", "temperature": 0})
    assert version.agent_id == agent_id
    assert version.version == 1
    assert version.status == "DRAFT"
    assert len(version.config_hash) == 64
    assert platform.store.versions[(agent_id, 1)] == version


def test_evaluate_validates_registration_score_and_evidence() -> None:
    platform = AgentPlatformVerticalSlice()
    version = platform.register(config={"model": "test"})
    evaluation = platform.evaluate(
        version, task_type="research", benchmark_id="bench-1", score=0.8,
        evidence=["source-a", "source-b"],
    )
    assert evaluation.agent_id == version.agent_id
    assert evaluation.version == 1
    assert evaluation.task_type == "research"
    assert evaluation.score == 0.8
    assert evaluation.evidence == ("source-a", "source-b")
    assert platform.store.list_evaluations(version.agent_id) == [evaluation]
    assert platform.store.list_evaluations(version.agent_id, "other") == []
    with pytest.raises(ValueError, match="between 0 and 1"):
        platform.evaluate(version, task_type="research", benchmark_id="b", score=1.1)
    with pytest.raises(ValueError, match="between 0 and 1"):
        platform.evaluate(version, task_type="research", benchmark_id="b", score=-0.1)
    with pytest.raises(AgentGovernanceError, match="not registered"):
        platform.evaluate(
            AgentVersion(uuid4(), 1, "hash"), task_type="research", benchmark_id="b", score=0.5
        )


def test_record_performance_builds_window_and_counts_prior() -> None:
    platform = AgentPlatformVerticalSlice()
    version = platform.register(config={})
    platform.evaluate(version, task_type="research", benchmark_id="b", score=0.6)
    second = platform.evaluate(version, task_type="research", benchmark_id="b", score=0.7)
    performance = platform.record_performance(second, window="rolling-7d")
    assert performance.agent_id == version.agent_id
    assert performance.score == 0.7
    assert performance.sample_count == 2
    assert len(performance.window_hash) == 64
    assert platform.store.performance == [performance]


def test_arbitration_requires_matching_evidence() -> None:
    platform = AgentPlatformVerticalSlice()
    first_version = platform.register(uuid4(), {})
    second_version = platform.register(uuid4(), {})
    first = platform.evaluate(
        first_version, task_type="research", benchmark_id="b", score=0.8, evidence=["a"]
    )
    second = platform.evaluate(
        second_version, task_type="research", benchmark_id="b", score=0.7, evidence=["b"]
    )
    decision = platform.arbitrate([second, first], task_type="research")
    assert decision.winner_agent_id == first.agent_id
    assert decision.winner_version == 1
    assert decision.confidence == pytest.approx(0.8 / 1.5)
    assert decision.evidence == (first.evaluation_id,)
    assert len(decision.decision_hash) == 64
    assert platform.store.decisions == [decision]
    no_evidence = platform.evaluate(
        first_version, task_type="research", benchmark_id="b", score=0.99, evidence=[]
    )
    with pytest.raises(AgentGovernanceError, match="task-matched evaluations with evidence"):
        platform.arbitrate([no_evidence], task_type="research")
    with pytest.raises(AgentGovernanceError, match="task-matched evaluations with evidence"):
        platform.arbitrate([first], task_type="unmatched")


def test_arbitration_tie_break_is_deterministic() -> None:
    platform = AgentPlatformVerticalSlice()
    low_id = uuid4()
    high_id = uuid4()
    if str(low_id) > str(high_id):
        low_id, high_id = high_id, low_id
    low = platform.register(low_id, {})
    high = platform.register(high_id, {})
    low_eval = platform.evaluate(
        low, task_type="research", benchmark_id="b", score=0.5, evidence=["l"]
    )
    high_eval = platform.evaluate(
        high, task_type="research", benchmark_id="b", score=0.5, evidence=["h"]
    )
    decision = platform.arbitrate([high_eval, low_eval], task_type="research")
    assert decision.winner_agent_id == low_id


def test_memory_lifecycle_and_validation() -> None:
    platform = AgentPlatformVerticalSlice()
    agent_id = uuid4()
    evidence_id = uuid4()
    memory = platform.write_memory(
        agent_id, task_type="research", content="validated finding", evidence_ids=(evidence_id,)
    )
    assert memory.agent_id == agent_id
    assert memory.active is True
    assert memory.content_hash == sha256(b"validated finding").hexdigest()
    assert platform.store.memories[memory.memory_id] == memory
    deactivated = platform.deactivate_memory(memory.memory_id)
    assert deactivated.active is False
    assert deactivated.memory_id == memory.memory_id
    assert platform.store.memories[memory.memory_id] == deactivated
    with pytest.raises(AgentGovernanceError, match="content and evidence"):
        platform.write_memory(agent_id, task_type="research", content="   ", evidence_ids=(evidence_id,))
    with pytest.raises(AgentGovernanceError, match="content and evidence"):
        platform.write_memory(agent_id, task_type="research", content="content", evidence_ids=())
    with pytest.raises(KeyError):
        platform.deactivate_memory(uuid4())


def test_cost_validates_non_negative_inputs() -> None:
    platform = AgentPlatformVerticalSlice()
    version = platform.register(config={})
    record = platform.cost(
        version, task_type="research", input_tokens=100, output_tokens=50, unit_cost=0.001
    )
    assert record.input_tokens == 100
    assert record.output_tokens == 50
    assert record.cost == pytest.approx(0.15)
    assert platform.store.costs == [record]
    with pytest.raises(ValueError, match="non-negative"):
        platform.cost(version, task_type="research", input_tokens=-1, output_tokens=1)
    with pytest.raises(ValueError, match="non-negative"):
        platform.cost(version, task_type="research", input_tokens=1, output_tokens=-1)
    with pytest.raises(ValueError, match="non-negative"):
        platform.cost(version, task_type="research", input_tokens=1, output_tokens=1, unit_cost=-0.1)


def test_run_completes_full_governed_lifecycle_and_promotes_version() -> None:
    platform = AgentPlatformVerticalSlice(AgentPlatformStore())
    result = platform.run(
        config={"model": "test"}, task_type="research", benchmark_id="bench-1", score=0.9,
        evidence=["source"], baseline_score=0.8, memory_content="validated result",
        input_tokens=100, output_tokens=50,
    )
    assert result.agent_version.status == "PROMOTED"
    assert result.evaluation.benchmark_id == "bench-1"
    assert result.performance.sample_count == 1
    assert result.arbitration.winner_agent_id == result.agent_version.agent_id
    assert result.memory.active is True
    assert result.cost.cost == pytest.approx(0.0015)
    assert result.regression is False
    assert len(result.governance_hash) == 64
    assert platform.store.versions[(result.agent_version.agent_id, 1)].status == "PROMOTED"


def test_run_rejects_regression_after_recording_evidence() -> None:
    platform = AgentPlatformVerticalSlice()
    with pytest.raises(AgentGovernanceError, match="regression detected"):
        platform.run(
            config={}, task_type="research", benchmark_id="bench-1", score=0.4,
            evidence=["source"], baseline_score=0.5,
        )
    assert len(platform.store.evaluations) == 1
    assert len(platform.store.performance) == 1
    assert len(platform.store.decisions) == 1
    assert len(platform.store.memories) == 1
    assert len(platform.store.costs) == 1


def test_hashing_and_empty_defaults_are_exercised() -> None:
    platform = AgentPlatformVerticalSlice()
    version = platform.register()
    evaluation = platform.evaluate(version, task_type="research", benchmark_id="b", score=0)
    performance = platform.record_performance(evaluation)
    assert version.agent_id is not None
    assert evaluation.evidence == ()
    assert performance.sample_count == 1
