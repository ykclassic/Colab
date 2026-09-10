# Phase 21I — Complete Product / E2E Verification

Phase 21I verifies the product as a user-facing journey rather than a collection of isolated APIs.

## Product journey

`Command Center → Research → Quant → Agents → Governance → Artifact / Report`

The Command Center now accepts a natural-language product goal, deterministically recommends a workflow, displays the proposed stages, and creates a workspace carrying the original goal as the execution context. The planner is deliberately explainable and does not execute trades or bypass governance.

## Verification coverage

- Command Center renders as the primary product entry point.
- A realistic research/quant goal produces a visible workflow plan.
- The recommended stages are rendered to the user.
- Product surfaces expose direct navigation to Research, Quant, Agents, Governance and Artifacts / Reports.
- Starting a workflow creates a workspace using the goal and idempotency key, then routes the user into the workspace surface.
- Existing backend CI remains unchanged for Python lint, type checking, coverage and tests.
- Frontend CI now builds the application and runs Playwright browser smoke tests against a production Next.js server.

## Important boundary

This phase establishes the product-level routing and E2E verification boundary. The workflow planner is deterministic; full autonomous execution of every stage still depends on the corresponding backend workflow handlers and durable job orchestration. No live trading or execution capability is introduced.
