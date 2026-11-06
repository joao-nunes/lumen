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
CHANGE_LIMIT = "src/lumen/auth/password_change.py"

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
            "    # Added last, so it runs outermost: requests the guard refuses get the headers too.\n"
            "    app.add_middleware(SecurityHeadersMiddleware)\n",
            "    app.add_middleware(SecurityHeadersMiddleware)\n"
            "    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)\n",
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
            "(self.session_name, session_token, True),",
            "(self.session_name, session_token, False),",
        ),
        Mutant(
            API + "cookies.py",
            "SameSite=Lax instead of Strict",
            'samesite="strict",\n            )\n',
            'samesite="lax",\n            )\n',
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
