"""Acceptance criteria of spec 004 (docs/specs/004-password-change-rate-limit.md)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.client import PASSWORD, NewClient, csrf, error_code, login, register
from tests.api.conftest import FakeClock

WRONG = "wrong password entirely"
NEW_PASSWORD = "purple elephant dancing slowly"
NEWER_PASSWORD = "seven quiet rivers meeting downstream"


def change(client: TestClient, current: str = PASSWORD, new: str = NEW_PASSWORD) -> httpx2.Response:
    return client.post(
        "/api/auth/password",
        json={"current_password": current, "new_password": new},
        headers=csrf(client),
    )


def logged_in(new_client: NewClient) -> TestClient:
    client = new_client()
    assert register(client).status_code == 201
    return client


def fail(client: TestClient, times: int) -> None:
    for _ in range(times):
        assert error_code(change(client, WRONG)) == (401, "invalid_credentials")


def test_ac1_five_wrong_passwords_lock_changes_even_for_the_right_password(
    new_client: NewClient, clock: FakeClock
) -> None:
    client = logged_in(new_client)
    for _ in range(5):  # T0 to T0 + 4 minutes
        fail(client, 1)
        clock.advance(minutes=1)
    clock.advance(minutes=-1)

    refused = change(client)
    assert error_code(refused) == (429, "too_many_attempts")
    assert refused.headers["Retry-After"] == "660"  # until the T0 failure is 15 minutes old
    assert client.get("/api/auth/me").status_code == 200
    assert login(new_client()).status_code == 204  # the password didn't change

    clock.advance(minutes=11)  # T0 + 15 minutes
    assert change(client).status_code == 204


def test_ac2_refused_attempts_do_not_extend_the_lockout(
    new_client: NewClient, clock: FakeClock
) -> None:
    client = logged_in(new_client)
    fail(client, 5)
    for _ in range(5):
        assert change(client, WRONG).status_code == 429
    clock.advance(minutes=15)
    assert change(client).status_code == 204


def test_ac3_another_session_does_not_get_a_new_count(new_client: NewClient) -> None:
    session_a = logged_in(new_client)
    fail(session_a, 5)
    session_b = new_client()
    assert login(session_b).status_code == 204  # logging in doesn't reset the count either
    assert error_code(change(session_b)) == (429, "too_many_attempts")


def test_ac4_failed_logins_and_failed_changes_are_counted_separately(
    new_client: NewClient,
) -> None:
    client = logged_in(new_client)
    for _ in range(5):
        login(new_client(), password=WRONG)
    assert error_code(login(new_client())) == (429, "too_many_attempts")
    assert change(client).status_code == 204

    other = new_client()
    assert register(other, "other@example.com").status_code == 201
    fail(other, 5)
    assert change(other).status_code == 429
    assert login(new_client(), "other@example.com").status_code == 204


def test_ac5_one_users_lockout_does_not_affect_another(new_client: NewClient) -> None:
    locked = logged_in(new_client)
    other = new_client()
    assert register(other, "other@example.com").status_code == 201
    fail(locked, 5)
    assert change(other).status_code == 204


def test_ac6_a_successful_change_resets_the_count(new_client: NewClient) -> None:
    client = logged_in(new_client)
    fail(client, 4)
    assert change(client).status_code == 204
    fail(client, 4)
    assert change(client, NEW_PASSWORD, NEWER_PASSWORD).status_code == 204


def test_ac7_a_weak_new_password_neither_counts_nor_resets(new_client: NewClient) -> None:
    client = logged_in(new_client)
    fail(client, 4)
    assert error_code(change(client, PASSWORD, "short")) == (422, "weak_password")
    fail(client, 1)  # the 5th failure: a counted 422 would have made this a 429
    # A 422 that reset the count would leave this at one failure, not a lockout.
    assert error_code(change(client)) == (429, "too_many_attempts")


def test_ac8_parallel_guesses_get_no_extra_attempts(new_client: NewClient) -> None:
    client = logged_in(new_client)
    barrier = Barrier(10)

    def guess(_: int) -> int:
        barrier.wait()
        return change(client, WRONG).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = sorted(pool.map(guess, range(10)))
    assert statuses == [401] * 5 + [429] * 5


def test_ac9_attempts_are_append_only_for_the_auth_role_and_closed_to_the_app(
    engine: Engine,
) -> None:
    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
    with engine.connect() as conn:
        held = {
            role: {
                p
                for p in privileges
                if conn.scalar(
                    text("SELECT has_table_privilege(:role, 'auth.password_change_attempts', :p)"),
                    {"role": role, "p": p},
                )
            }
            for role in ("lumen_auth", "lumen_app")
        }
    assert held == {"lumen_auth": {"SELECT", "INSERT"}, "lumen_app": set()}


def test_every_outcome_releases_the_row_lock(new_client: NewClient, engine: Engine) -> None:
    def open_transactions() -> int | None:
        with engine.connect() as conn:
            return conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND state LIKE 'idle in transaction%'"
                )
            )

    client = logged_in(new_client)
    # Checked after each request: a lock still held would block the next one forever.
    assert change(client, PASSWORD, "short").status_code == 422
    assert open_transactions() == 0
    for _ in range(5):
        assert change(client, WRONG).status_code == 401
        assert open_transactions() == 0
    assert change(client).status_code == 429
    assert open_transactions() == 0
