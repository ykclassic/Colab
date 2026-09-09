# Colab Architecture

## 1. Objective

Colab is designed as a governed AI platform rather than a collection of unrestricted chat agents. The architecture prioritizes safety, determinism, explainability, reproducibility, authorization, persistence, auditability and testability.

## 2. High-Level Architecture

```text
Next.js UI
    ↓
FastAPI API Layer
    ↓
┌──────────────┬──────────────┬──────────────┐
│ Workflow     │ Research     │ Quant        │
│ Services     │ Services     │ Services     │
└──────────────┴──────────────┴──────────────┘
                    ↓
          Governance / Risk
                    ↓
          Workflow Integrity
                    ↓
     Agents / Persistence / Operations
                    ↓
          PostgreSQL + pgvector
```

## 3. Workflow Domain

Responsible for stage transitions, checkpoints, events, state hashing, replay and transition validation.

The workflow engine must reject illegal transitions and enforce required governance gates.

## 4. Agent Domain

```text
Agent → Task Contract → Structured Input → Approved Tools
→ Structured Output → Evidence → Artifact
```

Agents have roles, versions, evaluation records and performance history.

## 5. Research Domain

```text
Source → Ingestion → Extraction → Normalization → Deduplication
→ Chunking → Embedding → Hybrid Retrieval → Reranking
→ Evidence Set → Synthesis → Citation Validation → Artifact
```

Provenance and content identity should survive through the pipeline.

## 6. Quantitative Domain

```text
Dataset Registry → Data Quality → Features → Strategy Registry
→ Backtest → Parameter Search → Walk Forward → OOS
→ Stress Testing → Monte Carlo → Robustness → Risk → Report
```

## 7. Governance Domain

Governance binds workflows, artifacts, strategy versions, datasets and risk assessments to approval and promotion decisions. Material artifact changes should invalidate prior approvals.

## 8. Persistence

PostgreSQL is the production system of record. Important domains include workflows, workflow events, agents, agent evaluations, research, datasets, strategies, experiments, risk assessments, approvals, artifacts and operational records.

## 9. Security Architecture

```text
Authentication
    ↓
Principal
    ↓
Workspace Membership
    ↓
Role
    ↓
Permission
    ↓
Resource Authorization
    ↓
Database RLS
```

RLS is defense-in-depth and must not replace API-layer authorization.

## 10. External Integrations

External access must pass through a controlled gateway enforcing HTTPS, host/path allow-lists, timeouts, response-size limits, server-side secrets and audit logging. Agents must not receive unrestricted network access.

## 11. Recommended Runtime Evolution

Long-running AI, research and quantitative workloads should progressively move toward:

```text
API → Command → Event → Queue → Worker → Result Event → Workflow Engine
```

This improves recovery, scalability, backpressure and operational control.

## 12. Architectural Rule

Generation, validation, approval and execution are separate authorities:

```text
Generation ≠ Validation ≠ Approval ≠ Execution
```

No AI-generated result should acquire consequential authority merely because an LLM produced it.
