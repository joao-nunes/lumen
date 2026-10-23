# CLAUDE.md

Conventions for working on Lumen. [PROJECT.MD](PROJECT.MD) is the source of truth for the product and architecture; feature specs live in [docs/specs/](docs/specs/).

Lumen is a personal wellbeing reflection app. It supports therapy and never replaces it, and it is also a portfolio project, so production-grade rigor is the point, not overhead.

## Commands

```bash
docker compose up -d --wait db     # PostgreSQL (dev db `lumen`, test db `lumen_test`, runtime roles)
uv run alembic upgrade head
make check                         # pre-commit on all files: ruff, mypy (strict), gitleaks, actionlint, uv lock
make test                          # all tests; integration tests skip if the db is down
make mutate [GROUPS="auth rls"]    # mutation check (about 7 min for all groups); recreates lumen_test
```

## Workflow for every feature

1. **Spec first.** `docs/specs/NNN-name.md`, as a PR the owner approves before any code. It holds the scope, decisions, acceptance criteria as concrete examples, and open questions. Don't fill gaps with silent defaults: anything undecided goes in the open questions, and anything decided during implementation goes in an "Added during implementation" section for review.
2. **Tests first,** from the acceptance criteria. Show them failing for the right reason before implementing.
3. **Minimal implementation, then refactor.**
4. **Mutation check** for security-critical code: add mutants to `scripts/mutate.py` and run `make mutate`.

## Tests

Write the minimum number of tests; every test must mitigate a real production risk.
- Test behaviors through public inputs and outputs, never private methods or internals.
- Skip trivial code (getters, mappers, linear glue). When you skip something, justify why rather than testing it.
- Prefer critical branches to line coverage, and don't retest what a higher-level test already proves.
- Cover only the essential edge cases, with strong assertions on the complete output state.
- Mock only slow or non-deterministic dependencies. Time is injected (`now` or a clock), not mocked. Use the real PostgreSQL test database wherever the database is the behavior: constraints, RLS, grants, migrations.

## Design and code

- SOLID, without abstraction for its own sake. Inject collaborators (e.g. `AuthService` takes `Passwords` and `SessionPolicy`), and add a `Protocol` only for a real seam.
- Type-check with mypy in strict mode, not ty. Avoid `type: ignore`; type the code properly instead.
- Analytics are deterministic code. LLMs may interpret computed results but never produce them.

## Database and security invariants

- **Three database roles.** `lumen_app` touches user data, always through RLS: use `user_transaction(...)` from `lumen.db.scope`. `lumen_auth` touches `users` and the `auth` schema. The owner `lumen` runs migrations and dev tooling only.
- **Every new user-data table** needs a `user_id` column, forced RLS with a `user_isolation` policy (`USING` and `WITH CHECK`), and explicit grants, all in its migration.
- **No credentials in migrations.** Role logins live only in `docker/postgres/init/02-app-roles.sql`. `.env` is gitignored; document new settings in `.env.example`.
- **Privacy.** Never store IP addresses. Raw journal text stays local (Tier 0); a hosted LLM only ever sees redacted or aggregated data.

## Git and GitHub

- Every change goes on a branch with a PR. `master` is protected: CI must pass and be up to date, and conversations must be resolved. Never bypass this with `--admin`.
- Merge with merge commits, not squash, and only after the owner approves. Branches are deleted automatically on merge.
- Don't merge a PR whose head is another open PR's branch until that one is merged; deleting its base branch closes it.
- Pin GitHub Actions to commit SHAs.
