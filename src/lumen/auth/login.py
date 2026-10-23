"""Login with rate limiting: combines AuthService and LoginRateLimiter.

Callers must commit the transaction even when this raises
InvalidCredentialsError: the failed attempt has to be persisted, or the
rate limit would never trigger.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from lumen.auth.rate_limit import LoginRateLimiter
from lumen.auth.service import AuthError, AuthService, InvalidCredentialsError, IssuedSession


class TooManyAttemptsError(AuthError):
    def __init__(self, retry_after: timedelta) -> None:
        super().__init__("Too many login attempts; try again later")
        self.retry_after = retry_after


def login_with_rate_limit(
    db: Session,
    auth: AuthService,
    limiter: LoginRateLimiter,
    email: str,
    password: str,
    now: datetime,
) -> IssuedSession:
    retry_after = limiter.retry_after(db, email, now)
    if retry_after is not None:
        # Refused before checking the password, so the right password can't
        # be confirmed during a lockout, and the refusal isn't recorded.
        raise TooManyAttemptsError(retry_after)
    try:
        issued = auth.login(db, email, password, now)
    except InvalidCredentialsError:
        limiter.record(db, email, succeeded=False, now=now)
        raise
    limiter.record(db, email, succeeded=True, now=now)
    return issued
