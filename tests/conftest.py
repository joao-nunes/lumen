"""Fixtures shared by all test packages.

Database fixtures: a migrated test database, one transaction per test.
Tests that need the database are skipped automatically when PostgreSQL isn't
reachable. Start it with `docker compose up -d db`. Set LUMEN_REQUIRE_DB=1
(as CI does) to fail instead of skipping, so a broken database setup can't
silently turn the integration suite green.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from lumen.auth.passwords import Passwords
from lumen.config import get_settings


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Any test that (transitively) needs the database is an integration test.
    for item in items:
        if "engine" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """The test database, migrated to head, connected as its owner."""
    url = get_settings().test_database_url
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        message = "PostgreSQL test database is not reachable (docker compose up -d db)"
        if os.environ.get("LUMEN_REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message)

    # Downgrading first exercises the downgrade path and guarantees a clean schema.
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test, even if the test commits."""
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def passwords() -> Passwords:
    """Argon2id with minimal cost parameters, so tests stay fast.

    Production parameters are covered by a dedicated test.
    """
    return Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
