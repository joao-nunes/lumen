"""Acceptance criteria of spec 005 (docs/specs/005-logging.md)."""

import asyncio
import json
import re
import signal
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lumen.api.app import create_app
from lumen.api.errors import error_response
from lumen.api.event_log import EventLog
from lumen.api.middleware import SECURITY_HEADERS, RequestLogMiddleware
from lumen.config import Settings
from tests.api.client import EMAIL, PASSWORD, SESSION, NewClient, csrf, login, register
from tests.api.conftest import FakeClock

DAY = "2026-10-23"
SCORES = {"mood": 3, "energy": 3, "stress": 3}
TS = "2026-10-23T09:00:00Z"
MARKER = "marker_7q"  # a valid tag, so it reaches PostgreSQL
CRASH_BODY = {"error": {"code": "internal_error", "message": "Something went wrong"}}


def parsed(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def request_line(
    lines: list[str], *, method: str, route: str | None, status: int, error: str | None
) -> dict[str, Any]:
    """The only line written, checked field by field except the two the server makes up."""
    [line] = parsed(lines)
    duration, request_id = line.pop("duration_ms"), line.pop("request_id")
    assert type(duration) is int
    assert duration >= 0
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert line == {
        "ts": TS,
        "event": "request",
        "method": method,
        "route": route,
        "status": status,
        "error": error,
    }
    return {"request_id": request_id}


@pytest.fixture
def client(new_client: NewClient) -> TestClient:
    return new_client()


@pytest.fixture
def tags_always_fail(clean_db: Engine) -> Iterator[None]:
    """Saving a tag fails with a real PostgreSQL error that repeats the row, marker included."""
    with clean_db.begin() as conn:
        conn.execute(text("ALTER TABLE tags ADD CONSTRAINT never CHECK (name = 'never')"))
    yield
    with clean_db.begin() as conn:
        conn.execute(text("ALTER TABLE tags DROP CONSTRAINT never"))


def test_ac1_a_request_writes_one_line_with_exactly_the_allowed_fields(
    client: TestClient, log_lines: list[str]
) -> None:
    assert register(client).status_code == 201
    log_lines.clear()

    response = client.put(
        f"/api/checkins/{DAY}",
        json={"scores": {**SCORES, "mood": 99}, "tags": []},
        headers=csrf(client),
    )

    assert response.status_code == 422
    fields = request_line(
        log_lines,
        method="PUT",
        route="/api/checkins/{local_date}",
        status=422,
        error="invalid_score",
    )
    assert response.headers["X-Request-ID"] == fields["request_id"]


def test_ac2_nothing_the_client_sends_reaches_the_log(
    new_client: NewClient, log_lines: list[str]
) -> None:
    client = new_client()
    headers = {"User-Agent": MARKER, "X-Forwarded-For": MARKER, "Referer": MARKER}
    secret_phrase = "cobalt lanterns drift past midnight"  # the policy rejects one with the email
    email, password = f"{MARKER}@example.com", secret_phrase

    assert (
        client.post(
            "/api/auth/register", json={"email": email, "password": password}, headers=headers
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": email, "password": "wrong " + password}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/password",
            json={"current_password": MARKER, "new_password": MARKER},
            headers={**csrf(client), **headers},
        ).status_code
        == 401
    )
    assert (
        client.put(
            f"/api/checkins/{DAY}?{MARKER}={MARKER}",
            json={"scores": SCORES, "tags": [MARKER]},
            headers={**csrf(client), **headers},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/checkins/{DAY}",
            json={"scores": SCORES, "tags": [MARKER + " !!"]},
            headers={**csrf(client), **headers},
        ).status_code
        == 422
    )
    assert client.get(f"/api/{MARKER}?{MARKER}={MARKER}", headers=headers).status_code == 404
    client.cookies.set("marker_cookie", MARKER)
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    assert len(log_lines) == 7
    assert not [line for line in log_lines if MARKER in line or "cobalt" in line]


def test_ac3_no_line_identifies_the_user(
    client: TestClient, engine: Engine, log_lines: list[str]
) -> None:
    assert register(client).status_code == 201
    assert login(client).status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # the first requests that know the user
    assert (
        client.put(
            f"/api/checkins/{DAY}", json={"scores": SCORES, "tags": []}, headers=csrf(client)
        ).status_code
        == 200
    )
    with engine.connect() as conn:
        user_id = str(conn.scalar(text("SELECT id FROM users")))

    assert len(log_lines) == 4
    for secret in (user_id, user_id.replace("-", ""), EMAIL, PASSWORD, client.cookies[SESSION]):
        assert not [line for line in log_lines if secret in line]


@pytest.mark.usefixtures("tags_always_fail")
def test_ac4_a_crash_is_logged_without_its_message_and_answered_as_json(
    new_client: NewClient, log_lines: list[str]
) -> None:
    client = new_client()
    assert register(client).status_code == 201
    log_lines.clear()

    response = client.put(
        f"/api/checkins/{DAY}",
        json={"scores": SCORES, "tags": [MARKER]},
        headers=csrf(client),
    )

    assert response.status_code == 500
    assert response.json() == CRASH_BODY
    assert MARKER not in response.text
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value
    assert response.headers["Cache-Control"] == "no-store"

    assert not [line for line in log_lines if MARKER in line]
    crash, request = parsed(log_lines)
    frames = crash.pop("frames")
    assert crash == {
        "ts": TS,
        "event": "crash",
        "request_id": response.headers["X-Request-ID"],
        "exceptions": ["sqlalchemy.exc.IntegrityError", "psycopg.errors.CheckViolation"],
    }
    assert frames
    assert all(re.fullmatch(r"lumen(\.\w+)+:\w+:\d+", frame) for frame in frames)
    modules = [frame.split(":")[0] for frame in frames]
    assert modules.index("lumen.db.repository") < modules.index("lumen.api.routes.checkins")
    assert any(frame.startswith("lumen.api.routes.checkins:write_checkin:") for frame in frames)
    assert not [frame for frame in frames if frame.startswith("lumen.api.middleware:")]
    assert request["event"] == "request"
    assert request["request_id"] == crash["request_id"]
    assert (request["status"], request["error"]) == (500, "internal_error")


def lockout(client: TestClient, path: str, body: dict[str, str], wrong: int = 5) -> list[int]:
    return [
        client.post(path, json=body, headers=csrf(client)).status_code for _ in range(wrong + 1)
    ]


def test_ac5_each_security_event_is_identifiable(
    new_client: NewClient, log_lines: list[str]
) -> None:
    def seen() -> list[tuple[str, int, str | None]]:
        rows = [(line["route"], line["status"], line["error"]) for line in parsed(log_lines)]
        log_lines.clear()
        return rows

    login_body = {"email": "nobody@example.com", "password": "wrong"}
    assert lockout(new_client(), "/api/auth/login", login_body) == [401] * 5 + [429]
    login_rows = seen()
    assert login_rows[0] == ("/api/auth/login", 401, "invalid_credentials")
    assert login_rows[-1] == ("/api/auth/login", 429, "too_many_attempts")

    client = new_client()
    assert register(client).status_code == 201
    log_lines.clear()
    change_body = {"current_password": "wrong", "new_password": "does not matter"}
    assert lockout(client, "/api/auth/password", change_body) == [401] * 5 + [429]
    change_rows = seen()
    assert change_rows[0] == ("/api/auth/password", 401, "invalid_credentials")
    assert change_rows[-1] == ("/api/auth/password", 429, "too_many_attempts")

    assert client.post("/api/auth/logout").status_code == 403
    assert seen() == [("/api/auth/logout", 403, "csrf_failed")]

    refused = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert refused.status_code == 403
    assert seen() == [(None, 403, "forbidden_origin")]  # refused before routing


def test_ac6_request_ids_come_from_the_server(client: TestClient, log_lines: list[str]) -> None:
    response = client.get("/api/auth/me", headers={"X-Request-ID": MARKER})
    assert response.headers["X-Request-ID"] != MARKER
    assert parsed(log_lines)[0]["request_id"] == response.headers["X-Request-ID"]


def test_ac6_parallel_requests_each_keep_their_own_id(
    client: TestClient, log_lines: list[str]
) -> None:
    paths = ["/api/auth/me", "/api/unknown"] * 5  # 401 and 404, so a mix-up shows in the status
    barrier = Barrier(len(paths))

    def send(path: str) -> tuple[str, int]:
        barrier.wait()
        response = client.get(path)
        return response.headers["X-Request-ID"], response.status_code

    with ThreadPoolExecutor(len(paths)) as pool:
        responses = list(pool.map(send, paths))

    assert len({request_id for request_id, _ in responses}) == len(paths)
    logged = {line["request_id"]: line["status"] for line in parsed(log_lines)}
    assert logged == dict(responses)


def test_ac7_pages_and_assets_write_nothing(tmp_path: Path, clock: FakeClock) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "app.js").write_text("")
    lines: list[str] = []
    app = create_app(
        Settings(_env_file=None, secret_key=SecretStr("x" * 32), web_dist=tmp_path),
        clock=clock,
        log=EventLog(clock, lines.append),
    )

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/apiary").status_code == 200  # the app's own page, not the API

    assert lines == []


