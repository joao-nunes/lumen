from dataclasses import dataclass
from datetime import timedelta

from lumen.config import Settings


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    # A session unused for this long expires.
    idle_timeout: timedelta = timedelta(hours=12)
    # A session expires this long after login, however active it is.
    absolute_timeout: timedelta = timedelta(days=7)
    # last_seen_at is only written when older than this, to avoid a database
    # write on every request; idle expiry loses at most this much precision.
    touch_interval: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not timedelta(0) < self.touch_interval < self.idle_timeout <= self.absolute_timeout:
            raise ValueError("Require 0 < touch_interval < idle_timeout <= absolute_timeout")

    @classmethod
    def from_settings(cls, settings: Settings) -> "SessionPolicy":
        return cls(
            idle_timeout=settings.session_idle_timeout,
            absolute_timeout=settings.session_absolute_timeout,
            touch_interval=settings.session_touch_interval,
        )
