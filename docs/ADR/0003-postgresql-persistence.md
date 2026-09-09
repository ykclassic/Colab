# ADR 0003: PostgreSQL as the Production System of Record

## Status

Accepted

## Decision

PostgreSQL is the primary durable persistence layer for production deployments.

## Rationale

The platform requires transactions, concurrency control, durable state, auditability, relational integrity, workspace isolation and scalable querying.

## Development Mode

In-memory implementations remain useful for local development and deterministic tests, but must not silently replace production persistence.
