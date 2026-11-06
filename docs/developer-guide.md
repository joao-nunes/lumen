# Lumen developer guide

Lumen is a personal wellbeing app: you record a daily check-in and it reports what your data shows, with the uncertainty attached. It supports therapy and never replaces it, and it is the foundation for the agents planned in [PROJECT.MD](../PROJECT.MD).

**What exists today:** Milestones 1 and 2, meaning auth, check-ins, deterministic analytics and the web app. **There is no agent, LLM or embedding code yet.** The LLM settings in `.env.example` aren't read by anything, and the pgvector database image isn't used.

Run every command from the repository root: `.env` and `alembic.ini` are found relative to the working directory.

## Set up

You need [uv](https://docs.astral.sh/uv/), Docker and [fnm](https://github.com/Schniz/fnm) (`brew install fnm`, then its shell setup).

```bash
fnm install "$(cat web/.nvmrc)" && fnm use "$(cat web/.nvmrc)"
npm install -g "pnpm@$(node -p "require('./web/package.json').packageManager.split('@')[1]")"
pnpm --dir web install

uv sync
uv run pre-commit install

cp .env.example .env
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" >> .env

docker compose up -d --wait db
uv run alembic upgrade head
make test
make run    # http://localhost:8000
```

| Command | What it does |
|---|---|
| `make dev` | API on :8000 and Vite on :5173, both reloading. No Content-Security-Policy here, because Vite serves the page. |
| `make run` | Builds the frontend; FastAPI serves it on :8000 (`PORT=` to change). The only mode with the real policy. |
| `make test` | pytest, then Vitest. Integration tests skip if the database is down. |
| `make e2e` | The Playwright test on :8001 against `lumen_test`. Can run beside the app. |
| `make check` | All pre-commit hooks: ruff, mypy strict, Prettier, ESLint, tsc, gitleaks, actionlint. |
| `make mutate GROUPS="auth http"` | Reruns the tests against deliberate bugs. About 7 minutes for all groups. Recreates `lumen_test`. |
| `make schema` | Regenerates `web/openapi.json` and `web/src/api/schema.d.ts`. |

## How a request flows

```text
SecurityHeadersMiddleware   headers on every response; no-store under /api/
RequestGuardMiddleware      unsafe methods: Origin allowed? JSON body?
route (lumen.api.routes)    orchestration only
  CurrentUser               session cookie -> user, via lumen_auth; CSRF on unsafe methods
  UserDb                    lumen_app transaction scoped to that user; commits before the response
  lumen.domain              rules and validation
  lumen.db.repository       SQL
  lumen.analytics           statistics, no I/O
```

`create_app` (`lumen/api/app.py`) is the only place that builds engines and services, and it takes a `clock` so tests control time. Domain exceptions become HTTP errors through `DOMAIN_ERRORS` in `lumen/api/errors.py`.

**Database roles:**

| Role | Can touch | Used for |
|---|---|---|
| `lumen_app` | User data, through row-level security | `UserDb` / `user_transaction(...)` |
| `lumen_auth` | `users` and the `auth` schema; can't read check-ins | `AuthDb` |
| `lumen` | Everything (superuser, bypasses RLS) | Migrations, seeding, tests |

RLS compares each row's `user_id` with a transaction-local setting, so it can't leak through a pooled connection. If that setting is missing, reads return no rows rather than an error.

## Call the API

There's no `/docs` or `/openapi.json` at runtime, because the Content-Security-Policy forbids the third-party script they load. For the machine-readable schema run `make schema` and read `web/openapi.json`, but see [known issues](#known-issues-and-open-questions) for what it leaves out.

With the server running:

```bash
BASE=http://localhost:8000/api; JAR=$(mktemp); DAY=$(date +%F)
JSON='content-type: application/json'

curl -s -c "$JAR" -H "$JSON" \
  -d '{"email":"dev@example.com","password":"correct horse battery staple"}' "$BASE/auth/register"

CSRF=$(awk '$6 ~ /lumen_csrf$/ {print $7}' "$JAR")

curl -s -b "$JAR" -X PUT -H "$JSON" -H "X-CSRF-Token: $CSRF" \
  -d '{"scores":{"mood":4,"energy":3,"stress":2},"tags":["Time outdoors"]}' "$BASE/checkins/$DAY"

curl -s -b "$JAR" "$BASE/overview?end=$DAY"
```

The `PUT` returns:

```json
{"local_date":"2026-11-05","prompted":["mood","energy","stress","concentration","social_connection"],
 "checkin":{"scores":{"mood":4,"energy":3,"stress":2},"tags":["time_outdoors"],"recorded_at":"2026-11-05T15:55:34.647967Z"}}
```

From Python, start the server with `COOKIE_SECURE=false`, because cookie jars won't send Secure cookies over `http://`. The cookies then have no `__Host-` prefix:

```python
import httpx2  # already a dev dependency
from datetime import date

with httpx2.Client(base_url="http://localhost:8000/api") as api:
    credentials = {"email": "agent@example.com", "password": "correct horse battery staple"}
    api.post("/auth/register", json=credentials).raise_for_status()
    csrf = {"X-CSRF-Token": api.cookies["lumen_csrf"]}

    today = date.today().isoformat()
    api.put(
        f"/checkins/{today}",
        json={"scores": {"mood": 4, "energy": 3, "stress": 2}, "tags": ["exercise"]},
        headers=csrf,
    ).raise_for_status()

    for dimension in api.get("/overview", params={"end": today}).json()["dimensions"]:
        print(dimension["dimension"], dimension["trend"]["outlook"], len(dimension["daily"]))
```

### Endpoints

Everything except register, login and logout needs a session. `PUT` and the password and logout `POST`s also need `X-CSRF-Token` when a session is present: the value of the `lumen_csrf` cookie.

| Endpoint | Success | Notes |
|---|---|---|
| `POST /api/auth/register` | `201 {user_id}` | Also logs in. Passwords: 15–256 characters, not containing "lumen" or the email's local part if that's 3+ characters. |
| `POST /api/auth/login` | `204` | New session; ends the one in the request's cookie. |
| `POST /api/auth/logout` | `204` | Also `204` without a session. |
| `POST /api/auth/password` | `204` | `{current_password, new_password}`. Ends all sessions and issues a new one. |
| `GET /api/auth/me` | `200 {user_id, email}` | |
| `GET /api/dimensions` | `200` | Keys, names, cadence, polarity and the five anchors. |
| `GET /api/tags` | `200 [{name, count}]` | Most used first. Unused tags are left out. |
| `GET /api/checkins/{date}` | `200` | Any date. `checkin` is `null` if none was saved. |
| `PUT /api/checkins/{date}` | `200` | See below. |
| `GET /api/overview?end={date}` | `200` | See below. `end` is required and has no limit, so future dates work. |

### Contracts

**Check-ins**
- There's one per day per user. `PUT` **replaces the whole day**, so a score or tag you leave out is deleted.
- `mood`, `energy` and `stress` are required. Any other known dimension is accepted, whether or not `prompted` lists it.
- Scores are JSON integers from 1 to 5; `true`, `"4"` and `4.0` are rejected.
- Tags are normalized (`"Time outdoors"` becomes `time_outdoors`). At most 20, and each must match `^[a-z][a-z0-9_]{0,39}$` after normalizing.
- `{date}` is the user's calendar day, chosen by the client. The server doesn't know their timezone, so it accepts from 8 days before the UTC date to 1 day after. The web app offers only today and the 7 days before it, in local time.
- `recorded_at` is the server's time in UTC. Saving again overwrites it.

**Overview**
- Each dimension has `change` (last 28 days against the 28 before) and `trend` (a slope over 84 days). `daily` and `rolling_7` cover the 84 days.
- A day missing from `daily` or `rolling_7` is a gap. Don't join across it. The rolling mean needs at least 3 days in its 7-day window.
- `direction` is what the numbers did: `increasing`, `decreasing`, `flat`, `unclear` or `insufficient_data`. `outlook` applies polarity, so rising stress is `worsening`. Use `outlook` for good or bad, and never compare `direction` across dimensions.
- `unclear` means the data can't separate change from noise. `insufficient_data` can appear with many days, because neighbouring days are correlated: the "effective" sample size must reach 4 in each period.
- Estimates are `null` when they can't be computed. There's deliberately no combined wellbeing score.

**Sessions**
- A session ends after 12 hours idle or 7 days in total (`SESSION_*` settings). A `401 not_authenticated` also clears the cookies.
- Login is limited per email, and password change per user, counted separately: 5 failures within 15 minutes gives `429` with `Retry-After`. Refused attempts don't extend the lockout, and a success resets the count.

### Errors

Failures from the app itself have this shape; see [known issues](#known-issues-and-open-questions) for the exceptions.

```json
{"error":{"code":"csrf_failed","message":"Missing or invalid CSRF token"}}
```

| Status | `code` | Cause |
|---|---|---|
| 401 | `not_authenticated` | No valid session |
| 401 | `invalid_credentials` | Wrong email or password (deliberately doesn't say which) |
| 403 | `csrf_failed` | Missing or wrong `X-CSRF-Token` |
| 403 | `forbidden_origin` | `Origin` is neither the server's own nor in `ALLOWED_ORIGINS` |
| 409 | `email_taken` | Registering an existing email, in any letter case |
| 415 | `unsupported_media_type` | Unsafe request with a body that isn't `application/json` |
| 422 | `invalid_email` | Registration |
| 422 | `weak_password` | Registration or password change |
| 422 | `missing_core_dimension`, `unknown_dimension`, `invalid_score`, `invalid_tag`, `too_many_tags`, `date_out_of_range` | Check-in rules |
| 422 | `invalid_request` | The request didn't match the schema |
| 429 | `too_many_attempts` | Login or password change lockout |

## Use the analytics from Python

This is the entry point for future agents. Analytics are pure functions over `Observation`s and need no database. **LLMs may interpret these results but never produce them.**

```python
from datetime import date, timedelta

from lumen.analytics.summary import summarize_all
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation
from lumen.synthetic.personas import PERSONAS, generate

end = date(2026, 10, 31)
checkins = generate(PERSONAS["burnout"], end - timedelta(days=111), days=112, seed=42)
observations = [
    Observation(day=c.local_date, dimension=d, value=v) for c in checkins for d, v in c.scores.items()
]

stress = summarize_all(observations, end)[Dimension.STRESS]
print(stress.trend.direction, stress.trend_outlook, round(stress.trend.slope_per_week, 3))
# increasing worsening 0.106
```

Personas are `burnout`, `stable` and `seasonal_dip`. To read real data, use `list_observations(db, user_id, overview_start(end), end)` inside a `user_transaction`, as `routes/overview.py` does.

## Extend

Feature work starts with a spec in `docs/specs/` that the owner approves, then failing tests. [CLAUDE.md](../CLAUDE.md) has the full workflow and the testing rules.

**Rules that apply to agent work:** Lumen's privacy and safety rules are in PROJECT.MD §2. Raw journal text stays local, a hosted LLM only ever sees redacted or aggregated data, and output must never be diagnostic.

### Add a user-data table and endpoint

1. Add the model to `lumen/db/models.py`:

   ```python
   class Goal(Base):
       __tablename__ = "goals"

       id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
       user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
       title: Mapped[str] = mapped_column(Text)
   ```

2. Run `uv run alembic revision --autogenerate -m "add goals"`. Autogenerate doesn't produce grants or RLS, and `alembic check` won't notice them missing, so add them to `upgrade()` by hand. Dropping the table in `downgrade()` removes them too.

   ```python
   op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON goals TO lumen_app")
   op.execute("ALTER TABLE goals ENABLE ROW LEVEL SECURITY")
   op.execute("ALTER TABLE goals FORCE ROW LEVEL SECURITY")
   op.execute(
       """
       CREATE POLICY user_isolation ON goals TO lumen_app
       USING (user_id = (SELECT current_app_user_id()))
       WITH CHECK (user_id = (SELECT current_app_user_id()))
       """
   )
   ```

   `test_every_user_owned_table_is_protected...` fails for any table with a `user_id` column and no policy. A child table should also carry `user_id`, with a composite foreign key to its parent (see `CheckinScore`).

3. Add the route in `lumen/api/routes/` and register its router in `create_app`. `CurrentUser` handles the session and CSRF, and `UserDb` handles RLS and the commit. Real routes keep their queries in `lumen/db/repository.py` and pass `user_id` even though RLS also enforces it.

   ```python
   router = APIRouter(prefix="/api")

   class GoalIn(BaseModel):
       title: str = Field(max_length=200)

   @router.post("/goals", status_code=201)
   def add_goal(body: GoalIn, user: CurrentUser, db: UserDb) -> GoalIn:
       db.add(Goal(user_id=user.user_id, title=body.title))
       db.flush()
       return body
   ```

4. Test through HTTP. `new_client` is an independent browser against the real app and database, and a test should prove isolation between users. Use the `clock` fixture for time.

   ```python
   from tests.api.client import NewClient, csrf, register

   def test_goals_are_private_to_each_user(new_client: NewClient) -> None:
       alice, bob = new_client(), new_client()
       register(alice, "alice@example.com")
       register(bob, "bob@example.com")

       alice.post("/api/goals", json={"title": "Walk daily"}, headers=csrf(alice))

       assert alice.get("/api/goals").json() == [{"title": "Walk daily"}]
       assert bob.get("/api/goals").json() == []
   ```

5. Run `make schema` and commit `schema.d.ts`; CI fails if it's out of date. Add mutants to `scripts/mutate.py` for security-critical behaviour.

### Add a domain error

Raise a new exception class and add a row to `DOMAIN_ERRORS`. The lookup is by exact type, so a **subclass** of a listed exception reaches the parent's handler and fails with a `KeyError` and a 500. Give each subclass its own row.

### Add a dimension

Dimensions are defined in `lumen/domain/dimensions.py`, and the web app picks them up from the API. Scores are stored in a Postgres enum, which creates two traps:

- **`alembic check` passes without a migration,** and saving the new dimension then fails with a 500. Add this by hand:

  ```python
  def upgrade() -> None:
      with op.get_context().autocommit_block():
          op.execute("ALTER TYPE dimension ADD VALUE IF NOT EXISTS 'appetite'")

  def downgrade() -> None:
      pass  # PostgreSQL can't remove an enum value
  ```

  Don't raise in `downgrade()`: the test fixture downgrades to base on every run, so that would break all integration tests.
- **A fifth rotating dimension breaks the schedule.** `rotating_dimensions_for` works with four, which gives two alternating pairs, and a test requires every dimension to be asked within two days. `prompted` is computed from the date rather than stored, so changing the schedule also changes what past days report.

### Change the frontend

- **Types** come from the backend: `make schema` after any API change.
- **Dates** go through `web/src/lib/dates.ts`. `new Date("2026-10-31")` is midnight UTC, which displays as 30 October west of UTC.
- **API calls** go through `web/src/api/client.ts`, which adds the CSRF header and handles an ended session.
- **No inline script, inline `style` attributes or third-party sources.** Styles React sets from script are fine. `make dev` won't reveal a violation; `make e2e` will. Changing the policy needs the owner's approval.

## Test

| Layer | Where | Use |
|---|---|---|
| Pure logic | `tests/domain`, `tests/analytics`, `web/src/lib` | No database. |
| Database rules | `tests/db`, `session` fixture | One transaction per test, rolled back. `act_as(session, APP, user_id)` switches to a runtime role. Connecting as the owner bypasses RLS, so a test that doesn't switch proves nothing about it. |
| HTTP | `tests/api`, `new_client` and `clock` fixtures | Real app and database. Tables are truncated around each test. |
| Screens | `web/src/screens/*.test.tsx` | jsdom with a fake `fetch`. Charts don't draw here. |
| End to end | `web/e2e` | Chromium under the real policy. Fails on any policy violation or page error. |

Gotchas:
- **`lumen_test` is shared.** pytest downgrades and upgrades it on every run, and `make e2e` and `make mutate` also use it, so don't run them at the same time.
- **Use the `passwords` fixture** for service-level tests, because production Argon2 settings are slow.
- **CI is stricter than local.** It sets `LUMEN_REQUIRE_DB=1` so integration tests fail rather than skip, enforces 90% coverage, and runs `alembic check`.
- **`make mutate` isn't in CI.** It stops before starting if a mutant's snippet no longer matches the code exactly once, so update the mutant when you change that code.

## Debug

| Symptom | Likely cause |
|---|---|
| `ValueError: SECRET_KEY must be set` | Not in `.env`, or you're not in the repository root. |
| `ValueError: WEB_DIST has no index.html` | Empty or wrong `WEB_DIST`. Leave it unset unless you need it; `make run` sets it. |
| `500`, plain text "Internal Server Error", no security headers | Unhandled exception. The traceback is in uvicorn's stderr; there's no application logging. |
| `403 csrf_failed` on every write, while reads work | `SECRET_KEY` changed. Log in again (see known issues). |
| `403 forbidden_origin` | The client's origin isn't in `ALLOWED_ORIGINS`, for example Vite on another port. |
| `KeyError: 'lumen_csrf'` in a Python client | The server has Secure cookies on. Set `COOKIE_SECURE=false`. |
| Can't stay logged in on Safari | Safari rejects Secure cookies on `http://localhost`. Set `COOKIE_SECURE=false`. |
| A query returns nothing | Not using `UserDb`/`user_transaction`, or the row belongs to another user. |
| `permission denied for table ...` | Missing `GRANT` in the migration, or the wrong role for that table. |
| `new row violates row-level security policy` | Inserting a `user_id` other than the scoped user. |
| `role "lumen_app" is not permitted to log in` | The volume predates the runtime roles, so migrations created them without a login. Run `docker compose exec -T db psql -U lumen -d lumen < docker/postgres/init/02-app-roles.sql`. |
| Integration tests skipped | Database down: `docker compose up -d --wait db`. |
| CI: API types differ | Run `make schema` and commit. |
| Pre-commit: `pnpm` not found | Node isn't on your `PATH`; finish fnm's shell setup. |

**See what a role sees.** This reproduces the app's view of the data:

```bash
docker compose exec -T db psql -U lumen -d lumen <<'SQL'
BEGIN;
SET LOCAL ROLE lumen_app;
SELECT set_config('lumen.user_id', '<user uuid>', true);
SELECT local_date, recorded_at FROM checkins ORDER BY local_date DESC LIMIT 5;
ROLLBACK;
SQL
```

**See charts with data.** Seeded users have no password, so register in the app first, then fill that account:

```python
# uv run python seed_account.py
from datetime import date, timedelta
from sqlalchemy import select
from lumen.config import get_settings
from lumen.db.models import User
from lumen.db.repository import save_checkin
from lumen.db.session import make_engine, make_session_factory
from lumen.synthetic.personas import PERSONAS, generate

EMAIL, DAYS = "you@example.com", 112
factory = make_session_factory(make_engine(get_settings().admin_database_url))
with factory.begin() as db:
    user_id = db.scalars(select(User.id).where(User.email == EMAIL)).one()
    for checkin in generate(PERSONAS["burnout"], date.today() - timedelta(days=DAYS - 1), DAYS, seed=42):
        save_checkin(db, user_id, checkin)
```

**Start the database again:** `docker compose down -v && docker compose up -d --wait db && uv run alembic upgrade head`. This deletes all local data.

## Known issues and open questions

Each was checked against a running server or the code. None is fixed yet.

**Looks like a bug**
1. **Not every error has the documented shape.** Unknown paths and wrong methods return FastAPI's `{"detail":"Not Found"}` and `{"detail":"Method Not Allowed"}`, although spec 001 §2.6 and `lumen/api/errors.py` promise one shape. The web client copes, reporting them as `unexpected_response`; other clients may not.
2. **Misleading `invalid_request` message.** A bad path or query value, such as `GET /api/checkins/notadate` or a missing `end`, says "The request body is invalid".
3. **The OpenAPI document doesn't describe the errors.** It gives `422` as FastAPI's `HTTPValidationError`, which the API never returns, and omits 401, 403, 409, 415 and 429. So `schema.d.ts` has the same gap.
4. **Changing `SECRET_KEY` traps logged-in users.** The CSRF token is derived from it, so existing sessions can read but get `403 csrf_failed` on every write, **including logout**. Logging in again fixes it. From reading the code, the web app's *Log out* button would appear to do nothing, because `handleLogOut` doesn't catch the failure.
5. **`LOG_LEVEL` does nothing.** `Settings` reads it, but nothing uses it and the app has no logging.
6. **Seeded users can't log in,** because `lumen.synthetic.seed` creates them without a password. The script above works around it.
7. **Registering while logged in leaves the old session valid until it expires.** Login ends the previous session; registration doesn't. Spec 001 doesn't say which is intended.

**Needs a decision**
8. **Parallel logins can get extra guesses.** From reading the code, requests sent together can all read a failure count below the limit before any failure is recorded; this hasn't been reproduced. Password change closes this gap with a row lock, but login counts unknown emails too, so it has no row to lock (spec 004 Q2).

**Deliberate, so don't "fix" without revisiting the spec**
- **Anyone can lock an email out for 15 minutes,** because the limit is per email and no IP addresses are stored (spec 001 §2.5).
- **Registration has no rate limit.** The owner decided against one.
- **Only one checkout can run the database at a time.** Compose names its project after the folder and always publishes port 5432, so a second clone or worktree fails on `docker compose up` and leaves an unused container and volume behind. The owner chose this over sharing one database across checkouts, where one checkout's migrations would affect another.
- **Registration reveals which emails exist** through `409 email_taken`, although login hides it (spec 001 §2.6).
- **Nothing cleans up authentication data yet.** `purge_expired` has no caller, and `auth.login_attempts` and `auth.password_change_attempts` are never purged, so the first keeps every attempted email. Both wait for the scheduler milestone (spec 001 I4).
- **A missing asset gets `200` with `index.html`,** not `404`, so that reloading a browser route works (spec 002 I12).
