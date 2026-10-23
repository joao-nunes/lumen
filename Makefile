.PHONY: check test mutate

# Lint, format, type-check and secret-scan everything (as CI's first job does).
check:
	uv run pre-commit run --all-files

# Unit and integration tests (integration tests need `docker compose up -d db`).
test:
	uv run pytest

# Mutation check: rerun the suite against deliberate bugs. Recreates lumen_test.
# Choose groups with GROUPS="auth rls http domain analytics" (default: all).
mutate:
	uv run python scripts/mutate.py $(GROUPS)
