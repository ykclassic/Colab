# Colab Testing Strategy

## Testing Pyramid

```text
             E2E
              ▲
       Integration
              ▲
          API / DB
              ▲
       Unit / Domain
```

## Unit Tests

Test domain logic, workflow transitions, hashing, validation, risk calculations, quantitative metrics, retrieval algorithms and authorization functions.

## Integration Tests

Test PostgreSQL, migrations, RLS, API persistence, workflow checkpoints, research retrieval, quant persistence and governance persistence.

## Security Tests

Required tests include authentication, permissions, IDOR, tenant isolation, privilege escalation, secret handling and rate limits.

## Workflow Tests

Every legal transition and every important illegal transition should be covered.

Examples:

```text
RESEARCH → STRATEGY       PASS
STRATEGY → RISK           PASS
RISK → IMPLEMENTATION     PASS
RESEARCH → COMPLETE       FAIL
STRATEGY → COMPLETE       FAIL
```

## Quant Tests

Cover metric correctness, chronological ordering, transaction costs, look-ahead protection, train/test separation, OOS behavior, parameter sweeps, robustness and reproducibility.

## E2E Tests

The frontend should have browser tests covering login, workspace creation, workflow execution, research, quant analysis, risk review, human approval and final artifacts.

Playwright is recommended for browser-level testing.

## CI Release Gate

Recommended sequence:

```text
Lint → Type Check → Unit → Integration → Security → Frontend Build → E2E → Release
```

Critical failures must block promotion.
