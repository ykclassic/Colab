# ADR 0004: No Direct Trading Capability for Agents

## Status

Accepted

## Decision

AI agents must not directly execute trades or financial transactions. Any future execution capability must exist behind an isolated execution boundary.

## Required Architecture

```text
Strategy → Independent Risk → Human Approval → Execution Gateway
```

## Rationale

This limits credential exposure, accidental execution, prompt-injection impact, model-failure impact and governance bypasses.

## Consequence

Colab cannot currently be considered an autonomous trading system. This is an intentional architectural constraint.
