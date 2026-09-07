# Colab — Multi-Agent Collaboration Platform

Production-grade multi-agent collaboration platform for quantitative product development.

## Architecture

- CEO / Project Lead — orchestration, decomposition, synthesis
- Quant Researcher — research and evidence
- Strategy / Quant Developer — strategy candidates and quantitative implementation
- Risk & Compliance Officer — independent risk gate
- Software Engineer / QA — implementation and validation

The platform uses structured, versioned workflow state and explicit stage transitions. Risk review is independent from strategy generation. Critical outputs require human approval.

## Phase 3 — Platform Productization

Phase 3 adds:

- FastAPI web/API interface with a responsive dashboard.
- Product workspaces with bounded concurrency and priority scheduling.
- Versioned, content-addressed artifact management with deterministic de-duplication.
- Provider-neutral tool registry with an explicit allow-list; no live trading/execution tool is registered.
- Versioned knowledge documents with deterministic lexical search and an interface suitable for a future vector backend.
- PostgreSQL schema for durable workspace, artifact, knowledge, and tool metadata with RLS enabled and browser roles denied until identity-aware policies exist.

## Development

Python 3.12+

```bash
python -m pip install -e '.[dev]'
pytest --cov=colab --cov-report=term-missing --cov-fail-under=90
```

Run the web interface locally with:

```bash
uvicorn colab.api:app --reload
```

The dashboard is served at `/`, the API under `/api`, and `/health` is suitable for deployment health checks.

## Safety boundary

This platform is for research and product development. It does **not** contain a live trading/exchange execution path. Quantitative execution remains subject to the Phase 2 orchestration, independent risk policy, validation, and human-review gates. The quantitative sandbox is a trusted-code boundary, not a hostile-tenant isolation boundary.

For production persistence, use the platform repository with `COLAB_DATABASE_DSN` and apply the Supabase migrations. Browser/API authorization must be added before exposing persisted records to authenticated tenants.
