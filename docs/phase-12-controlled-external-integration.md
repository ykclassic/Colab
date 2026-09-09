# Phase 12 — Controlled External Integration

Phase 12 introduces a deliberately narrow external-integration boundary for trusted, read-only data and tools.

## Controls

- Connectors must use HTTPS and an explicit host allow-list.
- Requests are limited to `GET` and connector-specific allow-listed paths.
- Private, loopback, link-local, multicast, reserved, and unspecified resolved addresses are rejected to reduce SSRF risk.
- Per-connector timeouts and response-size limits are mandatory.
- Credentials are referenced through server-side environment variables and are never returned by the API or audit records.
- Every request receives a correlation ID and an append-only in-process audit record.
- JSON responses are validated as objects or arrays before being returned to callers.
- Connector names containing trading/order/execution capabilities are rejected.

## Agent boundary

Agents may request approved external data through the integration gateway, but they do not receive arbitrary HTTP access, credentials, or execution primitives. A connector is a capability grant, not a general-purpose network tool.

## Trading boundary

Phase 12 does **not** add broker, exchange, order, transfer, withdrawal, or position-management operations. Any future trading integration must remain a separate execution subsystem with this invariant:

`Strategy Engine → Independent Risk Engine → Human Approval → Isolated Execution Gateway`

The external integration gateway must never be promoted into an execution gateway and must never allow an agent to bypass the risk or human-approval stages.

## Production rollout

1. Register only explicitly reviewed external data connectors.
2. Store provider credentials as backend secrets, never browser-visible environment variables.
3. Start with read-only endpoints and minimal path scopes.
4. Monitor audit records and error/timeout rates.
5. Add provider-specific adapters only behind the gateway contract.
6. Require regression and release-governance gates before promoting integration changes.
