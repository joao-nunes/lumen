.PHONY: check test mutate dev run schema check-schema

WEB := pnpm --dir web
# --no-access-log: uvicorn's access log records client IP addresses, which Lumen never stores.
API := uv run uvicorn lumen.api.main:app --factory --host 127.0.0.1 --port 8000 --no-access-log

# Lint, format, type-check and secret-scan everything (as CI's first job does).
check:
	uv run pre-commit run --all-files

# Unit and integration tests (integration tests need `docker compose up -d db`).
test:
	uv run pytest
	$(WEB) test

# Mutation check: rerun the suite against deliberate bugs. Recreates lumen_test.
# Choose groups with GROUPS="auth rls http checkins domain analytics" (default: all).
mutate:
	uv run python scripts/mutate.py $(GROUPS)

# Development: the API on :8000 and Vite on http://localhost:5173, both reloading on changes.
dev:
	@trap 'kill 0' EXIT; $(API) --reload --reload-dir src & $(WEB) dev & wait

# Everyday use: FastAPI serves the built frontend at http://localhost:8000.
run:
	$(WEB) build
	WEB_DIST=web/dist $(API)

# Regenerate the frontend's API types from the backend.
schema:
	uv run python scripts/export_openapi.py web/openapi.json
	$(WEB) exec openapi-typescript openapi.json -o src/api/schema.d.ts

# Fails if the committed API types don't match the backend (AC-11).
check-schema: schema
	git diff --exit-code -- web/src/api/schema.d.ts
