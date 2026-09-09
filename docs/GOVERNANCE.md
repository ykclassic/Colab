# Colab Governance

## Purpose

Governance prevents AI-generated research or strategies from becoming consequential decisions without validation and appropriate authorization.

## Principles

1. AI may propose.
2. Software may validate.
3. Risk may challenge.
4. Humans retain final authority over consequential decisions.

## Approval Lifecycle

```text
Draft → Submitted → Risk Review → Risk Approved → Human Review → Approved / Rejected
```

## Approval Binding

Approval records should identify the workspace, workflow, artifact, artifact version, artifact digest, strategy version, risk assessment, risk digest, requester, decision maker, decision and rationale.

A material governed-artifact change should invalidate the associated approval.

## Strategy Promotion

```text
Research → Candidate → Staging → Production
```

Suggested readiness thresholds are Candidate 70, Staging 80 and Production 90. A score alone is never sufficient for promotion; risk, operational, validation, reproducibility and governance gates must also pass.

## Human Review

Reviewers should inspect objective, evidence, methodology, assumptions, datasets, strategy, parameters, validation, risk and reproducibility information before approving consequential outcomes.

## Anti-Patterns

Never use:

```text
LLM → Production
Backtest profitable → Production
Agent generated → Automatically approved
```

Use:

```text
Generate → Validate → Risk Review → Human Review → Governed Promotion
```
