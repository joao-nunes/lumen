"""Mutation check: does the test suite catch deliberate, realistic bugs?

Each mutant replaces one exact snippet of source (or migration) code with a
plausible bug. For each mutant, the runner recreates the test database, runs
the full test suite, and restores the file, even on Ctrl-C.

Verdicts:
- CAUGHT: at least one test failed.
- SURVIVED: the suite passed, so no test guards this behaviour.
- INVALID: only setup errors and no failures, so the mutant broke the harness
  rather than showing that a test guards the behaviour.

Usage: uv run python scripts/mutate.py [group ...]   (default: every group)

When code changes, a snippet may stop matching. The runner checks every
snippet before it starts and stops if one doesn't match exactly once; update
the mutant to match the new code.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, make_url, text

from lumen.config import get_settings


@dataclass(frozen=True)
class Mutant:
    path: str
    name: str
    old: str
    new: str


SERVICE = "src/lumen/auth/service.py"
PASSWORDS = "src/lumen/auth/passwords.py"
RLS_MIGRATION = (
    "migrations/versions/2026_10_23_1742-3d3fd70e14a1_app_and_auth_roles_with_row_level_.py"
)
API = "src/lumen/api/"
REPOSITORY = "src/lumen/db/repository.py"
CHECKIN = "src/lumen/domain/checkin.py"
CONTEXT = "src/lumen/domain/context.py"
CONTEXT_MIGRATION = "migrations/versions/2026_11_13_1500-0b5d619b7c88_personal_context.py"
VOLUNTEERED_MIGRATION = "migrations/versions/2026_11_13_1200-a15cf43a3feb_volunteered_scores.py"
CHANGE_LIMIT = "src/lumen/auth/password_change.py"
EVENT_LOG = API + "event_log.py"
MIDDLEWARE = API + "middleware.py"
OLLAMA = "src/lumen/suggestions/ollama.py"
ROUTES_CHECKINS = API + "routes/checkins.py"
ROUTES_CONTEXT = API + "routes/context.py"
SUGGESTION = "src/lumen/suggestions/model.py"
EVALUATION = "src/lumen/suggestions/evaluation.py"
PROMPT = "src/lumen/suggestions/prompt.py"
PROMPT_TEXT = "src/lumen/suggestions/prompts/checkin_extraction_v3.txt"
DIMENSION_ANCHORS = "src/lumen/domain/dimensions.py"
LOG_MIDDLEWARE = (
    "    app.add_middleware(RequestLogMiddleware, log=EventLog(clock) if log is None else log)\n"
)

GROUPS: dict[str, list[Mutant]] = {
    "auth": [
        Mutant(
            SERVICE,
            "skip dummy verification for unknown email",
            "            self.passwords.verify_dummy(password)\n            raise InvalidCredentialsError()\n",
            "            raise InvalidCredentialsError()\n",
        ),
        Mutant(
            SERVICE,
            "don't revoke sessions on password change",
            "        self.revoke_all_sessions(db, user_id)\n        return self._issue",
            "        return self._issue",
        ),
        Mutant(
            SERVICE,
            "ignore idle timeout",
            "or now >= session.last_seen_at + self.policy.idle_timeout",
            "",
        ),
        Mutant(SERVICE, "ignore absolute timeout", "now >= session.expires_at or ", ""),
        Mutant(
            SERVICE,
            "touch last_seen on every request",
            "if now - session.last_seen_at >= self.policy.touch_interval:",
            "if True:",
        ),
        Mutant(
            SERVICE,
            "rehash bumps updated_at",
            "                    updated_at=PasswordCredential.updated_at,\n",
            "",
        ),
        Mutant(
            SERVICE,
            "change_password skips current-password check",
            "        if not self.passwords.verify(credential.password_hash, current_password).valid:\n"
            "            raise InvalidCredentialsError()\n",
            "",
        ),
        Mutant(
            SERVICE,
            "login doesn't issue a real session",
            "        return self._issue(db, user_id, now)\n\n    def resolve",
            "        return IssuedSession(user_id, 'x', now)\n\n    def resolve",
        ),
        Mutant(
            SERVICE,
            "change_password skips policy",
            "        check_policy(new_password, email=user.email)\n",
            "",
        ),
        Mutant(
            SERVICE,
            "register doesn't map duplicate email",
            '                raise EmailTakenError("An account with this email already exists") from exc\n',
            "                pass\n",
        ),
        Mutant(
            SERVICE,
            "purge ignores idle sessions",
            "                    AuthSession.last_seen_at <= now - self.policy.idle_timeout,\n",
            "",
        ),
        Mutant(
            SERVICE,
            "logout deletes all sessions",
            "            db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))",
            "            db.execute(delete(AuthSession))",
        ),
        Mutant(
            PASSWORDS, "no max length", "    if len(password) > MAX_LENGTH:\n", "    if False:\n"
        ),
        Mutant(
            PASSWORDS,
            "length counts bytes",
            "    if len(password) < MIN_LENGTH:",
            "    if len(password.encode()) < MIN_LENGTH:",
        ),
        Mutant(
            PASSWORDS,
            "no unicode normalization",
            '    return unicodedata.normalize("NFKC", password)',
            "    return password",
        ),
        Mutant(
            PASSWORDS,
            "email context ignored",
            "            words.append(local_part)",
            "            pass",
        ),
        Mutant(
            PASSWORDS,
            "weaker production params",
            "PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)",
            "PasswordHasher(time_cost=1)",
        ),
        Mutant(
            "src/lumen/auth/policy.py",
            "no timeout consistency check",
            '            raise ValueError("Require 0 < touch_interval < idle_timeout <= absolute_timeout")',
            "            pass",
        ),
    ],
    "rls": [
        Mutant(
            "src/lumen/db/scope.py",
            "scope survives its transaction (is_local=False)",
            "str(user_id), True)",
            "str(user_id), False)",
        ),
        Mutant(
            "src/lumen/db/scope.py",
            "user_transaction doesn't scope",
            "        scope_to_user(session, user_id)\n",
            "",
        ),
        Mutant(
            RLS_MIGRATION,
            "policy lets every row through",
            "            USING ({owner_column} = (SELECT current_app_user_id()))",
            "            USING (true)",
        ),
        Mutant(
            RLS_MIGRATION,
            "policy accepts writes for anyone",
            "            WITH CHECK ({owner_column} = (SELECT current_app_user_id()))",
            "            WITH CHECK (true)",
        ),
        Mutant(
            RLS_MIGRATION,
            "no NULLIF on empty setting",
            "NULLIF(current_setting('lumen.user_id', true), '')::uuid",
            "current_setting('lumen.user_id', true)::uuid",
        ),
        Mutant(
            RLS_MIGRATION,
            "RLS not forced",
            '        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")\n',
            "",
        ),
        Mutant(RLS_MIGRATION, "users table not protected", '[("users", "id")] + ', ""),
        Mutant(
            RLS_MIGRATION,
            "checkin_tags not protected",
            'USER_DATA_TABLES = ("checkins", "checkin_scores", "tags", "checkin_tags")',
            'USER_DATA_TABLES = ("checkins", "checkin_scores", "tags")',
        ),
        Mutant(
            RLS_MIGRATION,
            "app role can read auth schema",
            '    op.execute(f"GRANT USAGE ON SCHEMA auth TO {AUTH_ROLE}")',
            '    op.execute(f"GRANT USAGE ON SCHEMA auth TO {AUTH_ROLE}, {APP_ROLE}")\n'
            '    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA auth TO {APP_ROLE}")',
        ),
        Mutant(
            RLS_MIGRATION,
            "auth role can read user data",
            '    op.execute(f"GRANT SELECT, INSERT ON users TO {AUTH_ROLE}")',
            '    op.execute(f"GRANT SELECT, INSERT ON users TO {AUTH_ROLE}")\n'
            '    op.execute(f"GRANT SELECT ON checkins TO {AUTH_ROLE}")',
        ),
        Mutant(
            RLS_MIGRATION,
            "auth role missing session DELETE",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.sessions",
            "GRANT SELECT, INSERT, UPDATE ON auth.sessions",
        ),
        Mutant(
            RLS_MIGRATION,
            "app role missing tag INSERT",
            "GRANT SELECT, INSERT ON tags TO",
            "GRANT SELECT ON tags TO",
        ),
        Mutant(
            "src/lumen/db/repository.py",
            "repository ignores user (app-level filter)",
            "            models.Checkin.user_id == user_id,\n",
            "",
        ),
        Mutant(
            "src/lumen/db/repository.py",
            "repository ignores date range",
            "            models.Checkin.local_date.between(start, end),\n",
            "",
        ),
    ],
    "http": [
        Mutant(
            API + "app.py",
            "security headers not installed",
            "    app.add_middleware(SecurityHeadersMiddleware)\n",
            "",
        ),
        Mutant(
            API + "app.py",
            "security headers inside the request guard",
            "    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)\n"
            "    # Outside the guard, to log what it refuses; inside the headers, so a crash's 500 gets them.\n"
            "    app.add_middleware(RequestLogMiddleware, log=EventLog(clock) if log is None else log)\n"
            "    # Added last, so it runs outermost: requests the guard refuses get the headers too.\n"
            "    app.add_middleware(SecurityHeadersMiddleware)\n",
            "    app.add_middleware(SecurityHeadersMiddleware)\n"
            "    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)\n"
            "    app.add_middleware(RequestLogMiddleware, log=EventLog(clock) if log is None else log)\n",
        ),
        Mutant(
            API + "middleware.py",
            "inline script allowed by the CSP",
            """\"script-src 'self'\",""",
            """\"script-src 'self' 'unsafe-inline'\",""",
        ),
        Mutant(
            API + "middleware.py",
            "CSP lets script contact any site",
            """\"connect-src 'self'\",""",
            """\"connect-src *\",""",
        ),
        Mutant(
            API + "middleware.py",
            "API responses may be stored",
            '''headers["Cache-Control"] = "no-store"''',
            "pass",
        ),
        Mutant(
            API + "middleware.py",
            "everything marked no-store",
            """if scope["path"].startswith("/api/"):""",
            "if True:",
        ),
        Mutant(
            API + "app.py",
            "API docs routes left on",
            "docs_url=None, redoc_url=None, openapi_url=None",
            "",
        ),
        Mutant(
            API + "app.py",
            "any directory served as the web app",
            'if not (settings.web_dist / "index.html").is_file():',
            "if False:",
        ),
        Mutant(
            API + "web.py",
            "unknown API paths answered with the web app",
            'if path == "api" or path.startswith("api/"):',
            "if False:",
        ),
        Mutant(
            API + "web.py",
            "browser routes not answered with the web app",
            'return await super().get_response("index.html", scope)',
            "raise",
        ),
        Mutant(
            API + "app.py",
            "web app mounted before the API routes",
            "    app.include_router(auth_router)\n",
            '    if settings.web_dist is not None:\n        app.mount("/", WebApp(directory=settings.web_dist, html=True))\n    app.include_router(auth_router)\n',
        ),
        Mutant(
            API + "middleware.py",
            "origin check disabled",
            "if origin is not None and origin not in self._allowed_origins | {own_origin}:",
            "if False:",
        ),
        Mutant(
            API + "middleware.py",
            "JSON-only check disabled",
            'if _has_body(request) and _media_type(request) != "application/json":',
            "if False:",
        ),
        Mutant(
            API + "dependencies.py",
            "CSRF check disabled",
            "    if request.method in UNSAFE_METHODS and not container.cookies.csrf_matches(",
            "    if False and not container.cookies.csrf_matches(",
        ),
        Mutant(
            API + "cookies.py",
            "any CSRF header accepted",
            "return header is not None and hmac.compare_digest(self.csrf_token(session_token), header)",
            "return header is not None",
        ),
        Mutant(
            API + "cookies.py",
            "session cookie readable by JS",
            "self._set(response, self.session_name, session_token, httponly=True)",
            "self._set(response, self.session_name, session_token, httponly=False)",
        ),
        Mutant(
            API + "cookies.py",
            "SameSite=Lax instead of Strict",
            'samesite="strict",\n        )\n',
            'samesite="lax",\n        )\n',
        ),
        Mutant(
            API + "cookies.py",
            "no __Host- prefix",
            'prefix = "__Host-" if secure else ""',
            'prefix = ""',
        ),
        Mutant(
            API + "cookies.py",
            "deletion without Secure (ignored by browsers)",
            'name, path="/", secure=self._secure, httponly=httponly, samesite="strict"',
            'name, path="/", secure=False, httponly=httponly, samesite="strict"',
        ),
        Mutant(
            API + "routes/auth.py",
            "failed attempt not committed",
            "        db.commit()  # the failed attempt must persist, or the rate limit never triggers\n",
            "",
        ),
        Mutant(
            API + "routes/auth.py",
            "no session rotation on login",
            "        raise\n    _end_previous_session(request, container, db)\n",
            "        raise\n",
        ),
        Mutant(
            API + "routes/auth.py",
            "no session rotation on register",
            "container.clock())\n    _end_previous_session(request, container, db)\n",
            "container.clock())\n",
        ),
        Mutant(
            API + "routes/auth.py",
            "stale CSRF cookie not repaired",
            "        cookies.set_csrf(response, user.session_token)\n",
            "        pass\n",
        ),
        Mutant(
            API + "routes/auth.py",
            "CSRF cookie reissued on every read",
            "    if not cookies.csrf_matches(user.session_token, request.cookies.get(cookies.csrf_name)):\n",
            "    if True:\n",
        ),
        Mutant(
            API + "errors.py",
            "routing failures keep FastAPI's shape",
            "    app.add_exception_handler(HTTPException, _http_error)\n",
            "",
        ),
        Mutant(
            API + "errors.py",
            "405 loses its Allow header",
            "exc.detail, dict(exc.headers or {}))",
            "exc.detail)",
        ),
        Mutant(
            API + "routes/auth.py",
            "register doesn't log in",
            "    container.cookies.set(response, issued.token)\n    return Registered(user_id=user_id)",
            "    return Registered(user_id=user_id)",
        ),
        Mutant(
            API + "dependencies.py",
            "401 doesn't clear cookies",
            'raise ApiError(401, "not_authenticated", "Not logged in", clear_session=True)',
            'raise ApiError(401, "not_authenticated", "Not logged in")',
        ),
        Mutant(
            API + "dependencies.py",
            "data session not scoped to user",
            "    with user_transaction(container.app_sessions, user.user_id) as db:\n        yield db",
            "    with container.app_sessions() as db:\n        yield db",
        ),
        Mutant(
            "src/lumen/auth/login.py",
            "correct password accepted during lockout",
            "    if retry_after is not None:\n"
            "        # Refused before checking the password, so the right password can't\n"
            "        # be confirmed during a lockout, and the refusal isn't recorded.\n"
            "        raise TooManyAttemptsError(retry_after)\n"
            "    try:\n"
            "        issued = auth.login(db, email, password, now)\n"
            "    except InvalidCredentialsError:\n",
            "    try:\n"
            "        issued = auth.login(db, email, password, now)\n"
            "    except InvalidCredentialsError:\n"
            "        if retry_after is not None:\n"
            "            raise TooManyAttemptsError(retry_after) from None\n",
        ),
        Mutant(
            "src/lumen/auth/login.py",
            "refused attempts recorded (lockout extends)",
            "        raise TooManyAttemptsError(retry_after)",
            "        limiter.record(db, email, succeeded=False, now=now)\n"
            "        db.commit()\n        raise TooManyAttemptsError(retry_after)",
        ),
        Mutant(
            "src/lumen/auth/rate_limit.py",
            "success doesn't reset the count",
            "    if last_success is not None and last_success > since:\n        since = last_success\n",
            "",
        ),
        Mutant(
            "src/lumen/auth/rate_limit.py",
            "unlock time from newest failure",
            "unlocks_at = failures[len(failures) - policy.max_failures] + policy.window",
            "unlocks_at = failures[-1] + policy.window",
        ),
        Mutant(
            "src/lumen/auth/rate_limit.py",
            "off-by-one threshold",
            "if len(failures) < policy.max_failures:",
            "if len(failures) <= policy.max_failures:",
        ),
        # Spec 004: password change limit.
        Mutant(
            CHANGE_LIMIT,
            "password change limit not checked",
            "    if retry_after is not None:\n"
            "        # Refused before checking the password, so the right password can't\n"
            "        # be confirmed during a lockout, and the refusal isn't recorded.\n"
            "        raise TooManyAttemptsError(retry_after)\n",
            "",
        ),
        Mutant(
            CHANGE_LIMIT,
            "correct password accepted during a password change lockout",
            "    if retry_after is not None:\n"
            "        # Refused before checking the password, so the right password can't\n"
            "        # be confirmed during a lockout, and the refusal isn't recorded.\n"
            "        raise TooManyAttemptsError(retry_after)\n"
            "    try:\n"
            "        issued = auth.change_password(db, user_id, current_password, new_password, now)\n"
            "    except InvalidCredentialsError:\n",
            "    try:\n"
            "        issued = auth.change_password(db, user_id, current_password, new_password, now)\n"
            "    except InvalidCredentialsError:\n"
            "        if retry_after is not None:\n"
            "            raise TooManyAttemptsError(retry_after) from None\n",
        ),
        Mutant(
            API + "routes/auth.py",
            "failed password change not committed",
            "        db.commit()  # the failed change must persist, or the rate limit never triggers\n",
            "",
        ),
        Mutant(
            CHANGE_LIMIT,
            "refused password changes recorded (lockout extends)",
            "        raise TooManyAttemptsError(retry_after)",
            "        limiter.record(db, user_id, succeeded=False, now=now)\n"
            "        db.commit()\n        raise TooManyAttemptsError(retry_after)",
        ),
        Mutant(
            CHANGE_LIMIT,
            "successful password change doesn't reset the count",
            "    limiter.record(db, user_id, succeeded=True, now=now)\n",
            "",
        ),
        Mutant(
            CHANGE_LIMIT,
            "weak new password counted as a failure",
            "    except InvalidCredentialsError:\n"
            "        limiter.record(db, user_id, succeeded=False, now=now)\n",
            "    except Exception:\n"
            "        limiter.record(db, user_id, succeeded=False, now=now)\n"
            "        db.commit()\n",
        ),
        Mutant(
            CHANGE_LIMIT,
            "weak new password counted as a success",
            "        limiter.record(db, user_id, succeeded=False, now=now)\n        raise\n",
            "        limiter.record(db, user_id, succeeded=False, now=now)\n        raise\n"
            "    except Exception:\n"
            "        limiter.record(db, user_id, succeeded=True, now=now)\n"
            "        db.commit()\n        raise\n",
        ),
        Mutant(
            CHANGE_LIMIT,
            "password change row lock removed",
            "        .with_for_update()\n",
            "",
        ),
        Mutant(
            CHANGE_LIMIT,
            "password change count read before taking the lock",
            "    db.execute(\n"
            "        select(PasswordCredential.user_id)\n"
            "        .where(PasswordCredential.user_id == user_id)\n"
            "        .with_for_update()\n"
            "    )\n"
            "    retry_after = limiter.retry_after(db, user_id, now)\n",
            "    retry_after = limiter.retry_after(db, user_id, now)\n"
            "    db.execute(\n"
            "        select(PasswordCredential.user_id)\n"
            "        .where(PasswordCredential.user_id == user_id)\n"
            "        .with_for_update()\n"
            "    )\n",
        ),
        Mutant(
            "src/lumen/auth/rate_limit.py",
            "other users' failures counted",
            ".where(key, attempts.succeeded.is_(False),",
            ".where(attempts.succeeded.is_(False),",
        ),
        Mutant(
            "src/lumen/auth/login.py",
            "successful login resets the password change count",
            "    limiter.record(db, email, succeeded=True, now=now)\n",
            "    limiter.record(db, email, succeeded=True, now=now)\n"
            "    from lumen.auth.models import PasswordChangeAttempt\n\n"
            "    db.add(PasswordChangeAttempt(user_id=issued.user_id, attempted_at=now, succeeded=True))\n",
        ),
        Mutant(
            "src/lumen/auth/rate_limit.py",
            "failed logins count towards the password change limit",
            "        key = PasswordChangeAttempt.user_id == user_id\n",
            "        from lumen.db.models import User\n\n"
            "        email = db.scalar(select(User.email).where(User.id == user_id))\n"
            "        locked = _retry_after(\n"
            "            db, self.policy, LoginAttempt, LoginAttempt.email == email, now\n"
            "        )\n"
            "        if locked is not None:\n"
            "            return locked\n"
            "        key = PasswordChangeAttempt.user_id == user_id\n",
        ),
        Mutant(
            "migrations/versions/2026_11_06_1200-7c41e9a2d6b3_password_change_attempts.py",
            "password change attempts editable by the auth role",
            "GRANT SELECT, INSERT ON auth.password_change_attempts",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.password_change_attempts",
        ),
    ],
    "logging": [
        Mutant(
            EVENT_LOG,
            "exception message on the crash line",
            '                        "frames": _lumen_frames(exc.__traceback__),\n',
            '                        "frames": _lumen_frames(exc.__traceback__),\n'
            '                        "message": str(exc),\n',
        ),
        Mutant(
            EVENT_LOG,
            "method logged as received",
            '"method": method if method in METHODS else "OTHER",',
            '"method": method,',
        ),
        Mutant(
            EVENT_LOG,
            "failed write not swallowed: request line",
            '        with suppress(Exception):\n            self._write(\n                self._line(\n                    {\n                        "event": "request",',
            '        if True:\n            self._write(\n                self._line(\n                    {\n                        "event": "request",',
        ),
        Mutant(
            EVENT_LOG,
            "failed write not swallowed: crash line",
            '        with suppress(Exception):\n            self._write(\n                self._line(\n                    {\n                        "event": "crash",',
            '        if True:\n            self._write(\n                self._line(\n                    {\n                        "event": "crash",',
        ),
        Mutant(
            EVENT_LOG,
            "frames from outside Lumen logged",
            'if module.startswith("lumen.") and module != _MIDDLEWARE:',
            "if module != _MIDDLEWARE:",
        ),
        Mutant(
            EVENT_LOG,
            "middleware frames logged",
            'if module.startswith("lumen.") and module != _MIDDLEWARE:',
            'if module.startswith("lumen."):',
        ),
        Mutant(
            MIDDLEWARE,
            "raw path logged instead of the route's template",
            "route=route.path if isinstance(route, APIRoute) else None,",
            'route=scope["path"],',
        ),
        Mutant(
            MIDDLEWARE,
            "query string added to the route",
            "route=route.path if isinstance(route, APIRoute) else None,",
            "route=f\"{route.path}?{scope['query_string'].decode()}\" if isinstance(route, APIRoute) else None,",
        ),
        Mutant(
            MIDDLEWARE,
            "headers and cookies added to the route",
            "route=route.path if isinstance(route, APIRoute) else None,",
            "route=f\"{route.path}#{scope['headers']}\" if isinstance(route, APIRoute) else None,",
        ),
        Mutant(
            API + "dependencies.py",
            "user ID added to the route",
            "    return Authenticated(user_id=user_id, session_token=token)\n",
            '    request.scope["route"].path = f"/api/{user_id}"\n'
            "    return Authenticated(user_id=user_id, session_token=token)\n",
        ),
        Mutant(
            MIDDLEWARE,
            "client's X-Request-ID trusted",
            "request_id = uuid.uuid4().hex",
            'request_id = dict(scope["headers"]).get(b"x-request-id", uuid.uuid4().hex.encode()).decode()',
        ),
        Mutant(
            MIDDLEWARE,
            "request ID shared between requests",
            "request_id = uuid.uuid4().hex",
            'request_id = "0" * 32',
        ),
        Mutant(
            MIDDLEWARE,
            "request ID not returned to the client",
            '                MutableHeaders(scope=message)["X-Request-ID"] = request_id\n',
            "",
        ),
        Mutant(
            MIDDLEWARE,
            "unknown error code logged as received",
            'return code if isinstance(code, str) and code in ERROR_CODES else "unknown"',
            "return str(code)",
        ),
        Mutant(
            MIDDLEWARE,
            "crash re-raised after logging",
            "                        scope, receive, send_with_id\n                    )\n",
            "                        scope, receive, send_with_id\n                    )\n            raise\n",
        ),
        Mutant(
            MIDDLEWARE,
            "crash caught but not logged",
            "            self._log.crash(request_id, exc)\n",
            "",
        ),
        Mutant(
            MIDDLEWARE,
            "crash caught but no 500 sent",
            "            if status is None:\n",
            "            if False:\n",
        ),
        Mutant(
            MIDDLEWARE,
            "500 sent even after the response started",
            "            if status is None:\n",
            "            if True:\n",
        ),
        Mutant(
            MIDDLEWARE,
            "cancellation treated as a crash",
            "        except Exception as exc:\n            crashed = True",
            "        except BaseException as exc:\n            crashed = True",
        ),
        Mutant(
            MIDDLEWARE,
            "failure sending the 500 reaches uvicorn",
            '                with suppress(Exception):\n                    await error_response(500, "internal_error", "Something went wrong")(\n                        scope, receive, send_with_id\n                    )\n',
            '                await error_response(500, "internal_error", "Something went wrong")(\n                    scope, receive, send_with_id\n                )\n',
        ),
        Mutant(
            MIDDLEWARE,
            "startup and shutdown not passed through",
            '        if scope["type"] != "http":\n            await self._app(scope, receive, send)\n            return\n\n        request_id',
            "        request_id",
        ),
        Mutant(
            MIDDLEWARE,
            "error buffer unbounded",
            "[: MAX_ERROR_BODY - len(error_body)])",
            ")",
        ),
        Mutant(
            MIDDLEWARE,
            "redirects treated as errors",
            "if final >= 400\n",
            "if final >= 300\n",
        ),
        Mutant(
            MIDDLEWARE,
            "paths like /apiary logged as API",
            'if scope["path"] == "/api" or scope["path"].startswith("/api/"):',
            'if scope["path"].startswith("/api"):',
        ),
        Mutant(
            API + "errors.py",
            "a code missing from the list",
            '        "not_authenticated",\n',
            "",
        ),
        Mutant(
            EVENT_LOG,
            "frames outermost first",
            "return frames[::-1]",
            "return frames",
        ),
        Mutant(
            MIDDLEWARE,
            "pages and assets logged",
            'if scope["path"] == "/api" or scope["path"].startswith("/api/"):',
            "if True:",
        ),
        Mutant(
            API + "app.py",
            "log middleware outside the security headers",
            LOG_MIDDLEWARE
            + "    # Added last, so it runs outermost: requests the guard refuses get the headers too.\n"
            "    app.add_middleware(SecurityHeadersMiddleware)\n",
            "    app.add_middleware(SecurityHeadersMiddleware)\n" + LOG_MIDDLEWARE,
        ),
        Mutant(
            API + "app.py",
            "log middleware inside the request guard",
            "    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)\n"
            "    # Outside the guard, to log what it refuses; inside the headers, so a crash's 500 gets them.\n"
            + LOG_MIDDLEWARE,
            LOG_MIDDLEWARE
            + "    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)\n",
        ),
    ],
    "suggestions": [
        Mutant(
            ROUTES_CHECKINS,
            "the endpoint saves the suggestion",
            "    return SuggestionOut(scores=dict(valid.scores), tags=sorted(valid.tags))\n",
            "    with user_transaction(container.app_sessions, user.user_id) as db:\n"
            "        save_checkin(db, user.user_id, Checkin(recorded_at=container.clock(), local_date=local_date, scores=dict(valid.scores)))\n"
            "    return SuggestionOut(scores=dict(valid.scores), tags=sorted(valid.tags))\n",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "a transaction stays open during the model call",
            "        used = [name for name, _ in tag_usage(db, user.user_id)]\n"
            "        context = get_context(db, user.user_id)  # spec 010; Tier 0, so only the local model sees it\n"
            "    # All seven, whatever the day asks: a score the day didn't ask for is volunteered (spec 008).\n"
            "    asked = tuple(Dimension)\n"
            "    offered = offered_tags(used)\n"
            "    reply = container.suggestions.suggest(body.text, asked, offered, context)\n",
            "        used = [name for name, _ in tag_usage(db, user.user_id)]\n"
            "        context = get_context(db, user.user_id)\n"
            "        asked = tuple(Dimension)\n"
            "        offered = offered_tags(used)\n"
            "        reply = container.suggestions.suggest(body.text, asked, offered, context)\n",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "the model's reply isn't checked again",
            "    return SuggestionOut(scores=dict(valid.scores), tags=sorted(valid.tags))\n",
            "    return SuggestionOut(scores=dict(reply.scores), tags=sorted(reply.tags))\n",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "only the day's dimensions asked (spec 008)",
            "    asked = tuple(Dimension)\n",
            "    asked = dimensions_for(local_date)\n",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "the person's own tags not offered",
            "offered = offered_tags(used)",
            "offered = offered_tags(())",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "the route builds its own tag order",
            "offered = offered_tags(used)",
            "offered = tuple(dict.fromkeys([*offered_tags(()), *used]))",
        ),
        Mutant(
            SUGGESTION,
            "a tag offered twice",
            "tuple(dict.fromkeys([*used, *STARTER_TAGS]))",
            "(*used, *STARTER_TAGS)",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "the text isn't trimmed",
            "StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)",
            "StringConstraints(min_length=1, max_length=2000)",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "any length of text allowed",
            "StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)",
            "StringConstraints(strip_whitespace=True, min_length=1)",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "any day allowed",
            "    check_editable(local_date, container.clock())\n    if container.suggestions is None:",
            "    if container.suggestions is None:",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "no model configured crashes",
            "    if container.suggestions is None:\n        raise SuggestionsUnavailableError\n",
            "",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "mode ignored on save",
            "        mode=body.mode,\n",
            "",
        ),
        Mutant(
            API + "errors.py",
            "an unavailable model crashes instead",
            '    SuggestionsUnavailableError: (503, "suggestions_unavailable"),\n',
            "",
        ),
        Mutant(
            API + "errors.py",
            "validation errors repeat the input",
            'return error_response(422, "invalid_request", "The request is invalid")',
            'return error_response(422, "invalid_request", str(exc))',
        ),
        Mutant(
            API + "app.py",
            "the configured model is never used",
            "    if settings.ollama_model is None:\n        return None\n",
            "    return None\n",
        ),
        Mutant(
            OLLAMA,
            "any host allowed",
            'if parts.scheme not in ("http", "https") or not _is_loopback(parts.hostname):',
            'if parts.scheme not in ("http", "https"):',
        ),
        Mutant(
            OLLAMA,
            "host checked by its prefix",
            '    if host == "localhost":\n',
            '    if host is not None and host.startswith(("localhost", "127.")):\n',
        ),
        Mutant(
            OLLAMA,
            "cloud models allowed",
            "    if model is not None and _CLOUD_MODEL.search(model):\n",
            "    if False:\n",
        ),
        Mutant(
            API + "app.py",
            "app starts without checking the settings",
            "    check_local_only(settings.ollama_url, settings.ollama_model)\n",
            "",
        ),
        Mutant(OLLAMA, "proxy settings followed", "trust_env=False,", "trust_env=True,"),
        Mutant(
            OLLAMA,
            "redirects followed",
            "follow_redirects=False,",
            "follow_redirects=True,",
        ),
        Mutant(
            OLLAMA,
            "status not checked",
            "            response.raise_for_status()\n",
            "",
        ),
        Mutant(
            OLLAMA,
            "the original error stays attached",
            "raise SuggestionsUnavailableError from None",
            "raise SuggestionsUnavailableError",
        ),
        Mutant(
            OLLAMA,
            "quote not checked against the note",
            "if isinstance(quote, str) and (found := _normalized(quote)) and found in note:",
            "if isinstance(quote, str) and (found := _normalized(quote)):",
        ),
        Mutant(
            OLLAMA,
            "an empty quote counts as evidence",
            "if isinstance(quote, str) and (found := _normalized(quote)) and found in note:",
            "if isinstance(quote, str) and ((found := _normalized(quote)) in note):",
        ),
        Mutant(
            OLLAMA,
            "quote compared exactly",
            "and found in note:",
            "and quote in text:",
        ),
        Mutant(
            OLLAMA,
            "scores written as text dropped",
            "scores[key] = int(score) if isinstance(score, str) and score.isdecimal() else score",
            "scores[key] = score",
        ),
        Mutant(
            OLLAMA,
            "only a reply that is purely JSON accepted",
            'reply, _ = json.JSONDecoder().raw_decode(content, content.index("{"))',
            "reply = json.loads(content)",
        ),
        Mutant(OLLAMA, "temperature left to the default", '"temperature": 0, ', ""),
        Mutant(
            OLLAMA,
            "the note sent inside the system prompt",
            '{"role": "user", "content": text},',
            '{"role": "user", "content": "note"},',
        ),
        Mutant(
            SUGGESTION,
            "scores above the scale kept",
            "and SCALE_MIN <= value <= SCALE_MAX",
            "",
        ),
        Mutant(
            SUGGESTION,
            "true accepted as a score",
            "type(value := scores.get(dimension.value)) is int",
            "isinstance(value := scores.get(dimension.value), int)",
        ),
        Mutant(
            SUGGESTION,
            "unlisted tags kept",
            "if isinstance(tag, str) and tag in offered",
            "if isinstance(tag, str)",
        ),
        Mutant(PROMPT_TEXT, "prompt wording changed unmeasured", " Never give advice.", ""),
        Mutant(
            DIMENSION_ANCHORS,
            "anchor wording changed unmeasured",
            "Deep, sustained focus",
            "Deep focus",
        ),
        Mutant(
            PROMPT,
            "polarity wording changed unmeasured",
            "Higher means MORE of it, which is worse.",
            "Higher is worse.",
        ),
        Mutant(
            OLLAMA,
            "client sends a different prompt from the measured one",
            "system = checkin_extraction_prompt(dimensions, tags, context)",
            "system = checkin_extraction_prompt(dimensions, (), context)",
        ),
        Mutant(
            EVALUATION,
            "dimensions not asked still measured",
            "for dimension in outcome.asked:",
            "for dimension in Dimension:",
        ),
        Mutant(
            PROMPT,
            "prompt v1 used again",
            'PROMPT_NAME = "checkin_extraction_v3"',
            'PROMPT_NAME = "checkin_extraction_v1"',
        ),
        Mutant(
            PROMPT,
            "measured for the day's dimensions, not all seven",
            "return (tuple(Dimension), offered_tags(INVENTED_TAGS), context)",
            "return (tuple(Dimension)[:5], offered_tags(INVENTED_TAGS), context)",
        ),
        Mutant(
            PROMPT,
            "invented tags not offered",
            "return (tuple(Dimension), offered_tags(INVENTED_TAGS), context)",
            "return (tuple(Dimension), offered_tags(()), context)",
        ),
        # Spec 010: the personal context and the tag bar.
        Mutant(
            ROUTES_CHECKINS,
            "the saved context never reaches the model",
            "reply = container.suggestions.suggest(body.text, asked, offered, context)",
            'reply = container.suggestions.suggest(body.text, asked, offered, "")',
        ),
        Mutant(
            OLLAMA,
            "the client drops the context",
            "system = checkin_extraction_prompt(dimensions, tags, context)",
            "system = checkin_extraction_prompt(dimensions, tags)",
        ),
        Mutant(
            OLLAMA,
            "a quote from the context counts",
            'scores, chosen = _evidenced_scores(reply["dimensions"], text), reply["tags"]',
            'scores, chosen = _evidenced_scores(reply["dimensions"], text + " " + context), reply["tags"]',
        ),
        Mutant(
            PROMPT,
            "the context section shown when there's no context",
            'context_section=_CONTEXT_SECTION.format(context=context) if context else "",',
            "context_section=_CONTEXT_SECTION.format(context=context),",
        ),
        Mutant(
            PROMPT,
            "the hash ignores how a context is shown",
            'return (request_for(""), request_for(MEASURED_CONTEXT))',
            'return (request_for(""), request_for(""))',
        ),
        Mutant(
            EVALUATION,
            "each note measured without its context",
            "for asked, tags, context in (request_for(entry.context),):",
            'for asked, tags, context in (request_for(""),):',
        ),
        Mutant(
            EVALUATION,
            "no bar for tags",
            "        and metrics.tag_precision >= TAG_PRECISION_BAR\n",
            "",
        ),
        Mutant(
            EVALUATION,
            "a run never stops on failures",
            "if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:",
            "if failures_in_a_row >= MAX_FAILURES_IN_A_ROW * 99:",
        ),
        Mutant(
            EVALUATION,
            "a success doesn't reset the failure count",
            "failures_in_a_row = failures_in_a_row + 1 if suggestion is None else 0",
            "failures_in_a_row = failures_in_a_row + 1 if suggestion is None else failures_in_a_row",
        ),
        Mutant(
            SUGGESTION,
            "a person's own tags offered last",
            "[*used, *STARTER_TAGS]",
            "[*STARTER_TAGS, *used]",
        ),
        Mutant(
            EVALUATION,
            "tuning run recorded as the measurement",
            'if split != "test" or not (',
            "if not (",
        ),
        Mutant(
            EVALUATION,
            "recorded though Portuguese missed the bar",
            "meets_bar(english) and meets_bar(portuguese)",
            "meets_bar(english)",
        ),
        Mutant(
            EVALUATION,
            "recorded though English missed the bar",
            "meets_bar(english) and meets_bar(portuguese)",
            "meets_bar(portuguese)",
        ),
        Mutant(
            EVALUATION,
            "a failure counts as a correct blank",
            "left_blank += suggestion is not None and guess is None",
            "left_blank += guess is None",
        ),
        Mutant(
            EVALUATION,
            "within one counted against every addressed dimension",
            "within_one=_ratio(within_one, suggested),",
            "within_one=_ratio(within_one, addressed),",
        ),
        Mutant(
            EVALUATION,
            "coverage always full",
            "coverage=_ratio(suggested, addressed),",
            "coverage=1.0,",
        ),
        Mutant(
            EVALUATION,
            "within one means within two",
            "within_one += distance <= 1",
            "within_one += distance <= 2",
        ),
        Mutant(
            EVALUATION,
            "off by three misses exactly three",
            "off_by_three += distance >= 3",
            "off_by_three += distance > 3",
        ),
        Mutant(
            EVALUATION,
            "dimensions marked either way measured",
            "            if dimension in entry.either:\n                continue\n            guess",
            "            guess",
        ),
        Mutant(
            EVALUATION,
            "the model's loading time counted",
            "times = sorted(o.seconds for o in outcomes[1:])",
            "times = sorted(o.seconds for o in outcomes)",
        ),
        Mutant(
            EVALUATION,
            "the bar ignores coverage",
            "        and metrics.coverage >= COVERAGE_BAR\n",
            "",
        ),
        Mutant(
            EVALUATION,
            "the bar ignores failures on distressing text",
            "        and metrics.distress_failures == 0\n",
            "",
        ),
        Mutant(
            EVALUATION,
            "the blind sheet shows the labels",
            '*[""] * len(Dimension)]',
            "*[entry.scores.get(d, '') for d in Dimension]]",
        ),
        Mutant(
            EVALUATION,
            "the blind sheet includes distressing notes",
            ' and e.category != "distress"',
            "",
        ),
    ],
    "domain": [
        Mutant(
            "src/lumen/domain/checkin.py",
            "naive timestamps allowed",
            '            raise ValueError("recorded_at must be timezone-aware")',
            "            pass",
        ),
        Mutant(
            "src/lumen/domain/checkin.py",
            "tags not normalized",
            '        object.__setattr__(self, "tags", frozenset(normalize_tag(t) for t in self.tags))',
            "        pass",
        ),
        Mutant(
            "src/lumen/domain/checkin.py",
            "scores not validated",
            "            validate_score(value)",
            "            pass",
        ),
        Mutant(
            "src/lumen/domain/dimensions.py",
            "bool accepted as score",
            "    if isinstance(value, bool) or not isinstance(value, int):",
            "    if not isinstance(value, int):",
        ),
        Mutant(
            "src/lumen/domain/dimensions.py",
            "rotation stuck on same dims",
            "    start = (day.toordinal() * per_day) % n",
            "    start = 0",
        ),
    ],
    "checkins": [
        Mutant(
            REPOSITORY,
            "upsert merges scores instead of replacing",
            "    for child in (models.CheckinScore, models.CheckinTag):\n"
            "        session.execute(delete(child).where(child.checkin_id == checkin_id))\n",
            "    session.execute(delete(models.CheckinTag).where(models.CheckinTag.checkin_id == checkin_id))\n"
            "    session.execute(delete(models.CheckinScore).where(models.CheckinScore.checkin_id == checkin_id, models.CheckinScore.dimension.in_(list(checkin.scores))))\n",
        ),
        Mutant(
            REPOSITORY,
            "upsert keeps the old tags",
            "    for child in (models.CheckinScore, models.CheckinTag):\n",
            "    for child in (models.CheckinScore,):\n",
        ),
        Mutant(
            CHECKIN,
            "backfill window one day too long",
            "    first = today_utc - timedelta(days=BACKFILL_DAYS + 1)",
            "    first = today_utc - timedelta(days=BACKFILL_DAYS + 2)",
        ),
        Mutant(
            CHECKIN,
            "future window one day too long",
            "    last = today_utc + timedelta(days=1)",
            "    last = today_utc + timedelta(days=2)",
        ),
        Mutant(
            CHECKIN,
            "core dimensions not required",
            "    if missing:\n        raise MissingCoreDimensionError",
            "    if False:\n        raise MissingCoreDimensionError",
        ),
        Mutant(
            CHECKIN,
            "tag limit off by one",
            "        if len(self.tags) > MAX_TAGS:",
            "        if len(self.tags) > MAX_TAGS + 1:",
        ),
        Mutant(
            "src/lumen/analytics/overview.py",
            "no lookback for the rolling mean",
            "    return summary_start(end) - timedelta(days=ROLLING_WINDOW_DAYS - 1)",
            "    return summary_start(end)",
        ),
        Mutant(
            "src/lumen/analytics/overview.py",
            "rolling mean over a different window",
            "rolling=rolling_mean(series, summary.trend_period, ROLLING_WINDOW_DAYS),",
            "rolling=rolling_mean(series, summary.trend_period, ROLLING_WINDOW_DAYS + 7),",
        ),
        Mutant(
            "src/lumen/api/routes/overview.py",
            "overview ignores the requested end date",
            "dimensions=[_dimension(d, o) for d, o in overview(observations, end).items()],",
            "dimensions=[_dimension(d, o) for d, o in overview(observations, end.replace(day=1)).items()],",
        ),
        Mutant(
            REPOSITORY,
            "tags ordered by name only",
            "        .order_by(uses.desc(), models.Tag.name)",
            "        .order_by(models.Tag.name)",
        ),
        # Spec 010: personal context.
        Mutant(
            ROUTES_CONTEXT,
            "context saved untrimmed",
            "StringConstraints(strip_whitespace=True, max_length=MAX_CONTEXT_LENGTH)",
            "StringConstraints(strip_whitespace=False, max_length=MAX_CONTEXT_LENGTH)",
        ),
        Mutant(
            CONTEXT,
            "context limit one longer",
            "MAX_CONTEXT_LENGTH = 750",
            "MAX_CONTEXT_LENGTH = 751",
        ),
        Mutant(
            REPOSITORY,
            "empty context saved instead of deleted",
            "    if not value:\n",
            "    if False:\n",
        ),
        Mutant(
            REPOSITORY,
            "context read without the user filter",
            "select(models.PersonalContext.text).where(models.PersonalContext.user_id == user_id)",
            "select(models.PersonalContext.text).limit(1)",
        ),
        Mutant(
            CONTEXT_MIGRATION,
            "context table without forced RLS",
            '    op.execute("ALTER TABLE personal_context FORCE ROW LEVEL SECURITY")\n',
            "",
        ),
        Mutant(
            CONTEXT_MIGRATION,
            "context table without the app's grants",
            'op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON personal_context TO {APP_ROLE}")',
            'op.execute(f"GRANT SELECT ON personal_context TO {APP_ROLE}")',
        ),
        # Spec 008: volunteered scores.
        Mutant(
            ROUTES_CHECKINS,
            "every score labelled asked",
            "volunteered=volunteered_for(local_date, scores)",
            "volunteered=frozenset()",
        ),
        Mutant(
            ROUTES_CHECKINS,
            "labelled by today's schedule, not the check-in's day",
            "volunteered=volunteered_for(local_date, scores)",
            "volunteered=volunteered_for(now.date(), scores)",
        ),
        Mutant(
            CHECKIN,
            "asked scores labelled volunteered",
            "frozenset(d for d in scores if d not in asked)",
            "frozenset(d for d in scores if d in asked)",
        ),
        Mutant(
            REPOSITORY,
            "every score stored as volunteered",
            '"volunteered": d in checkin.volunteered,',
            '"volunteered": True,',
        ),
        Mutant(
            REPOSITORY,
            "stored labels not read back",
            "volunteered=frozenset(s.dimension for s in row.scores if s.volunteered),",
            "volunteered=frozenset(),",
        ),
        Mutant(
            REPOSITORY,
            "volunteered scores included in observations",
            "            models.CheckinScore.volunteered.is_(False),\n",
            "",
        ),
        Mutant(
            VOLUNTEERED_MIGRATION,
            "migration's schedule shifted by a day",
            "(c.local_date - DATE '0001-01-01' + 1)",
            "(c.local_date - DATE '0001-01-01' + 2)",
        ),
        Mutant(
            VOLUNTEERED_MIGRATION,
            "migration labels nothing",
            "    op.execute(LABEL_EXISTING)\n",
            "",
        ),
    ],
    "analytics": [
        Mutant(
            "src/lumen/analytics/inference.py",
            "no autocorrelation correction",
            "    return n * (1 - r1) / (1 + r1)",
            "    return float(n)",
        ),
        Mutant(
            "src/lumen/analytics/inference.py",
            "no small-sample bias correction",
            "    return (n * r1 + 1) / (n - 3) if n > 3 else r1",
            "    return r1",
        ),
        Mutant(
            "src/lumen/analytics/inference.py",
            "negative autocorrelation inflates n_eff",
            "    r1 = min(max(r1, 0.0), 0.99)",
            "    r1 = min(r1, 0.99)",
        ),
        Mutant(
            "src/lumen/analytics/direction.py",
            "ignore practical threshold",
            "    if (ci_low > 0 or ci_high < 0) and abs(estimate) >= threshold:",
            "    if ci_low > 0 or ci_high < 0:",
        ),
        Mutant(
            "src/lumen/analytics/direction.py",
            "ignore polarity",
            "    if rising == (polarity is Polarity.HIGHER_IS_BETTER):",
            "    if rising:",
        ),
        Mutant(
            "src/lumen/analytics/series.py",
            "daily means use last value",
            "    return {day: fsum(values) / len(values) for day, values in sorted(by_day.items())}",
            "    return {day: float(values[-1]) for day, values in sorted(by_day.items())}",
        ),
        Mutant(
            "src/lumen/analytics/metrics.py",
            "rolling window off by one day",
            "        day: period_stat(series, DateRange.ending_on(day, window_days), min_points)",
            "        day: period_stat(series, DateRange.ending_on(day, window_days + 1), min_points)",
        ),
        Mutant(
            "src/lumen/analytics/metrics.py",
            "weekly means not clipped to period",
            "        week = DateRange(max(monday, period.start), min(monday + timedelta(days=6), period.end))",
            "        week = DateRange(monday, monday + timedelta(days=6))",
        ),
        Mutant(
            "src/lumen/analytics/metrics.py",
            "previous period wrong",
            "    previous = previous or current.previous()",
            "    previous = previous or current",
        ),
        Mutant(
            "src/lumen/analytics/trends.py",
            "slope per day not per week",
            "    slope = fit.slope * 7",
            "    slope = fit.slope",
        ),
        Mutant(
            "src/lumen/analytics/trends.py",
            "no n_eff guard",
            "    if n_eff < MIN_EFFECTIVE_POINTS:\n"
            "        return Trend(slope, None, None, Direction.INSUFFICIENT_DATA, n, n_eff)",
            "    if False:\n        pass",
        ),
        Mutant(
            "src/lumen/analytics/trends.py",
            "x from index not date",
            "    xs = [float((day - period.start).days) for day in points]",
            "    xs = [float(i) for i, _ in enumerate(points)]",
        ),
        Mutant(
            "src/lumen/analytics/summary.py",
            "summary_start ignores change window",
            "    return min(change_period.previous().start, DateRange.ending_on(end, trend_days).start)",
            "    return DateRange.ending_on(end, trend_days).start",
        ),
    ],
}


