# Colab Security Model

## Objective

Security covers identity, authorization, tenant isolation, secret protection, auditability, tool restrictions, AI safety and data integrity.

## Authentication

Colab provides JWT authentication infrastructure. Protected API operations should derive an authenticated principal before executing.

```text
JWT → Validation → Principal → Authorization
```

## Authorization

Authorization should follow:

```text
User → Organization → Workspace Membership → Role → Permission → Resource
```

Example permissions include `workspace.read`, `workspace.write`, `research.write`, `strategy.write`, `risk.assess`, `validation.execute`, `human.approve` and `audit.read`.

## Tenant Isolation

Every workspace-scoped resource must be authorized against the authenticated principal. This includes workflows, artifacts, research, datasets, strategies, experiments, risk assessments, approvals and reports.

## Database Security

PostgreSQL Row Level Security should provide defense-in-depth. Application authorization and RLS must both be tested.

Minimum isolation tests should prove that users cannot read or modify another workspace by changing identifiers.

## AI Security

Agents must not receive raw exchange credentials, unrestricted network access, unrestricted shell access or direct financial execution authority. Agents must not approve their own work or modify governance rules.

## External Integrations

External connectors must enforce HTTPS-only transport, host/path allow-lists, timeouts, response-size limits, server-side credentials and audit logging.

## Secrets

Never commit API keys, database passwords, OAuth credentials, exchange credentials or private keys to Git.

## Audit Logging

Security-sensitive actions should generate audit events, including authorization failures, membership changes, approvals, rejections, promotions and external requests.

## Production Checklist

- [ ] All protected endpoints require authentication
- [ ] Workspace authorization is enforced
- [ ] RLS policies are tested
- [ ] IDOR tests pass
- [ ] Privilege-escalation tests pass
- [ ] Rate limits are enabled
- [ ] Security headers are enabled
- [ ] Secrets are externalized
- [ ] Dependency and secret scanning are enabled
- [ ] Production authentication bypasses are impossible
- [ ] External integrations are allow-listed
- [ ] Agents cannot access execution credentials
