"""Spec 010, first PR: personal context, stored per person, Tier 0, never logged."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.client import NewClient, csrf, error_code, register

MARKER = "marker_private_context_4k"


@pytest.fixture
def client(new_client: NewClient) -> TestClient:
    logged_in = new_client()
    assert register(logged_in).status_code == 201
    return logged_in


def put(client: TestClient, value: str) -> int:
    return client.put("/api/context", json={"text": value}, headers=csrf(client)).status_code


def stored(client: TestClient) -> str:
    response = client.get("/api/context")
    assert response.status_code == 200
    return str(response.json()["text"])


def rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.scalar(text("SELECT count(*) FROM personal_context")) or 0


def test_ac1_saved_trimmed_read_back_and_replaced(client: TestClient) -> None:
    assert stored(client) == ""

    assert put(client, "  Waking at night is normal for me.  ") == 200
    assert stored(client) == "Waking at night is normal for me."

    assert put(client, "I nap most afternoons.") == 200
    assert stored(client) == "I nap most afternoons."


def test_ac2_too_long_is_refused_and_empty_deletes(client: TestClient, engine: Engine) -> None:
    assert put(client, "x" * 750) == 200
    response = client.put("/api/context", json={"text": "x" * 751}, headers=csrf(client))
    assert error_code(response)[0] == 422
    assert stored(client) == "x" * 750

    assert put(client, "   ") == 200
    assert stored(client) == ""
    assert rows(engine) == 0


def test_ac3_each_person_sees_only_their_own(client: TestClient, new_client: NewClient) -> None:
    other = new_client()
    assert register(other, "other@example.com").status_code == 201
    assert put(client, "Mine.") == 200

    assert stored(other) == ""
    assert put(other, "Theirs.") == 200
    assert (stored(client), stored(other)) == ("Mine.", "Theirs.")


def test_ac4_never_logged_or_repeated(
    client: TestClient, engine: Engine, log_lines: list[str]
) -> None:
    log_lines.clear()
    assert put(client, f"{MARKER} wakes at night") == 200
    assert MARKER in stored(client)
    too_long = client.put("/api/context", json={"text": MARKER * 100}, headers=csrf(client))

    assert MARKER not in too_long.text
    assert log_lines
    assert not [line for line in log_lines if MARKER in line]
    with engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) "
                "FROM information_schema.tables WHERE table_schema IN ('public', 'auth') "
                "AND table_type = 'BASE TABLE' AND table_name <> 'personal_context'"
            )
        ).scalars()
        for table in tables:
            found = conn.execute(text(f"SELECT t::text FROM {table} t")).scalars()  # noqa: S608
            assert not [row for row in found if MARKER in row], table


def test_it_needs_a_session_and_a_csrf_token(new_client: NewClient, client: TestClient) -> None:
    assert error_code(new_client().get("/api/context")) == (401, "not_authenticated")
    response = client.put("/api/context", json={"text": "x"})
    assert error_code(response)[0] == 403
