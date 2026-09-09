# Colab Deployment

## Recommended Topology

```text
Internet
   ↓
Next.js Frontend
   ↓
FastAPI API
   ↓
Workflow / Research / Quant Services
   ↓
Workers
   ↓
PostgreSQL + pgvector
```

## Production Persistence

Production must use a configured PostgreSQL database and must not silently fall back to in-memory persistence.

Example:

```text
COLAB_ENV=production
COLAB_DATABASE_DSN=<secure-postgresql-dsn>
```

## Database Checklist

- Apply migrations in deterministic order.
- Verify RLS policies.
- Verify indexes.
- Configure backups.
- Test recovery.
- Validate connection limits.

## Health

Use `/health` for service health and `/ready` for dependency readiness.

## Deployment Gates

A production deployment should require successful tests, type checks, security checks, migration validation, frontend build, environment validation and health/readiness verification.

## Rollback

Every production deployment must have a documented rollback/recovery procedure. Database changes require an explicit migration and recovery strategy.

## Current Caveat

A successful build alone does not establish production readiness. Authentication, authorization, tenant isolation, database configuration, observability and deployment infrastructure must be validated independently.
