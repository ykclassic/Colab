# Colab Development Guide

## Requirements

- Python 3.12+
- Node.js
- npm
- PostgreSQL for durable development
- Git

## Backend

```bash
python -m pip install -e '.[dev]'
pytest
pytest --cov=colab --cov-report=term-missing --cov-fail-under=90
uvicorn colab.api:app --reload
```

## Frontend

Use the committed lockfile for reproducible installs:

```bash
npm ci
```

Then use the repository's configured development and build commands.

## Code Standards

Prefer explicit types, Pydantic validation, deterministic behavior, small functions, clear domain boundaries and explicit error handling.

Avoid hidden global state, implicit authorization, duplicated business logic, unbounded retries, unrestricted network access and silent failure.

## Pull Requests

Describe the purpose, implementation, tests, security impact, persistence impact, API changes, migrations and operational impact.

## Database Migrations

Production migrations must be immutable after application. Create a new migration for subsequent changes and keep migration ordering deterministic.

## Feature Completion

A feature is complete only when relevant implementation, tests, authorization, persistence, observability and documentation are addressed.
