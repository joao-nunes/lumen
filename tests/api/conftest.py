"""HTTP-level fixtures: the real app, real login roles, real database, fake clock.

The app commits its own transactions, so isolation is by truncating every
table before and after each test (rollback can't undo another connection's
commits).
"""

from collections.abc import Callable, Collection, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, make_url, text

from lumen.api.app import create_app
from lumen.api.event_log import EventLog
from lumen.config import Settings, get_settings
from lumen.domain.dimensions import Dimension
from lumen.suggestions.model import Suggestion

T0 = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def _truncate_all(engine: Engine) -> None:
    with engine.begin() as conn:
        tables = conn.scalars(
            text(
                "SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) "
                "FROM information_schema.tables "
                "WHERE table_schema IN ('public', 'auth') AND table_type = 'BASE TABLE' "
                "AND table_name <> 'alembic_version'"
            )
        ).all()
        # A request that leaked a transaction would otherwise block this forever.
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


def _as_role(url: str, role: str) -> str:
    # Local and CI role passwords equal the role name (docker/postgres/init).
    return make_url(url).set(username=role, password=role).render_as_string(hide_password=False)


@pytest.fixture
def clean_db(engine: Engine) -> Iterator[Engine]:
    _truncate_all(engine)
    yield engine
    _truncate_all(engine)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def log_lines() -> list[str]:
    return []


class FakeSuggestionModel:
    """Stands in for a local model, which is slow and non-deterministic. Records what it's asked."""

    def __init__(self) -> None:
        self.reply = Suggestion()
        self.error: Exception | None = None
        self.calls: list[tuple[str, tuple[Dimension, ...], tuple[str, ...], str]] = []
        self.during_call: Callable[[], None] = lambda: None

    def suggest(
        self,
        text: str,
        dimensions: Collection[Dimension],
        tags: Collection[str],
        context: str = "",
    ) -> Suggestion:
        self.calls.append((text, tuple(dimensions), tuple(tags), context))
        self.during_call()
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
def suggestion_model() -> FakeSuggestionModel:
    return FakeSuggestionModel()


@pytest.fixture
def test_settings() -> Callable[..., Settings]:
    def make(**changes: object) -> Settings:
        test_url = get_settings().test_database_url
        return Settings(
            _env_file=None,
            database_url=_as_role(test_url, "lumen_app"),
            auth_database_url=_as_role(test_url, "lumen_auth"),
            admin_database_url=test_url,
            test_database_url=test_url,
            secret_key=SecretStr("test-secret-key-" + "x" * 32),
            allowed_origins=["http://localhost:5173"],
            cookie_secure=True,
            **changes,
        )

    return make


@pytest.fixture
def app(
    clean_db: Engine,
    clock: FakeClock,
    log_lines: list[str],
    suggestion_model: FakeSuggestionModel,
    test_settings: Callable[..., Settings],
) -> FastAPI:
    return create_app(
        test_settings(),
        clock=clock,
        log=EventLog(clock, log_lines.append),
        suggestions=suggestion_model,
    )


@pytest.fixture
def new_client(app: FastAPI) -> Iterator[Callable[[], TestClient]]:
    """Independent browsers. https:// so Secure cookies are kept and sent, as in Chrome."""
    clients: list[TestClient] = []

    def make() -> TestClient:
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()  # runs the app's startup/shutdown lifespan
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
