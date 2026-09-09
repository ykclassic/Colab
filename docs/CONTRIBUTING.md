# Contributing to Colab

## Principles

Contributions should prioritize correctness, security, reproducibility, maintainability and testability.

## Before Opening a Pull Request

Run the relevant backend tests, coverage, lint/type checks and frontend build/tests.

## Pull Request Requirements

Describe:

- purpose
- implementation
- tests
- security impact
- persistence impact
- API changes
- migration changes
- operational impact

## Code Standards

Prefer explicit types, small functions, clear domain boundaries, deterministic behavior, immutable data where appropriate and explicit error handling.

Avoid hard-coded secrets, implicit authorization, unrestricted network access, unbounded retries and silent failure.

## Security

Never weaken authentication, authorization, tenant isolation, approval controls or audit logging for convenience.

## Database Migrations

Never modify an already-applied production migration. Create a new migration instead.

## Documentation

New capabilities must update the appropriate documentation. A feature is incomplete if its behavior cannot be clearly explained to another engineer.