def crash_only(lines: list[str], request_id: str) -> None:
    [crash] = parsed(lines)
    assert crash == {
        "ts": TS,
        "event": "crash",
        "request_id": request_id,
        "exceptions": ["builtins.ValueError"],
        "frames": [],
    }


async def _crashes(scope: Scope, receive: Receive, send: Send) -> None:
    raise ValueError(MARKER)


def test_ac7_a_crash_outside_the_api_writes_only_a_crash_line(clock: FakeClock) -> None:
    lines: list[str] = []
    client = TestClient(RequestLogMiddleware(_crashes, log=EventLog(clock, lines.append)))

    response = client.get("/some/page")

    assert response.status_code == 500
    assert response.json() == CRASH_BODY
    crash_only(lines, response.headers["X-Request-ID"])


def test_ac8_a_method_outside_the_list_is_not_logged_as_sent(
    client: TestClient, log_lines: list[str]
) -> None:
    assert client.request("PROPFIND", "/api/auth/me").status_code == 405
    request_line(
        log_lines, method="OTHER", route="/api/auth/me", status=405, error="method_not_allowed"
    )


def test_ac8_an_unmatched_path_has_no_route(client: TestClient, log_lines: list[str]) -> None:
    assert client.get(f"/api/{MARKER}").status_code == 404
    request_line(log_lines, method="GET", route=None, status=404, error="not_found")


