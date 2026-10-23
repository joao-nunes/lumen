from datetime import timedelta

import pytest

from lumen.auth.policy import SessionPolicy
from lumen.config import Settings


def test_inconsistent_timeouts_are_rejected() -> None:
    with pytest.raises(ValueError):
        SessionPolicy(idle_timeout=timedelta(days=8), absolute_timeout=timedelta(days=7))
    with pytest.raises(ValueError):
        SessionPolicy(touch_interval=timedelta(hours=12))  # not shorter than idle


def test_timeouts_are_configurable_with_iso_8601_durations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT", "PT2H")
    monkeypatch.setenv("SESSION_ABSOLUTE_TIMEOUT", "P1D")
    policy = SessionPolicy.from_settings(Settings(_env_file=None))
    assert (policy.idle_timeout, policy.absolute_timeout) == (timedelta(hours=2), timedelta(days=1))
