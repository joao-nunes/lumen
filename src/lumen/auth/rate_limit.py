"""Login rate limiting per email (spec 001 §2.5).

Only failures since the email's last successful login, within the window,
count. Once `max_failures` of them exist, logins are refused until enough
of them age out of the window. Refused attempts are not recorded, so
retrying during a lockout doesn't extend it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lumen.auth.models import LoginAttempt


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    max_failures: int = 5
    window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.max_failures < 1 or self.window <= timedelta(0):
            raise ValueError("Require max_failures >= 1 and a positive window")


class LoginRateLimiter:
    def __init__(self, policy: RateLimitPolicy | None = None) -> None:
        self.policy = policy or RateLimitPolicy()

    def retry_after(self, db: Session, email: str, now: datetime) -> timedelta | None:
        """How long `email` is locked out for, or None if it may try now."""
        email = email.strip()
        last_success = db.scalar(
            select(func.max(LoginAttempt.attempted_at)).where(
                LoginAttempt.email == email, LoginAttempt.succeeded
            )
        )
        since = now - self.policy.window
        if last_success is not None and last_success > since:
            since = last_success
        failures = db.scalars(
            select(LoginAttempt.attempted_at)
            .where(
                LoginAttempt.email == email,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at > since,
            )
            .order_by(LoginAttempt.attempted_at)
        ).all()
        if len(failures) < self.policy.max_failures:
            return None
        # Unlocked once only max_failures - 1 of them remain inside the window.
        unlocks_at = failures[len(failures) - self.policy.max_failures] + self.policy.window
        return unlocks_at - now

    def record(self, db: Session, email: str, *, succeeded: bool, now: datetime) -> None:
        db.add(LoginAttempt(email=email.strip(), attempted_at=now, succeeded=succeeded))
        db.flush()
