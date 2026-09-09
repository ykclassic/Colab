# Phase 11 — Production Validation & Release Governance

Phase 11 creates the control plane between quantitative research and production promotion.

## Capabilities

- **Reproducibility manifests:** bind dataset checksum, feature configuration, strategy parameters, code revision, dependency-lock hash, seed, and environment into a deterministic manifest hash.
- **Strategy/model versioning:** register immutable version identities with artifact and manifest digests; duplicate name/version registrations are rejected.
- **Regression suites:** deterministic cases with explicit expected values, tolerances, and criticality. Critical failures block release.
- **Promotion gates:** candidate, staging, and production policies have explicit minimum readiness scores and required gates.
- **Readiness scoring:** aggregate gate scores into candidate-ready, staging-ready, production-ready, or not-ready ratings.
- **Audit trail:** promotion decisions are append-only in the governance service and expose their reasons/evidence.
- **Safety boundary:** this phase authorizes promotion decisions but does not deploy models, place orders, or bypass existing human-review/execution controls.

## Promotion policy

| Target | Minimum score | Required gates |
|---|---:|---|
| Candidate | 70 | Reproducibility, version integrity, regression |
| Staging | 80 | Candidate gates + operational readiness |
| Production | 90 | Staging gates + risk |

## API

- `POST /api/governance/versions`
- `GET /api/governance/versions`
- `POST /api/governance/versions/{version_id}/promote`
- `GET /api/governance/decisions`

The implementation is intentionally deterministic and dependency-light. Durable persistence of governance records can be added without changing the gate contracts.