@pytest.mark.parametrize(
    "response",
    [
        error_response(418, MARKER, MARKER),  # a code nobody listed
        PlainTextResponse(MARKER, status_code=400),  # an error that isn't the API's shape
        PlainTextResponse('{"error": {"code": ["x"]}}', status_code=400),
        # A listed code, but too big to be one of the API's errors: it must not be buffered whole.
        error_response(400, "not_found", "x" * 100_000),
    ],
)
def test_ac8_an_error_code_outside_the_list_is_not_logged_as_sent(
    app: FastAPI, client: TestClient, log_lines: list[str], response: Any
) -> None:
    app.add_api_route("/api/odd", lambda: response)
    client.get("/api/odd")
    request_line(
        log_lines, method="GET", route="/api/odd", status=response.status_code, error="unknown"
    )


def test_ac9_a_crash_after_the_response_started_is_logged_and_not_re_raised(
    clock: FakeClock,
) -> None:
    lines: list[str] = []

    async def crashes_midway(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"part", "more_body": True})
        raise ValueError(MARKER)

    client = TestClient(RequestLogMiddleware(crashes_midway, log=EventLog(clock, lines.append)))
    response = client.get("/api/stream")  # would raise here if the crash escaped

    assert (response.status_code, response.content) == (200, b"part")
    crash, request = parsed(lines)
    assert crash["exceptions"] == ["builtins.ValueError"]
    assert (request["status"], request["error"]) == (200, "internal_error")
    assert MARKER not in "".join(lines)


def _raising_write(line: str) -> None:
    raise OSError("stderr is closed")


