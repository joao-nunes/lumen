# Spec 005: Privacy-safe logging

**Status:** Approved (decisions in §5)
**Builds on:** spec 001 (auth HTTP layer), spec 003 (security headers), spec 004 (password change limit)

## 1. Goal

When a request fails, Lumen keeps no record of it beyond whatever uvicorn prints, and that output can contain private text. This spec adds a small log that helps diagnose failures and can't carry personal content, and it closes the leaks that exist today.

### What happens today

Each of these was checked with a marker value against the test database:

| Finding | Result |
|---|---|
| A crash under real uvicorn | The traceback, with the marker in it, goes to the terminal |
| SQLAlchemy's `hide_parameters=True` | **Doesn't help.** PostgreSQL's own error message repeats the value: a bad cast names it, a unique violation repeats the key, and a `NOT NULL` violation repeats the row |
| The database container's log (`docker compose logs db`) | The marker is written there too |

Journal text isn't stored by any table yet, but the same paths apply to anything a query carries, including emails and tags today, and the agents work will add journal text. No request is known to trigger these errors today, so these are weaknesses rather than an observed leak.

### Non-goals
- **Metrics, dashboards and alerts.**
- **Shipping logs anywhere.** Lumen runs on `localhost`.
- **Agent and scheduler events.** Each milestone adds its own, under the rules in §2.1.
- **Command line tools** (`alembic`, the seed command, `scripts/`). They don't handle requests.
- **Vite's output under `make dev`.**

## 2. Proposed decisions

### 2.1 Only named fields can be logged

The rule is an allowlist: a value reaches the log only if this spec names its field and the field's value can only come from Lumen's own code or from a fixed list.

A small `EventLog` class offers one method per kind of line, with typed arguments. It has no method that takes free text, a dictionary or an exception message. Adding a field means changing that class and this list, which makes it visible in review.

**Never logged:** request or response bodies, query strings, raw paths, headers, cookies, emails, user IDs, session tokens, IP addresses, exception messages, and argument or variable values.

### 2.2 The two kinds of line

One JSON object per line. JSON means a value can't forge an extra line.

**`request`**, for each request under `/api/`:

```json
{"ts":"2026-11-06T09:00:00Z","event":"request","request_id":"9f1c...","method":"PUT","route":"/api/checkins/{local_date}","status":422,"duration_ms":12,"error":"invalid_score"}
```

| Field | Value | Why it's safe |
|---|---|---|
| `ts` | UTC, from the injected clock | Set by the server |
| `request_id` | Random, new for each request | Set by the server. An incoming `X-Request-ID` is ignored |
| `method` | A standard HTTP method, otherwise `OTHER` | Fixed list |
| `route` | The route's template, or `null` if no route matched | Comes from the code, so a date in the path or text in an unknown path never appears |
| `status` | The HTTP status | A number |
| `duration_ms` | Whole milliseconds | A number |
| `error` | The API's error code, or `null` | Fixed list. Anything else is logged as `unknown` |

**`crash`**, for each unhandled exception, right before its `request` line:

```json
{"ts":"2026-11-06T09:00:00Z","event":"crash","request_id":"9f1c...","exceptions":["sqlalchemy.exc.DataError","psycopg.errors.InvalidTextRepresentation"],"frames":["lumen.db.repository:save_checkin:88","lumen.api.routes.checkins:put_checkin:97"]}
```

- **`exceptions`** holds the class names of the exception and its causes.
- **`frames`** holds `module:function:line` for Lumen's own code only.

**The cost:** a crash line says where and what kind of failure happened, but not the message. A `KeyError` won't say which key, so some bugs will need reproducing in a test. See Q2.

Pages and static assets get no `request` line: they carry no data and would add noise. A crash there still gets a `crash` line.

### 2.3 Error codes serve as the named events

Route, status and error code already identify each security event, so no separate event names are needed:

| Event | `route` | `status` | `error` |
|---|---|---|---|
| Failed login | `/api/auth/login` | 401 | `invalid_credentials` |
| Login locked | `/api/auth/login` | 429 | `too_many_attempts` |
| Wrong current password | `/api/auth/password` | 401 | `invalid_credentials` |
| Password change locked | `/api/auth/password` | 429 | `too_many_attempts` |
| CSRF refused | any write | 403 | `csrf_failed` |
| Origin refused | any write | 403 | `forbidden_origin` |

This means no new code at each place an error occurs, and no second list to keep in step with the first.

### 2.4 Crashes are caught, so uvicorn doesn't print them

Uvicorn prints any exception that reaches it, so the fix is to stop it getting there. A new middleware sits just inside `SecurityHeadersMiddleware` and:

- gives each request its ID, and returns it as an `X-Request-ID` response header
- writes the lines in §2.2
- catches `Exception` and returns `500`:

```json
{"error":{"code":"internal_error","message":"Something went wrong"}}
```

**This changes behaviour on purpose:** a crash now returns the API's normal error shape and has the security headers. Spec 003 §2.4 had accepted that it wouldn't. The web client already handles this shape.

