# Phase 21I — Complete Product / E2E Verification

Phase 21I verifies the actual user-facing product journey rather than isolated backend capabilities.

## Product journey

The Command Center is the intent-to-workflow entry point:

`User goal → Command Center → Research → Quant → Agents → Governance → Artifact / Report`

The Command Center deterministically maps a goal to an explainable workflow plan, shows the stages, and creates a workspace carrying the goal and idempotency key. Dedicated product pages remain available for users who already know the stage they want.

## E2E verification

The frontend CI job builds the production Next.js application, installs Chromium, and runs Playwright browser tests against the production server. The tests verify that:

1. A quantitative goal is classified as the Quant Validation workflow.
2. The recommended workflow and all planned stages are visible.
3. Research, Quant, Agents, Governance, and Artifacts / Reports links exist with their intended destinations.

## Boundary

The planner is deterministic and explainable. It does not execute trades or bypass governance. Full autonomous execution of every planned stage remains dependent on the existing backend workflow and job handlers.