def test_ac10_a_failing_log_changes_no_response(clock: FakeClock) -> None:
    async def ok(scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse("fine")(scope, receive, send)

    log = EventLog(clock, _raising_write)

    assert TestClient(RequestLogMiddleware(ok, log=log)).get("/api/x").text == "fine"
    crashed = TestClient(RequestLogMiddleware(_crashes, log=log)).get("/api/x")
    assert (crashed.status_code, crashed.json()) == (500, CRASH_BODY)


def run_asgi(
    app: ASGIApp, clock: FakeClock, *, scope_type: str = "http", send: Send | None = None
) -> list[str]:
    """Calls the middleware directly, for what TestClient can't arrange, and returns its lines."""
    lines: list[str] = []
    scope = {"type": scope_type, "method": "GET", "path": "/api/x", "headers": []}

    async def receive() -> Message:
        return {"type": "http.request"}

    async def discard(message: Message) -> None:
        pass

    middleware = RequestLogMiddleware(app, log=EventLog(clock, lines.append))
    asyncio.run(middleware(scope, receive, send or discard))
    return lines


def test_cause_chains_are_followed_even_when_they_loop(clock: FakeClock) -> None:
    async def loops(scope: Scope, receive: Receive, send: Send) -> None:
        first, second = KeyError(MARKER), ValueError(MARKER)
        first.__cause__, second.__cause__ = second, first
        raise first

    def too_slow(signum: int, frame: object) -> None:
        raise TimeoutError

    # Without this, a loop that never ends would hang the suite rather than fail it.
    signal.signal(signal.SIGALRM, too_slow)
    signal.alarm(5)
    try:
        lines = run_asgi(loops, clock)
    finally:
        signal.alarm(0)
    assert parsed(lines)[0]["exceptions"] == ["builtins.KeyError", "builtins.ValueError"]


def test_exception_chain_follows_python_s_own_rules(clock: FakeClock) -> None:
    async def implicit(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            raise KeyError(MARKER)
        except KeyError:
            raise ValueError(MARKER)  # noqa: B904

    async def hidden(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            raise KeyError(MARKER)
        except KeyError:
            raise ValueError(MARKER) from None

    implicit_line = parsed(run_asgi(implicit, clock))[0]
    assert implicit_line["exceptions"] == ["builtins.ValueError", "builtins.KeyError"]
    assert parsed(run_asgi(hidden, clock))[0]["exceptions"] == ["builtins.ValueError"]


def test_cancellation_is_not_treated_as_a_crash(clock: FakeClock) -> None:
    lines: list[str] = []

    async def cancelled(scope: Scope, receive: Receive, send: Send) -> None:
        lines.extend(["reached"])
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run_asgi(cancelled, clock)
    assert lines == ["reached"]


def test_a_failure_sending_the_500_stays_out_of_uvicorn(clock: FakeClock) -> None:
    async def client_gone(message: Message) -> None:
        raise OSError(MARKER)

    crash, request = parsed(
        run_asgi(_crashes, clock, send=client_gone)
    )  # would raise if it escaped

    assert crash["exceptions"] == ["builtins.ValueError"]
    assert (request["status"], request["error"]) == (500, "internal_error")


def test_an_app_that_sends_nothing_is_logged_as_a_500(clock: FakeClock) -> None:
    async def silent(scope: Scope, receive: Receive, send: Send) -> None:
        pass

    [request] = parsed(run_asgi(silent, clock))
    assert (request["status"], request["error"]) == (500, "unknown")


def test_startup_and_shutdown_pass_through_unlogged(clock: FakeClock) -> None:
    seen: list[str] = []

    async def lifespan(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    assert run_asgi(lifespan, clock, scope_type="lifespan") == []
    assert seen == ["lifespan"]


def test_duration_is_in_milliseconds(clock: FakeClock) -> None:
    async def slow(scope: Scope, receive: Receive, send: Send) -> None:
        await asyncio.sleep(0.02)
        await PlainTextResponse("fine")(scope, receive, send)

    [request] = parsed(run_asgi(slow, clock))
    assert request["duration_ms"] >= 20
    assert request["error"] is None


def test_successes_and_redirects_have_no_error(client: TestClient, log_lines: list[str]) -> None:
    assert client.get("/api/auth/me/", follow_redirects=False).status_code == 307
    request_line(log_lines, method="GET", route=None, status=307, error=None)


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "status", "code"),
    [
        ("GET", "/api/auth/me", {}, 401, "not_authenticated"),
        ("POST", "/api/auth/login", {"content": "x"}, 415, "unsupported_media_type"),
        ("POST", "/api/auth/login", {"json": {}}, 422, "invalid_request"),
    ],
)
def test_codes_outside_the_domain_errors_are_listed(
    client: TestClient,
    log_lines: list[str],
    method: str,
    path: str,
    kwargs: dict[str, Any],
    status: int,
    code: str,
) -> None:
    assert client.request(method, path, **kwargs).status_code == status
    assert parsed(log_lines)[0]["error"] == code
