"""Acceptance criteria of spec 001 (docs/specs/001-auth-http.md), one test each."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from lumen.api.dependencies import user_session
from lumen.db import models
from lumen.db.repository import save_checkin
from lumen.domain.checkin import Checkin
from lumen.domain.dimensions import Dimension
from tests.api.conftest import FakeClock

SESSION, CSRF = "__Host-lumen_session", "__Host-lumen_csrf"
EMAIL = "joao@example.com"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "purple elephant dancing slowly"

NewClient = Callable[[], TestClient]


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> httpx.Response:
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> httpx.Response:
    return client.post("/api/auth/login", json={"email": email, "password": password})


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get(CSRF) or ""}


def error_code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def set_cookies(response: httpx.Response) -> dict[str, str]:
    """Raw Set-Cookie headers by cookie name, to check attributes."""
    return {h.split("=", 1)[0]: h for h in response.headers.get_list("set-cookie")}


def cleared(header: str) -> bool:
    # Deletion must keep Secure and Path=/, or browsers ignore it for __Host- cookies.
    return all(part in header for part in ("Max-Age=0", "Secure", "Path=/"))


def registered_user(new_client: NewClient) -> uuid.UUID:
    return uuid.UUID(register(new_client()).json()["user_id"])


# --- register and login ------------------------------------------------------------


def test_ac1_register_logs_in_and_rejects_duplicate_email_in_any_case(
    new_client: NewClient,
) -> None:
    client = new_client()
    response = register(client)
    assert response.status_code == 201
    user_id = response.json()["user_id"]
    assert client.get("/api/auth/me").json() == {"user_id": user_id, "email": EMAIL}
    assert error_code(register(new_client(), EMAIL.upper())) == (409, "email_taken")


def test_ac2_weak_password_is_rejected_without_creating_a_user(new_client: NewClient) -> None:
    assert error_code(register(new_client(), password="Sh0rt!Pass#1")) == (422, "weak_password")
    assert register(new_client()).status_code == 201  # the email is still free


def test_ac3_login_sets_hardened_cookies_and_identifies_the_user(new_client: NewClient) -> None:
    user_id = registered_user(new_client)
    client = new_client()
    response = login(client)
    assert response.status_code == 204
    cookies = set_cookies(response)
    session, csrf_cookie = cookies[SESSION], cookies[CSRF]
    for attribute in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=604800"):
        assert attribute in session
    for attribute in ("Secure", "SameSite=Strict", "Path=/"):
        assert attribute in csrf_cookie
    assert "HttpOnly" not in csrf_cookie  # the frontend must read it
    assert "Domain" not in session + csrf_cookie
    assert client.get("/api/auth/me").json() == {"user_id": str(user_id), "email": EMAIL}


def test_ac4_wrong_password_and_unknown_email_are_indistinguishable(
    new_client: NewClient,
) -> None:
    registered_user(new_client)
    wrong_password = login(new_client(), password="wrong password entirely")
    unknown_email = login(new_client(), email="nobody@example.com")
    assert error_code(wrong_password) == (401, "invalid_credentials")
    assert wrong_password.json() == unknown_email.json()


def test_ac5_logging_in_again_invalidates_the_previous_session(new_client: NewClient) -> None:
    registered_user(new_client)
    client = new_client()
    login(client)
    old_token = client.cookies.get(SESSION)
    login(client)
    assert client.cookies.get(SESSION) != old_token
    stale = new_client()
    stale.cookies.set(SESSION, old_token or "")
    assert error_code(stale.get("/api/auth/me")) == (401, "not_authenticated")


# --- sessions ------------------------------------------------------------------------


def test_ac6_idle_session_expires_and_cookies_are_cleared(
    new_client: NewClient, clock: FakeClock
) -> None:
    client = new_client()
    register(client)
    clock.advance(hours=12)
    response = client.get("/api/auth/me")
    assert error_code(response) == (401, "not_authenticated")
    assert cleared(set_cookies(response)[SESSION])


def test_ac7_logout_ends_the_session_clears_cookies_and_is_idempotent(
    new_client: NewClient,
) -> None:
    client = new_client()
    register(client)
    token = client.cookies.get(SESSION)
    response = client.post("/api/auth/logout", headers=csrf(client))
    assert response.status_code == 204
    assert cleared(set_cookies(response)[SESSION])
    stale = new_client()
    stale.cookies.set(SESSION, token or "")
    assert error_code(stale.get("/api/auth/me")) == (401, "not_authenticated")
    assert client.post("/api/auth/logout").status_code == 204


def test_ac8_password_change_revokes_other_sessions_and_the_old_password(
    new_client: NewClient,
) -> None:
    laptop, desktop = new_client(), new_client()
    register(laptop)
    login(desktop)
    old_token = laptop.cookies.get(SESSION)
    response = laptop.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf(laptop),
    )
    assert response.status_code == 204
    assert laptop.cookies.get(SESSION) != old_token
    assert laptop.get("/api/auth/me").status_code == 200
    assert error_code(desktop.get("/api/auth/me")) == (401, "not_authenticated")
    assert error_code(login(new_client())) == (401, "invalid_credentials")
    assert login(new_client(), password=NEW_PASSWORD).status_code == 204


# --- CSRF and origin ----------------------------------------------------------------


def test_ac9_state_change_without_matching_csrf_token_is_forbidden(
    new_client: NewClient,
) -> None:
    client, other = new_client(), new_client()
    register(client)
    login(other)
    assert error_code(client.post("/api/auth/logout")) == (403, "csrf_failed")
    assert error_code(client.post("/api/auth/logout", headers=csrf(other))) == (403, "csrf_failed")
    assert client.get("/api/auth/me").status_code == 200  # still logged in


def test_ac10_requests_from_other_origins_are_forbidden(new_client: NewClient) -> None:
    registered_user(new_client)
    evil = new_client().post(
        "/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert error_code(evil) == (403, "forbidden_origin")
    allowed = new_client().post(
        "/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": "http://localhost:5173"},
    )
    assert allowed.status_code == 204


def test_ac11_form_encoded_bodies_are_rejected(new_client: NewClient) -> None:
    registered_user(new_client)
    response = new_client().post("/api/auth/login", data={"email": EMAIL, "password": PASSWORD})
    assert error_code(response) == (415, "unsupported_media_type")


# --- rate limiting ------------------------------------------------------------------


def test_ac12_five_failures_lock_the_email_even_for_the_right_password(
    new_client: NewClient, clock: FakeClock
) -> None:
    registered_user(new_client)
    for _ in range(5):
        login(new_client(), password="wrong password entirely")
        clock.advance(minutes=1)
    clock.advance(minutes=-1)  # the 5th failure was at T0 + 4 min; still at that moment
    locked = login(new_client())
    assert error_code(locked) == (429, "too_many_attempts")
    assert locked.headers["Retry-After"] == "660"  # until the T0 failure is 15 minutes old
    clock.advance(minutes=11)  # T0 + 15 min
    assert login(new_client()).status_code == 204


def test_ac13_unknown_emails_are_locked_the_same_way(new_client: NewClient) -> None:
    for _ in range(5):
        login(new_client(), email="nobody@example.com")
    assert error_code(login(new_client(), email="nobody@example.com")) == (
        429,
        "too_many_attempts",
    )


def test_ac14_a_successful_login_resets_the_failure_count(new_client: NewClient) -> None:
    registered_user(new_client)
    for _ in range(4):
        login(new_client(), password="wrong password entirely")
    assert login(new_client()).status_code == 204
    for _ in range(4):
        login(new_client(), password="wrong password entirely")
    assert login(new_client()).status_code == 204


# --- user data and RLS --------------------------------------------------------------


def test_ac15_data_endpoints_get_a_session_scoped_to_the_logged_in_user(
    app: FastAPI, new_client: NewClient, clean_db: Engine
) -> None:
    @app.get("/test/checkin-owners")
    def checkin_owners(db: Annotated[Session, Depends(user_session)]) -> list[str]:
        return sorted({str(u) for u in db.scalars(select(models.Checkin.user_id))})  # no filter

    alice, bob = new_client(), new_client()
    alice_id = register(alice, "alice@example.com").json()["user_id"]
    bob_id = register(bob, "bob@example.com").json()["user_id"]
    with Session(clean_db) as owner, owner.begin():
        for user_id in (alice_id, bob_id):
            save_checkin(
                owner,
                uuid.UUID(user_id),
                Checkin(
                    datetime(2026, 10, 23, 21, tzinfo=UTC), date(2026, 10, 23), {Dimension.MOOD: 3}
                ),
            )

    assert alice.get("/test/checkin-owners").json() == [alice_id]
    assert error_code(new_client().get("/test/checkin-owners")) == (401, "not_authenticated")
