"""Password change with rate limiting (spec 004): combines AuthService and its limiter.

Callers must commit the transaction even when this raises
InvalidCredentialsError: the failed attempt has to be persisted, or the
rate limit would never trigger.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lumen.auth.login import TooManyAttemptsError
from lumen.auth.models import PasswordCredential
from lumen.auth.rate_limit import PasswordChangeRateLimiter
from lumen.auth.service import AuthService, InvalidCredentialsError, IssuedSession


def change_password_with_rate_limit(
    db: Session,
    auth: AuthService,
    limiter: PasswordChangeRateLimiter,
    user_id: uuid.UUID,
    current_password: str,
    new_password: str,
    now: datetime,
) -> IssuedSession:
    # Held until the transaction ends. Without it, requests sent together would
    # all read a count below the limit before any failure is recorded.
    db.execute(
        select(PasswordCredential.user_id)
        .where(PasswordCredential.user_id == user_id)
        .with_for_update()
    )
    retry_after = limiter.retry_after(db, user_id, now)
    if retry_after is not None:
        # Refused before checking the password, so the right password can't
        # be confirmed during a lockout, and the refusal isn't recorded.
        raise TooManyAttemptsError(retry_after)
    try:
        issued = auth.change_password(db, user_id, current_password, new_password, now)
    except InvalidCredentialsError:
        limiter.record(db, user_id, succeeded=False, now=now)
        raise
    limiter.record(db, user_id, succeeded=True, now=now)
    return issued
