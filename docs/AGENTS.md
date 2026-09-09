# Colab Agent Platform

## Philosophy

Colab uses specialized agents with explicit responsibilities rather than one unrestricted autonomous agent.

Each agent should have a role, responsibility, task contract, approved tools, output schema and evaluation criteria.

## Roles

### CEO / Project Lead

Goal definition, decomposition, orchestration and synthesis.

### Quant Researcher

Quantitative research, evidence gathering, experiment design and analysis.

### Strategy Developer

Strategy specification, candidate development and quantitative implementation.

### Risk & Compliance

Independent challenge of assumptions, risk assessment and readiness review.

### Software Engineer / QA

Implementation, testing, validation and defect identification.

## Agent Contract

```text
Agent → Task Contract → Structured Input → Approved Tools
→ Structured Output → Evidence → Artifact
```

Structured outputs should expose fields such as task ID, agent, decision, confidence, evidence, assumptions, risks, artifacts and citations.

## Evaluation

Measure correctness, evidence quality, citation accuracy, hallucination, risk detection, latency, token usage, cost and human override/revision rate.

## Arbitration

Agent disagreement should be resolved using evidence quality, source authority, task-specific historical performance, calibration, corroboration and contradiction detection. Response length is not a valid correctness proxy.

## Memory

Distinguish working, episodic, semantic and procedural memory. Memory should have ownership, scope, provenance, confidence and appropriate retention rules.

## Safety

Agents must not bypass governance, approve their own work, modify governance rules, trade directly, access unrestricted credentials or access arbitrary networks.
