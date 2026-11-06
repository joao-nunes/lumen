"""Rate limits on guessing a password: at login (spec 001 §2.5) and when changing it (spec 004).

Only failures since the last success, within the window, count. Once
`max_failures` of them exist, attempts are refused until enough of them age
out of the window. Refused attempts are not recorded, so retrying during a
lockout doesn't extend it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from lumen.auth.models import LoginAttempt, PasswordChangeAttempt


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    max_failures: int = 5
    window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.max_failures < 1 or self.window <= timedelta(0):
            raise ValueError("Require max_failures >= 1 and a positive window")


def _retry_after(
    db: Session,
    policy: RateLimitPolicy,
    attempts: type[LoginAttempt] | type[PasswordChangeAttempt],
    key: ColumnElement[bool],
    now: datetime,
) -> timedelta | None:
    last_success = db.scalar(select(func.max(attempts.attempted_at)).where(key, attempts.succeeded))
    since = now - policy.window
    if last_success is not None and last_success > since:
        since = last_success
    failures = db.scalars(
        select(attempts.attempted_at)
        .where(key, attempts.succeeded.is_(False), attempts.attempted_at > since)
        .order_by(attempts.attempted_at)
    ).all()
    if len(failures) < policy.max_failures:
        return None
    # Unlocked once only max_failures - 1 of them remain inside the window.
    unlocks_at = failures[len(failures) - policy.max_failures] + policy.window
    return unlocks_at - now


class LoginRateLimiter:
    def __init__(self, policy: RateLimitPolicy | None = None) -> None:
        self.policy = policy or RateLimitPolicy()

    def retry_after(self, db: Session, email: str, now: datetime) -> timedelta | None:
        """How long `email` is locked out for, or None if it may try now."""
        return _retry_after(db, self.policy, LoginAttempt, LoginAttempt.email == email.strip(), now)

    def record(self, db: Session, email: str, *, succeeded: bool, now: datetime) -> None:
        db.add(LoginAttempt(email=email.strip(), attempted_at=now, succeeded=succeeded))
        db.flush()


class PasswordChangeRateLimiter:
    def __init__(self, policy: RateLimitPolicy | None = None) -> None:
        self.policy = policy or RateLimitPolicy()

    def retry_after(self, db: Session, user_id: uuid.UUID, now: datetime) -> timedelta | None:
        """How long `user_id` is locked out for, or None if they may try now."""
        key = PasswordChangeAttempt.user_id == user_id
        return _retry_after(db, self.policy, PasswordChangeAttempt, key, now)

    def record(self, db: Session, user_id: uuid.UUID, *, succeeded: bool, now: datetime) -> None:
        db.add(PasswordChangeAttempt(user_id=user_id, attempted_at=now, succeeded=succeeded))
        db.flush()
