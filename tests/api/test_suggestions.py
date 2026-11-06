"""AC-4 to AC-10 of spec 006 (docs/specs/006-free-text-checkin.md)."""

import json
from collections.abc import Callable
from threading import Thread
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from lumen.api.app import create_app
from lumen.config import Settings
from lumen.domain.dimensions import Dimension, dimensions_for
from lumen.suggestions.model import STARTER_TAGS, Suggestion, SuggestionsUnavailableError
from tests.api.client import NewClient, csrf, error_code, register
from tests.api.conftest import T0, FakeClock, FakeSuggestionModel
from tests.suggestions.test_ollama_client import Stub

DAY = "2026-10-23"
OLD_DAY = "2026-10-01"
SCORES = {"mood": 3, "energy": 3, "stress": 3}
MARKER = "marker_private_note_7q"
NOTE = f"{MARKER} slept badly"
PROMPTED = dimensions_for(T0.date())


def suggest(client: TestClient, note: str = NOTE, day: str = DAY) -> httpx2.Response:
    return client.post(f"/api/checkins/{day}/suggestion", json={"text": note}, headers=csrf(client))


@pytest.fixture
def client(new_client: NewClient) -> TestClient:
    logged_in = new_client()
    assert register(logged_in).status_code == 201
    return logged_in


def row_count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.scalar(text(f"SELECT count(*) FROM {table}")) or 0  # noqa: S608


def test_ac4_a_suggestion_is_returned_and_nothing_is_saved(
    client: TestClient, suggestion_model: FakeSuggestionModel, engine: Engine
) -> None:
    suggestion_model.reply = Suggestion(
        scores={Dimension.MOOD: 3, Dimension.STRESS: 4}, tags=frozenset({"poor_sleep"})
    )

    response = suggest(client)

    assert response.status_code == 200
    assert response.json() == {"scores": {"mood": 3, "stress": 4}, "tags": ["poor_sleep"]}
    assert row_count(engine, "checkins") == 0
    assert row_count(engine, "tags") == 0

    [(note, dimensions, offered)] = suggestion_model.calls
    assert note == NOTE
    assert dimensions == PROMPTED
    assert offered == STARTER_TAGS


def test_ac4_text_is_trimmed_before_the_model_sees_it(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    assert suggest(client, f"  {NOTE}\n").status_code == 200
    assert suggestion_model.calls[0][0] == NOTE


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(lambda m: None, id="success"),
        pytest.param(
            lambda m: setattr(m, "error", SuggestionsUnavailableError()), id="unavailable"
        ),
        pytest.param(lambda m: setattr(m, "error", ValueError(MARKER)), id="crash"),
    ],
)
def test_ac5_the_text_leaves_no_trace(
    client: TestClient,
    suggestion_model: FakeSuggestionModel,
    engine: Engine,
    log_lines: list[str],
    arrange: Callable[[FakeSuggestionModel], None],
) -> None:
    arrange(suggestion_model)
    log_lines.clear()

    response = suggest(client)

    assert MARKER not in response.text
    assert log_lines
    assert not [line for line in log_lines if MARKER in line]
    assert response.headers["Cache-Control"] == "no-store"
    with engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) "
                "FROM information_schema.tables "
                "WHERE table_schema IN ('public', 'auth') AND table_type = 'BASE TABLE'"
            )
        ).scalars()
        for table in tables:
            rows = conn.execute(text(f"SELECT t::text FROM {table} t")).scalars()  # noqa: S608
            assert not [row for row in rows if MARKER in row], table


def test_ac6_values_outside_what_was_asked_are_removed(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    unasked = next(d for d in Dimension if d not in PROMPTED)
    suggestion_model.reply = Suggestion(
        scores={Dimension.MOOD: 9, Dimension.ENERGY: 2, unasked: 3},
        tags=frozenset({"not_offered", "exercise"}),
    )

    assert suggest(client).json() == {"scores": {"energy": 2}, "tags": ["exercise"]}


def test_ac7_an_unavailable_model_is_a_503(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    suggestion_model.error = SuggestionsUnavailableError()
    assert error_code(suggest(client)) == (503, "suggestions_unavailable")


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({}, id="no model configured"),
        pytest.param(
            {"ollama_url": "http://127.0.0.1:9", "ollama_model": "some-model"}, id="ollama is down"
        ),
    ],
)
def test_ac7_the_app_works_and_reports_503_with_no_usable_model(
    clean_db: Engine,
    clock: FakeClock,
    test_settings: Callable[..., Settings],
    changes: dict[str, Any],
) -> None:
    app = create_app(test_settings(**changes), clock=clock)
    with TestClient(app, base_url="https://testserver") as client:
        assert register(client).status_code == 201
        assert error_code(suggest(client)) == (503, "suggestions_unavailable")


