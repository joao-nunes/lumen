from datetime import timedelta

import pytest

from lumen.auth.policy import SessionPolicy
from lumen.config import Settings


def test_defaults() -> None:
    policy = SessionPolicy()
    assert policy.idle_timeout == timedelta(hours=12)
    assert policy.absolute_timeout == timedelta(days=7)


@pytest.mark.parametrize(
    ("idle", "absolute", "touch"),
    [
        (timedelta(days=8), timedelta(days=7), timedelta(minutes=5)),  # idle > absolute
        (timedelta(hours=12), timedelta(days=7), timedelta(hours=12)),  # touch >= idle
        (timedelta(hours=12), timedelta(days=7), timedelta(0)),  # touch must be positive
    ],
)
def test_inconsistent_timeouts_are_rejected(
    idle: timedelta, absolute: timedelta, touch: timedelta
) -> None:
    with pytest.raises(ValueError):
        SessionPolicy(idle_timeout=idle, absolute_timeout=absolute, touch_interval=touch)


def test_settings_parse_iso_8601_durations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT", "PT2H")
    monkeypatch.setenv("SESSION_ABSOLUTE_TIMEOUT", "P1D")
    policy = SessionPolicy.from_settings(Settings(_env_file=None))
    assert policy.idle_timeout == timedelta(hours=2)
    assert policy.absolute_timeout == timedelta(days=1)
