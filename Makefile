.PHONY: check audit test e2e mutate eval-extraction dev run schema check-schema

WEB := pnpm --dir web
# --no-access-log: uvicorn's access log records client IP addresses, which Lumen never stores.
PORT ?= 8000
API := uv run uvicorn lumen.api.main:app --factory --host 127.0.0.1 --port $(PORT) --no-access-log

# Lint, format, type-check and secret-scan everything (as CI's first job does).
check:
	uv run pre-commit run --all-files

# Known vulnerabilities in both lockfiles (as CI does on every change and daily). Needs Docker.
# Accepted exceptions, each with a reason and an expiry date, are in osv-scanner.toml.
audit:
	docker build --quiet --tag lumen-osv-scanner docker/osv-scanner > /dev/null
	docker run --rm -v "$(CURDIR):/src:ro" lumen-osv-scanner scan source \
		--config /src/osv-scanner.toml --lockfile /src/uv.lock --lockfile /src/web/pnpm-lock.yaml

# Unit and integration tests (integration tests need `docker compose up -d db`).
test:
	uv run pytest
	$(WEB) test

# End-to-end test (AC-9) in Chromium, against what `make run` serves. It runs on :8001 and uses
# the test database, so it can run beside the app and no test accounts reach the development one.
e2e:
	ADMIN_DATABASE_URL=postgresql+psycopg://lumen:lumen@localhost:5432/lumen_test uv run alembic upgrade head
	$(WEB) exec playwright install chromium
	$(WEB) exec playwright test

# Mutation check: rerun the suite against deliberate bugs. Recreates lumen_test.
# Choose groups with GROUPS="auth rls http checkins domain analytics" (default: all).
mutate:
	uv run python scripts/mutate.py $(GROUPS)

# Measure a local model on the evaluation set (spec 006 §3). Needs Ollama running; not part of CI.
# SPLIT=dev is for tuning prompts. Report on SPLIT=test only once, after they're settled.
SPLIT ?= dev
eval-extraction:
	uv run python scripts/eval_extraction.py --model $(MODEL) --split $(SPLIT) $(ARGS)

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