def test_the_configured_model_is_the_one_used(
    clean_db: Engine, clock: FakeClock, test_settings: Callable[..., Settings]
) -> None:
    """Through the real client and a stub server: a 503 alone couldn't show it's wired up."""
    stub = Stub()
    stub.answer(json.dumps({"dimensions": {"mood": {"quote": NOTE, "score": 2}}, "tags": []}))
    settings = test_settings(ollama_url=stub.url, ollama_model="some-model")
    try:
        with TestClient(create_app(settings, clock=clock), base_url="https://testserver") as client:
            assert register(client).status_code == 201
            assert suggest(client).json() == {"scores": {"mood": 2}, "tags": []}
    finally:
        stub.server.shutdown()
        stub.server.server_close()
    assert stub.requests[0]["body"]["model"] == "some-model"


def test_ac7_it_needs_a_session(
    new_client: NewClient, suggestion_model: FakeSuggestionModel
) -> None:
    assert error_code(suggest(new_client())) == (401, "not_authenticated")
    assert suggestion_model.calls == []


def test_ac7_it_needs_a_csrf_token(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    response = client.post(f"/api/checkins/{DAY}/suggestion", json={"text": NOTE})
    assert error_code(response) == (403, "csrf_failed")
    assert suggestion_model.calls == []


@pytest.mark.parametrize(
    "note", ["", "   \n ", MARKER + "x" * 2000], ids=["empty", "only spaces", "too long"]
)
def test_ac7_text_out_of_bounds_is_refused_without_repeating_it(
    client: TestClient, suggestion_model: FakeSuggestionModel, note: str
) -> None:
    response = suggest(client, note)

    assert error_code(response) == (422, "invalid_request")
    assert MARKER not in response.text
    assert suggestion_model.calls == []


def test_ac7_exactly_the_limit_is_allowed(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    assert suggest(client, "x" * 2000).status_code == 200
    assert len(suggestion_model.calls) == 1


def test_a_day_outside_the_editable_window_is_refused(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    assert error_code(suggest(client, day=OLD_DAY)) == (422, "date_out_of_range")
    assert suggestion_model.calls == []


def test_ac8_no_transaction_stays_open_during_the_model_call(
    client: TestClient, suggestion_model: FakeSuggestionModel, engine: Engine
) -> None:
    seen: list[str] = []

    def check() -> None:
        with engine.connect() as conn:
            seen.extend(
                conn.execute(
                    text(
                        "SELECT usename || ': ' || state FROM pg_stat_activity "
                        "WHERE usename IN ('lumen_app', 'lumen_auth') "
                        "AND datname = current_database() AND xact_start IS NOT NULL"
                    )
                ).scalars()
            )

    suggestion_model.during_call = check

    assert suggest(client).status_code == 200
    assert len(suggestion_model.calls) == 1
    assert seen == []


def test_other_requests_are_served_while_the_model_is_thinking(
    client: TestClient, suggestion_model: FakeSuggestionModel
) -> None:
    """A model call takes seconds. If it blocked the server, the whole app would freeze with it."""
    statuses: list[int] = []

    def serve_another_request() -> None:
        # A daemon thread: if the server is blocked, this must fail rather than hang the suite.
        other = Thread(
            target=lambda: statuses.append(client.get("/api/auth/me").status_code), daemon=True
        )
        other.start()
        other.join(timeout=2)

    suggestion_model.during_call = serve_another_request

    assert suggest(client).status_code == 200
    assert statuses == [200]


def test_ac9_the_model_is_offered_only_the_caller_s_tags(
    new_client: NewClient, suggestion_model: FakeSuggestionModel
) -> None:
    first, second = new_client(), new_client()
    assert register(first).status_code == 201
    assert register(second, "second@example.com").status_code == 201
    saved = first.put(
        f"/api/checkins/{DAY}",
        json={"scores": SCORES, "tags": ["only_first_has_this", "exercise"]},
        headers=csrf(first),
    )
    assert saved.status_code == 200

    assert suggest(first).status_code == 200
    assert suggest(second).status_code == 200

    offered_first, offered_second = (call[2] for call in suggestion_model.calls)
    assert "only_first_has_this" in offered_first
    assert offered_first.count("exercise") == 1  # in both lists, offered once
    assert set(offered_first) >= set(STARTER_TAGS)
    assert offered_second == STARTER_TAGS


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ({"mode": "free_text"}, "free_text"),
        ({}, "structured"),
        ({"mode": "structured"}, "structured"),
    ],
)
def test_ac10_mode_is_stored(
    client: TestClient, engine: Engine, sent: dict[str, str], stored: str
) -> None:
    response = client.put(
        f"/api/checkins/{DAY}", json={"scores": SCORES, **sent}, headers=csrf(client)
    )

    assert response.status_code == 200
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT mode::text FROM checkins")) == stored


def test_ac10_an_unknown_mode_is_refused(client: TestClient) -> None:
    response = client.put(
        f"/api/checkins/{DAY}", json={"scores": SCORES, "mode": "other"}, headers=csrf(client)
    )
    assert error_code(response) == (422, "invalid_request")


def test_the_log_identifies_a_suggestion_by_its_route(
    client: TestClient, suggestion_model: FakeSuggestionModel, log_lines: list[str]
) -> None:
    suggestion_model.error = SuggestionsUnavailableError()
    log_lines.clear()

    suggest(client)

    line = json.loads(log_lines[-1])
    assert line["route"] == "/api/checkins/{local_date}/suggestion"
    assert (line["status"], line["error"]) == (503, "suggestions_unavailable")
