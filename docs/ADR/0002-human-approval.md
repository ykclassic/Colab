# ADR 0002: Human Approval for Consequential Decisions

## Status

Accepted

## Decision

AI agents may generate recommendations and artifacts, but consequential decisions require appropriate validation and, where designated, human approval.

## Rationale

LLM output is probabilistic and must not automatically become authority. The system therefore separates generation, validation, risk assessment and approval.

## Consequences

The platform may be slower than a fully autonomous agent. This is intentional: safety and accountability take precedence over maximum autonomy.
