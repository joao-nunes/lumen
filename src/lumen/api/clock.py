from collections.abc import Callable
from datetime import UTC, datetime

# The current time, injected so tests can control it.
Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)
