# Colab

## AI-Native Research, Quantitative Experimentation & Governed Collaboration Platform

Colab is a multi-agent platform for structured research, quantitative experimentation, strategy development, risk analysis, validation, and governed decision-making.

It combines specialized AI agents, deterministic workflow controls, evidence-backed research retrieval, quantitative research infrastructure, human approval, persistent artifacts, and reproducibility controls.

> **Current status:** Advanced development / emerging production platform.
>
> Colab is **not currently a live autonomous trading platform**. Trading and financial execution remain outside the current product boundary.

## What Colab Does

Colab separates complex work into specialized responsibilities rather than giving one unrestricted AI agent control of the entire process.

### Core roles

| Role | Responsibility |
|---|---|
| CEO / Project Lead | Goal definition, decomposition, orchestration and synthesis |
| Quant Researcher | Research, evidence gathering and quantitative analysis |
| Strategy Developer | Strategy design and implementation |
| Risk & Compliance | Independent risk assessment |
| Software Engineer / QA | Implementation, testing and validation |

## Governed Workflow

```text
INTAKE
  ↓
DECOMPOSITION
  ↓
RESEARCH
  ↓
STRATEGY
  ↓
RISK
  ↓
IMPLEMENTATION
  ↓
VALIDATION
  ↓
SYNTHESIS
  ↓
HUMAN REVIEW
  ↓
COMPLETE
```

Workflow integrity controls validate legal transitions and maintain chained state information for validation and replay.

## Major Capabilities

### Multi-Agent Collaboration

- Specialized agent roles
- Versioned agents
- Structured model outputs
- Evidence and citation fields
- Agent evaluation
- Performance and cost tracking
- Agent memory records
- Evidence-weighted arbitration

### Research Platform

- Source and document management
- Document versioning
- Extraction and normalization
- Chunking
- Embeddings
- Vector retrieval
- Lexical retrieval
- Hybrid retrieval
- Reciprocal-rank fusion
- Reranking
- Citation validation
- Provenance
- Reproducibility hashes

### Quantitative Research

- Dataset registration
- Strategy registry
- Experiments
- Backtesting
- Sharpe and Sortino ratios
- Volatility and drawdown
- Calmar ratio
- VaR and CVaR
- Win rate and profit factor
- Stress testing
- Monte Carlo analysis
- Robustness analysis
- Experiment hashing
- Durable persistence

### Governance

- Strategy versions
- Artifact versions
- Risk assessments
- Approval requests and decisions
- Readiness reports
- Release gates
- Promotion decisions
- Artifact and risk digests
- Reproducibility manifests

Governance records are designed to remain bound to the exact workspace, workflow, artifact, strategy version and risk assessment being evaluated.

### Security Foundation

- JWT-based authentication infrastructure
- Roles and permissions
- Workspace membership checks
- Endpoint authorization primitives
- Rate limiting
- Security headers
- Audit events
- Supabase/PostgreSQL RLS support

**Production requirement:** every workspace-scoped API endpoint must be verified to enforce authentication, authorization and tenant isolation before multi-tenant exposure.

## Persistence

PostgreSQL is the production system of record for durable platform state. Major persisted domains include workflows, checkpoints, governance, research, quantitative experiments, agents, artifacts and operational records.

Development environments may use deterministic in-memory services. Production deployments must use a configured PostgreSQL database.

## Safety Boundary

Colab deliberately does not provide unrestricted agent execution.

External integrations are constrained by:

- HTTPS-only transport
- host/path allow-lists
- timeout limits
- response-size limits
- server-side secret handling
- auditing
- restricted operations

Trading, order submission, withdrawals, transfers and unrestricted execution are outside the current integration boundary.

Any future execution architecture must remain separated:

```text
Strategy
   ↓
Independent Risk Engine
   ↓
Human Approval
   ↓
Isolated Execution Gateway
```

Agents must never receive exchange credentials or unrestricted financial execution authority.

## Technology Stack

### Backend

- Python 3.12+
- FastAPI
- Pydantic
- PostgreSQL
- Supabase
- LangGraph
- Provider-neutral model runtime

### Frontend

- Next.js
- React
- TypeScript

### Infrastructure

- PostgreSQL / Supabase
- GitHub Actions
- Vercel-compatible frontend deployment

## Local Development

### Backend

```bash
python -m pip install -e '.[dev]'
pytest --cov=colab --cov-report=term-missing --cov-fail-under=90
uvicorn colab.api:app --reload
```

The API is available at `http://localhost:8000`.

Health check:

```text
GET /health
```

Readiness check:

```text
GET /ready
```

### Frontend

Use the committed lockfile for reproducible installs:

```bash
npm ci
```

Then use the repository's configured development/build commands.

## Environment Configuration

Production persistence requires a secure PostgreSQL connection, for example:

```text
COLAB_ENV=production
COLAB_DATABASE_DSN=<postgresql-connection-string>
```

Additional configuration controls authentication, model providers, embeddings, rate limits, integrations and operational behavior.

Never commit credentials or secrets to Git.

## Development Principles

1. Safety before autonomy.
2. Human authority over consequential decisions.
3. Evidence before conclusions.
4. Deterministic workflows.
5. Reproducible research.
6. Explicit authorization.
7. Tenant isolation.
8. Version important state.
9. Persist governance decisions.
10. Never allow AI output to bypass a safety boundary.

## Current Limitations

Colab should not currently be represented as:

- a fully autonomous AI company
- a production autonomous trading platform
- an unrestricted agent execution platform
- a finished enterprise SaaS product

Remaining hardening includes complete API authorization coverage, tenant-isolation verification, production RLS validation, comprehensive end-to-end testing, frontend workflow completion, durable worker infrastructure, stronger quantitative validation, observability and deployment hardening.

## Documentation

| Document | Purpose |
|---|---|
| [Guide](docs/GUIDE.md) | User and developer introduction |
| [Architecture](docs/ARCHITECTURE.md) | System architecture and boundaries |
| [API](docs/API.md) | HTTP API conventions and endpoints |
| [Security](docs/SECURITY.md) | Authentication, authorization and tenant isolation |
| [Governance](docs/GOVERNANCE.md) | Risk, approval and release governance |
| [Research](docs/RESEARCH.md) | Research ingestion, retrieval and evidence |
| [Quant](docs/QUANT.md) | Quantitative research and validation |
| [Agents](docs/AGENTS.md) | Agent contracts and evaluation |
| [Workflows](docs/WORKFLOWS.md) | Workflow stages and integrity |
| [Operations](docs/OPERATIONS.md) | Jobs, reliability and observability |
| [Deployment](docs/DEPLOYMENT.md) | Deployment and production checks |
| [Testing](docs/TESTING.md) | Testing strategy |
| [Development](docs/DEVELOPMENT.md) | Local development |
| [Contributing](docs/CONTRIBUTING.md) | Contribution standards |
| [Roadmap](docs/ROADMAP.md) | Product and engineering roadmap |

## License

See the repository license file.
