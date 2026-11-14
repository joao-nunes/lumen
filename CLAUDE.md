# CLAUDE.md

Conventions for working on Lumen. [PROJECT.MD](PROJECT.MD) is the source of truth for the product and architecture; feature specs live in [docs/specs/](docs/specs/); API contracts, recipes and known issues are in the [developer guide](docs/developer-guide.md).

Lumen is a personal wellbeing reflection app. It supports therapy and never replaces it, and it is also a portfolio project, so production-grade rigor is the point, not overhead.

## Commands

```bash
docker compose up -d --wait db     # PostgreSQL (dev db `lumen`, test db `lumen_test`, runtime roles)
uv run alembic upgrade head
make check                         # pre-commit on all files: ruff, mypy (strict), gitleaks, actionlint, uv lock
make audit                         # known vulnerabilities in uv.lock and web/pnpm-lock.yaml (OSV-Scanner, needs Docker)
make test                          # backend and web tests; integration tests skip if the db is down
make e2e                           # AC-9 in Chromium on :8001, against the test database
make mutate [GROUPS="auth rls"]    # mutation check; recreates lumen_test
make eval-extraction MODEL=x       # measure a local model (spec 006); needs Ollama running
make dev                           # API on :8000, Vite on http://localhost:5173
make run                           # FastAPI serves the built frontend at http://localhost:8000
make schema                        # regenerate web/src/api/schema.d.ts after changing the API
```

## Workflow for every feature

1. **Spec first.** `docs/specs/NNN-name.md`, as a PR the owner approves before any code. It holds the scope, decisions, acceptance criteria as concrete examples, and open questions. Don't fill gaps with silent defaults: anything undecided goes in the open questions, and anything decided during implementation goes in an "Added during implementation" section for review.
2. **Tests first,** from the acceptance criteria. Show them failing for the right reason before implementing.
3. **Minimal implementation, then refactor.**
4. **Fault injection** for every significant code change or new feature:
   1. Deliberately introduce subtle bugs, memory leaks, race conditions, edge cases or common failure modes.
   2. Run the existing tests against them, and verify that the relevant tests go red.
   3. If they don't, refine the tests until they do.
   4. Revert every injected bug. None is ever merged.
   5. Fix any real issues found, then continue normal development and testing.

   Keep repeatable faults as mutants in `scripts/mutate.py` (`make mutate`). Security-critical code must have them.

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
- Prompt wording lives in `src/lumen/suggestions/prompts/`, one file per version, not in code. Changing a prompt, anchor or starter tag fails a test until it's measured again (`evals/extraction/measured_prompt.json`).

## Database and security invariants

- **Three database roles.** `lumen_app` touches user data, always through RLS: use `user_transaction(...)` from `lumen.db.scope`. `lumen_auth` touches `users` and the `auth` schema. The owner `lumen` runs migrations and dev tooling only.
- **Every new user-data table** needs a `user_id` column, forced RLS with a `user_isolation` policy (`USING` and `WITH CHECK`), and explicit grants, all in its migration.
- **No credentials in migrations.** Role logins live only in `docker/postgres/init/02-app-roles.sql`. `.env` is gitignored; document new settings in `.env.example`.
- **Content-Security-Policy.** Pages load only from Lumen's own origin (`lumen.api.middleware`). Don't add inline script or style, or third-party sources; a change to the policy needs the owner's approval.
- **Time.** The API and database stay in UTC. The web app shows dates and times through `web/src/lib/dates.ts`: instants in the browser's timezone, calendar days never converted.
- **Privacy.** Never store IP addresses. Raw journal text stays local (Tier 0); a hosted LLM only ever sees redacted or aggregated data.
- **Local models.** Free-text check-ins are Tier 0 and never saved. A person's personal context is Tier 0 too: saved, but only ever shown to the local model. `lumen.suggestions.ollama` talks only to a loopback address, refuses cloud models, ignores proxy settings and doesn't follow redirects, and Ollama runs with cloud features off. Keep it that way.
- **Dependencies.** CI fails on any known vulnerability in either lockfile (`make audit`, on every change and daily) and on new CodeQL alerts. Fix by upgrading. Only when that's impossible, add an exception to `osv-scanner.toml` that says why it can't be exploited in Lumen, with an `effectiveUntil` at most three months away. Never drop a lockfile from the scan or pin an older scanner to get green.
- **Logging.** Only `EventLog` (`lumen.api.event_log`) writes logs, and only allowlisted fields: never exception messages, request content or user IDs. PostgreSQL's error messages repeat query values, so `hide_parameters` isn't enough.

## Git and GitHub

- Every change goes on a branch with a PR. `master` is protected: CI must pass and be up to date, and conversations must be resolved. Never bypass this with `--admin`.
- Merge with merge commits, not squash, and only after the owner approves. Branches are deleted automatically on merge.
- Don't merge a PR whose head is another open PR's branch until that one is merged; deleting its base branch closes it.
- Pin GitHub Actions to commit SHAs.
