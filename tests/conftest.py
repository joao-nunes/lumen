"""Fixtures shared by all test packages."""

import pytest
from argon2 import PasswordHasher

from lumen.auth.passwords import Passwords


@pytest.fixture
def passwords() -> Passwords:
    """Argon2id with minimal cost parameters, so tests stay fast.

    Production parameters are covered by a dedicated test.
    """
    return Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