def recreate_test_database() -> None:
    """A mutated migration can leave the schema half-built; start every run from empty."""
    url = make_url(get_settings().test_database_url)
    name = url.database
    if name is None or not name.endswith("_test"):
        sys.exit(f"Refusing to recreate {name!r}: the test database name must end in _test")
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    quoted = engine.dialect.identifier_preparer.quote(name)
    with engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {quoted}"))
    engine.dispose()


def run_suite() -> tuple[int, str]:
    recreate_test_database()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    return result.returncode, lines[-1].strip("= ") if lines else result.stderr.strip()


def verdict(returncode: int, summary: str) -> str:
    if returncode == 0:
        return "SURVIVED"
    if returncode == 1 and re.search(r"\d+ failed", summary):
        return "CAUGHT"
    if returncode == 1 and re.search(r"\d+ errors?", summary):
        return "INVALID"
    sys.exit(f"pytest did not run normally (exit code {returncode}): {summary}")


def main(selected: list[str]) -> None:
    unknown = set(selected) - GROUPS.keys()
    if unknown:
        sys.exit(
            f"Unknown group(s): {', '.join(sorted(unknown))}. Choose from {', '.join(GROUPS)}."
        )
    mutants = [m for group in selected or GROUPS for m in GROUPS[group]]

    for m in mutants:
        count = Path(m.path).read_text().count(m.old)
        if count != 1:
            sys.exit(f"Snippet for {m.name!r} occurs {count} times in {m.path}; update the mutant.")

    # A failing baseline would make every mutant look caught.
    code, summary = run_suite()
    if code != 0:
        sys.exit(f"Baseline suite is not green, fix it first: {summary}")
    print(f"Baseline: {summary}\n")

    caught = 0
    for m in mutants:
        path = Path(m.path)
        original = path.read_text()
        try:
            path.write_text(original.replace(m.old, m.new))
            code, summary = run_suite()
        finally:
            path.write_text(original)
        result = verdict(code, summary)
        caught += result == "CAUGHT"
        print(f"{result:<8}  {path.name:<16} {m.name:<46} [{summary}]", flush=True)

    print(f"\n{caught}/{len(mutants)} mutants caught")
    if caught != len(mutants):
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
