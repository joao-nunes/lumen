# Spec 001: Auth HTTP layer

**Status:** Approved (decisions in §4)
**Milestone:** 1, closes it
**Builds on:** `AuthService` (`lumen.auth.service`), database roles and RLS (`lumen.db.scope`)

## 1. Goal

Expose authentication over HTTP so the future React frontend can register, log in, stay logged in, log out and change its password. Every request that touches user data must run as `lumen_app` with RLS scoped to the logged-in user.

### Non-goals
- No frontend, password reset or email verification (there's no mail server).
- No OAuth, passkeys or MFA, and no account deletion.
- No rate limiting on registration.
- No HTTPS termination: this is a local desktop app, see Q2.

## 2. Proposed decisions

### 2.1 Application structure
- **App factory.** FastAPI with `create_app(settings, clock)` as the single composition root. It wires two session factories (`lumen_app` and `lumen_auth`), `AuthService`, the login limiter and the clock.
- **Dependency injection.** Endpoints receive collaborators through FastAPI dependencies, so tests swap the clock and settings without patching (dependency inversion).
- **User-scoped sessions.** The `current_user` dependency resolves the session cookie with `AuthService.resolve` on the auth connection. Data endpoints then receive a session from `user_transaction(app_factory, user_id)`, so RLS applies automatically.

### 2.2 Endpoints (JSON, under `/api/auth`)

| Method and path | Body | Success | Notes |
|---|---|---|---|
| `POST /register` | `{email, password}` | `201 {user_id}` and sets cookies | Logs in immediately (Q1) |
| `POST /login` | `{email, password}` | `204` and sets cookies | Replaces any existing session (rotation) |
| `POST /logout` | — | `204` and clears cookies | Idempotent |
| `POST /password` | `{current_password, new_password}` | `204` and new cookies | Revokes all other sessions |
| `GET /me` | — | `200 {user_id, email}` | `401` if not logged in (Q5) |

### 2.3 Cookies
- **Session cookie:** `__Host-lumen_session` holds the raw session token, with `HttpOnly; Secure; SameSite=Strict; Path=/`. Its `Max-Age` is the absolute timeout (7 days); the server stays authoritative about idle expiry. The `__Host-` prefix makes browsers refuse the cookie unless it's `Secure`, has `Path=/` and has no `Domain`, so it can't be overwritten from a subdomain. Chrome accepts `Secure` cookies on `http://localhost` (Q2).
- **CSRF cookie:** `__Host-lumen_csrf` holds the CSRF token. It isn't `HttpOnly`, because the frontend must read it.
- **Logout and session expiry** clear both cookies.

### 2.4 CSRF and cross-site defences (defence in depth)
1. **`SameSite=Strict`** session cookie: browsers don't send it on cross-site requests.
2. **Origin check:** for unsafe methods (`POST`/`PUT`/`PATCH`/`DELETE`), reject with `403` if the `Origin` header is present and not in `ALLOWED_ORIGINS`. This also covers login and register, where there's no session yet ("login CSRF"). Dev allowlist: `http://localhost:5173` (Vite) and the API's own origin (Q4).
3. **JSON only:** request bodies must be `application/json`, so plain HTML forms from other sites can't submit them.
4. **CSRF token:** authenticated unsafe requests must send the header `X-CSRF-Token` equal to `HMAC-SHA256(SECRET_KEY, session_token)`.
   - Because the token is derived from the session, nothing extra is stored, and it rotates whenever the session does.
   - Comparison is constant-time.
   - A missing or wrong token gives `403`.

### 2.5 Login rate limiting
- **Storage:** a new table, `auth.login_attempts (email citext, attempted_at timestamptz, succeeded bool)`. No IP addresses are stored, consistent with the privacy principle.
- **Rule:** after **5 failed attempts for an email within 15 minutes**, further logins for that email are rejected with `429` and `Retry-After` until the oldest of those failures is 15 minutes old (Q3).
- **Unknown emails** are counted the same way, so a `429` doesn't reveal whether an account exists.
- **During a lockout, even the correct password is rejected.** That's what makes guessing pointless.
- **A successful login resets the count:** only failures after the last success count.
- **Failed attempts are recorded even though the request fails,** in their own transaction.
- **Known trade-off:** anyone can lock an email out for 15 minutes. That's acceptable for a local personal app.
- `purge_expired` also deletes attempts older than the window.

### 2.6 Errors
Errors use one JSON shape: `{"error": {"code": "<code>", "message": "<human text>"}}`.

| Situation | Status | `code` |
|---|---|---|
| Wrong email or password, or unknown email | 401 | `invalid_credentials` (same message for both) |
| Not logged in, or session expired | 401 | `not_authenticated` |
| Email already registered | 409 | `email_taken` |
| Invalid email or password policy violation | 422 | `invalid_email` / `weak_password`, with the policy message |
| Too many login attempts | 429 | `too_many_attempts`, plus a `Retry-After` header |
| Origin, content type or CSRF failure | 403 / 415 | `forbidden_origin`, `csrf_failed` / `unsupported_media_type` |

A `409` on registration reveals that an email is registered. That's inherent to sign-up, and acceptable here.

### 2.7 New settings
- `SECRET_KEY`: required, at least 32 bytes. The app fails to start without it.
- `ALLOWED_ORIGINS`: a list of allowed origins.
- `COOKIE_SECURE`: true by default (Q2).

## 3. Acceptance criteria

Each criterion becomes an HTTP-level test (FastAPI `TestClient` against the real test database, with an injected clock), written first and shown failing before implementation.

**Register and login**
- **AC-1:** Registering a new email gives `201` with a `user_id` and sets both cookies, so `GET /me` immediately returns that user. Registering the same email in any letter case gives `409 email_taken`.
- **AC-2:** A 12-character password gives `422 weak_password`, and no user is created.
- **AC-3:** A correct login gives `204` and sets both cookies with the attributes in §2.3. `GET /me` then returns `{user_id, email}`.
- **AC-4:** A wrong password and an unknown email both give `401 invalid_credentials` with an identical body.
- **AC-5:** Logging in while already holding a session cookie invalidates the old session: the old token now gives `401` on `/me`.

**Sessions**
- **AC-6:** With the clock 12 hours after the last activity, `/me` gives `401 not_authenticated` and clears the cookies.
- **AC-7:** Logout gives `204` and clears the cookies, and the old token gives `401`. Logging out twice also gives `204`.
- **AC-8:** A password change gives `204` with new cookies. Every other session, e.g. a second browser, gets `401`. The old password no longer logs in.

**CSRF and origin**
- **AC-9:** An authenticated `POST /logout` without `X-CSRF-Token`, or with a token from another session, gives `403 csrf_failed`, and the session stays valid.
- **AC-10:** `POST /login` with `Origin: https://evil.example` gives `403 forbidden_origin`, even with correct credentials.
- **AC-11:** `POST /login` with a form-encoded body gives `415`.

**Rate limiting**
- **AC-12:** 5 wrong passwords within 15 minutes, then the *correct* password, gives `429` with `Retry-After`. At the 15-minute mark the correct password gives `204`.
- **AC-13:** The same sequence for an email that doesn't exist also ends in `429`.
- **AC-14:** 4 failures, then a success, then 4 more failures doesn't trigger a lockout, because the success resets the count.

**User data and RLS**
- **AC-15:** A request with a valid session reaches data endpoints with a database session scoped to that user. A test endpoint that lists check-ins with **no filter** returns only that user's rows.

## 4. Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Should registering also log you in? | **Yes** |
| Q2 | `Secure` cookies on `http://localhost` (Safari may refuse them) | **Not an issue:** the owner uses Chrome, so keep `Secure` and the `__Host-` prefix |
| Q3 | Lockout thresholds | **5 failures in 15 minutes** |
| Q4 | Dev origins | **Yes:** `http://localhost:5173` plus the API's own origin |
| Q5 | Should `/me` return the email? | **Yes** |