**Edge cases:**
- **Crash after the response has started:** a `500` can't be sent, so it writes the `crash` line and ends the response without re-raising, which keeps the message away from uvicorn.
- **Cancellation (`CancelledError`):** this isn't an `Exception`, so it passes through untouched.

### 2.5 Logging can't break a request

If writing a line fails, such as when stderr is a closed pipe, the error is swallowed and the request's response doesn't change. A broken terminal shouldn't cost someone a check-in.

### 2.6 The database's own log

`docker-compose.yml` starts PostgreSQL with `log_min_messages=log`. That drops `ERROR` lines, which hold the repeated values, and keeps startup and shutdown lines. In a one-off test with this setting, the marker didn't reach the log, while with the default setting it did.

The application still gets each error as an exception, so `crash` lines still identify it. Direct `psql` errors no longer appear in the container's log, but `psql` shows them itself.

**Existing logs:** applying this recreates the database container, which also clears its old logs. The data is in a volume and isn't affected.

### 2.7 Code

- **No third-party library and no `LOG_LEVEL`.** With two kinds of line there's nothing to filter, and `LOG_LEVEL` was only just removed for doing nothing.
- **`EventLog` is injected** through `create_app`, as the clock is, so tests read the lines directly.
- **Ruff bans importing `logging` and `traceback` in `src/lumen`,** so nothing can bypass the allowlist by accident.
- **`--no-access-log` stays.**

## 3. Acceptance criteria

HTTP tests against the real test database, with an injected clock and a captured log.

- **AC-1 (request line):** an invalid `PUT /api/checkins/2026-10-23` writes exactly one line, with exactly the fields in §2.2: the route's template, `status: 422` and `error: invalid_score`. `duration_ms` is a whole number of at least 0, and `request_id` equals the `X-Request-ID` response header.
- **AC-2 (no marker gets through):** one marker is sent in each of these places, across registration, login, password change, check-in and an unknown `/api` path: the email, password, tag, path, query string, a header (including `User-Agent`), `X-Forwarded-For`, and the cookies. No marker appears in any log line, whether the request succeeds or fails.
- **AC-3 (no user details):** after registering and logging in, the log contains neither the user's ID nor their email, nor the session token.
- **AC-4 (crash):** a route that fails with a real PostgreSQL error repeating a marker gives:
  - a `500` with the exact body of §2.4 and the security headers from spec 003
  - a `crash` line with the expected exception classes and frames, followed by a `request` line with `status: 500` and `error: internal_error`, both with the same `request_id`
  - no marker in the log or the response
- **AC-5 (security events):** each row in §2.3 produces exactly that `route`, `status` and `error`.
- **AC-6 (request IDs):**
  - An incoming `X-Request-ID` is ignored.
  - Parallel requests each get their own ID, matching their own response.
- **AC-7 (no line for pages):** `GET /` and a static asset write nothing. A crash while serving one writes a `crash` line.
- **AC-8 (unknown values):** a method outside the standard list is logged as `OTHER`. An unmatched `/api` path has `route: null` and `error: not_found`.
- **AC-9 (crash after the response started):** a `crash` line is written, and nothing is re-raised.
- **AC-10 (logging fails):** with a log that raises on every write, a normal request and a crashing one still return their usual responses.

**Checked by hand once, as with spec 003's browser check:**
- Under real uvicorn, a crash carrying a marker leaves it out of the terminal output.
- With the Compose setting applied, the marker isn't in `docker compose logs db`.
- Ruff rejects `import logging` in `src/lumen`.

**Untested by justification:** the JSON encoder's escaping, which is the standard library's; and the exact `duration_ms`, which depends on real time.

## 4. Mutation check

Add a `logging` group to `make mutate`:
- Exception message added to the `crash` line
- Raw path logged instead of the route's template
- Query string added to `route`
- Client's `X-Request-ID` trusted
- Request ID shared between requests
- Unknown `error` or method logged as received
- User ID added to the `request` line
- Crash re-raised after logging
- `Exception` caught but no `crash` line written
- Middleware outside `SecurityHeadersMiddleware`, so a `500` loses the headers
- Failed log write not swallowed
- Pages logged

One-off faults under the project workflow, beyond these: cancellation swallowed, a crash in the error handling itself, a failure while the `500` is being sent, and an exception whose cause chain loops.

## 5. Decisions

The owner chose the recommendation on all three.

| # | Question | Decision |
|---|---|---|
| Q1 | **Where do lines go?** Stderr only, or also a rotating file? A file keeps history after the terminal closes, but it would be a dated record of when someone used the app, outside row-level security. | **Stderr only.** You can see failures while the app runs, and nothing is written to disk. Revisit at deployment, when there's also somewhere safer to keep a file. |
| Q2 | **Should there be a developer switch that shows full exception messages?** It would make local debugging easier, but it's easy to leave on, and it's the exact leak this spec closes. | **No switch.** Reproduce the bug in a test, where the data is fake. |
| Q3 | **Should `request` lines include the user ID?** It would separate users' activity once there are several, but it would tie each person to a timeline of their use. | **No.** Lumen has few users on `localhost`, so it would add little. Revisit at deployment. |

## 6. Added during implementation (for review)

Nothing yet.
