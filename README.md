## Lumen — an agentic personal assistant for reflection and self-understanding.

[![CI](https://github.com/joao-nunes/lumen/actions/workflows/ci.yml/badge.svg)](https://github.com/joao-nunes/lumen/actions/workflows/ci.yml)

See [PROJECT.MD](PROJECT.MD) for the architecture and roadmap.

## Development

Requirements: [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env
uv sync
uv run pre-commit install           # lint, format, type-check, and secret-scan on every commit
docker compose up -d --wait db      # PostgreSQL 16 + pgvector (creates databases and runtime roles)
# Volumes created before the runtime roles existed need this once:
#   docker compose exec -T db psql -U lumen -d lumen < docker/postgres/init/02-app-roles.sql
uv run alembic upgrade head

uv run pytest                       # unit + integration tests (integration skips if DB is down)
uv run pytest -m "not integration"  # unit tests only
uv run ruff check . && uv run ruff format --check . && uv run mypy

# Seed the dev database with a synthetic persona (burnout | stable | seasonal_dip)
uv run python -m lumen.synthetic.seed burnout --seed 42
```

## Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on pushes to `master`:

- **Lint, format, types:** all pre-commit hooks (ruff, mypy, gitleaks, uv lock check, actionlint, file hygiene).
- **Tests (PostgreSQL):**
  - applies migrations to a fresh pgvector database
  - runs `alembic check` to fail on models that changed without a migration
  - runs the full test suite with integration tests required (never skipped) and a 90% coverage gate
  - smoke-tests the seeding CLI

Actions are pinned to commit SHAs. Dependabot proposes weekly updates for actions and Python dependencies.
