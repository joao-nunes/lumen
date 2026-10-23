from datetime import timedelta

import pytest

from lumen.auth.policy import SessionPolicy


def test_inconsistent_timeouts_are_rejected() -> None:
    with pytest.raises(ValueError):
        SessionPolicy(idle_timeout=timedelta(days=8), absolute_timeout=timedelta(days=7))
    with pytest.raises(ValueError):
        # Touch interval >= idle timeout would expire sessions while in use.
        SessionPolicy(touch_interval=timedelta(hours=12))
