## Lumen — an agentic personal assistant for reflection and self-understanding.

See [PROJECT.MD](PROJECT.MD) for the architecture and roadmap.

## Development

Requirements: [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env
uv sync
docker compose up -d --wait db      # PostgreSQL 16 + pgvector (creates `lumen` and `lumen_test`)
uv run alembic upgrade head

uv run pytest                       # unit + integration tests (integration skips if DB is down)
uv run pytest -m "not integration"  # unit tests only
uv run ruff check . && uv run ruff format --check . && uv run mypy

# Seed the dev database with a synthetic persona (burnout | stable | seasonal_dip)
uv run python -m lumen.synthetic.seed burnout --seed 42
```
