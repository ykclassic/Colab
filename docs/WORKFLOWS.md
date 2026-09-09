# Colab Workflows

## Canonical Stages

```text
INTAKE
DECOMPOSITION
RESEARCH
STRATEGY
RISK
IMPLEMENTATION
VALIDATION
SYNTHESIS
HUMAN_REVIEW
COMPLETE
```

A governed rejection path is also supported.

## Responsibilities

| Stage | Responsibility |
|---|---|
| Intake | Define the problem |
| Decomposition | Break the problem into tasks |
| Research | Gather evidence |
| Strategy | Develop candidates |
| Risk | Independently assess risk |
| Implementation | Build and test |
| Validation | Verify correctness |
| Synthesis | Integrate results |
| Human Review | Obtain required human decision |
| Complete | Finalize the governed result |

## Integrity

Workflow transitions are validated. Integrity metadata includes sequence information and chained state hashes that allow event history to be checked and replayed.

## Governance Gates

The workflow must not bypass required risk review before implementation or required human approval before completion.

## Recovery

Persisted workflows should support checkpointing, replay and recovery. Long-running work should progressively move to durable workers and queues rather than relying only on synchronous HTTP requests.
