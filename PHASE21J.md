# Phase 21J — Production-Readiness Certification

## Purpose

Phase 21J is the final engineering gate before calling Colab production-ready. It certifies the repository across security, tenant isolation, migrations, durable workflows, research, quant, agents, workers, observability, frontend E2E, and regression coverage.

The certification deliberately distinguishes **repository/CI evidence** from **environment evidence**. A green CI run cannot prove that a particular production PostgreSQL/Supabase project, authentication configuration, secrets configuration, backups, deployment, or worker fleet is correctly configured.

## Certification matrix

| Gate | Required evidence | CI gate |
|---|---|---|
| Security | Production auth defaults; test-auth hook impossible in production; security middleware and headers | `test_security_*` |
| Tenant isolation | Workspace membership enforcement and tenant-scoped listing | `test_tenant_isolation_certification_*` |
| Migration | Ordered SQL migrations; RLS and membership protections present | `test_migration_certification_*` |
| Workflow durability | Idempotency, leases, `SKIP LOCKED`, retries, artifact completion | `test_workflow_durability_certification` |
| Research E2E | Research API/platform/intelligence surfaces plus regression coverage | `test_research_e2e_certification_surface_exists` + full suite |
| Quant E2E | Quant vertical slice plus quantitative regression coverage | `test_quant_e2e_certification_surface_exists` + full suite |
| Agent E2E | Agent evaluation/benchmark/governance vertical slice plus regression coverage | `test_agent_e2e_certification_surface_exists` + full suite |
| Background worker | Production worker requires PostgreSQL; claim/complete path exercised | `test_background_worker_certification_requires_postgresql` |
| Observability | Correlation, job observation, and workflow/handler/artifact spans | `test_observability_certification` |
| Frontend E2E | Playwright product journey and navigation checks | existing `npm run e2e` |
| Regression | Ruff, mypy, pytest coverage gate, frontend production build, Playwright | CI `test` + `frontend` jobs |

## Production blockers that remain environment-specific

These are not honestly certifiable from GitHub CI alone and must be checked against the actual deployment before a production declaration:

1. Production PostgreSQL/Supabase is configured and reachable through `/ready`.
2. All migrations have been applied to the target database in timestamp order.
3. RLS policies are enabled and verified with real authenticated principals from separate tenants.
4. Production authentication uses the intended Supabase/JWT issuer, audience and signing keys.
5. `COLAB_ALLOW_TEST_AUTH` is disabled/unset in production.
6. Secrets are configured in the deployment secret store and are absent from logs/source.
7. Database backups and point-in-time recovery have been tested.
8. At least one production worker is running with `COLAB_DATABASE_DSN` and can claim, heartbeat, retry and complete jobs.
9. OpenTelemetry export/metrics destination is configured and receiving telemetry.
10. The deployed frontend and API pass health/readiness checks together.
11. Rollback and database recovery procedures have been exercised.

## Safety boundary

Colab remains an advisory research, quantitative experimentation and governed collaboration platform. It does not expose unrestricted financial execution authority. Agents do not receive exchange credentials or a direct order-submission path.

## Certification decision

**Engineering certification:** pending final Phase 21J CI run.

**Production declaration:** not granted until the environment-specific checks above have evidence from the actual production-like deployment.
