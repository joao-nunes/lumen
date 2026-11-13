"""AC-2 and AC-3 of spec 006: the client against a stub server, and the local-only rule."""

import hashlib
import json
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from pydantic import SecretStr

from lumen.api.app import create_app
from lumen.config import Settings
from lumen.domain.dimensions import Dimension
from lumen.suggestions.model import Suggestion, SuggestionsUnavailableError
from lumen.suggestions.ollama import OllamaSuggestionModel, check_local_only
from lumen.suggestions.prompt import measured_requests, prompt_fingerprint

TEXT = "marker_private_text slept badly"
ASKED = (Dimension.MOOD, Dimension.STRESS)
TAGS = ("poor_sleep", "exercise")


class Stub:
    """A stand-in for Ollama: records requests and answers with whatever `reply` says."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply: Callable[[BaseHTTPRequestHandler], None] = lambda h: None
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                stub.requests.append({"path": self.path, "body": json.loads(body)})
                stub.reply(self)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, content: object) -> None:
        self.send(200, json.dumps({"message": {"role": "assistant", "content": content}}))

    def send(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        def reply(handler: BaseHTTPRequestHandler) -> None:
            handler.send_response(status)
            for name, value in (headers or {}).items():
                handler.send_header(name, value)
            handler.send_header("Content-Length", str(len(body.encode())))
            handler.end_headers()
            handler.wfile.write(body.encode())

        self.reply = reply


@pytest.fixture
def stub() -> Iterator[Stub]:
    server = Stub()
    yield server
    server.server.shutdown()
    server.server.server_close()


def suggest(stub: Stub, *, timeout: float = 5) -> Suggestion:
    model = OllamaSuggestionModel(stub.url, "some-model", timeout_seconds=timeout)
    return model.suggest(TEXT, ASKED, TAGS)


def reply(tags: object = (), **dimensions: object) -> str:
    """A model's answer: each dimension as (quote, score), or absent for null."""
    items = {
        name: {"quote": value[0], "score": value[1]} if isinstance(value, tuple) else value
        for name, value in dimensions.items()
    }
    return json.dumps({"dimensions": items, "tags": list(tags) if tags != "x" else "x"})


def test_ac2_a_valid_reply_gives_the_suggestion(stub: Stub) -> None:
    stub.answer(reply(["poor_sleep"], mood=("slept badly", 3), stress=(None, None)))

    assert suggest(stub) == Suggestion(scores={Dimension.MOOD: 3}, tags=frozenset({"poor_sleep"}))

    [request] = stub.requests
    body = request["body"]
    assert request["path"] == "/api/chat"
    assert body["model"] == "some-model"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"]["temperature"] == 0
    assert body["messages"][-1] == {"role": "user", "content": TEXT}


def test_ac2_the_prompt_uses_the_anchors_the_form_shows(stub: Stub) -> None:
    stub.answer(reply())
    suggest(stub)

    system = stub.requests[0]["body"]["messages"][0]
    assert system["role"] == "system"
    assert "Struggling to feel anything positive" in system["content"]  # mood 1
    assert "Feels like too much to cope with" in system["content"]  # stress 5
    assert "Hard to get through basic tasks" not in system["content"]  # energy wasn't asked
    assert '"energy"' not in system["content"]  # nor in the reply's shape
    assert "poor_sleep, exercise" in system["content"]
    assert TEXT not in system["content"]


def test_the_client_sends_the_prompt_that_was_measured(stub: Stub) -> None:
    stub.answer(reply())
    model = OllamaSuggestionModel(stub.url, "some-model")
    for dimensions, tags in measured_requests():
        model.suggest(TEXT, dimensions, tags)

    sent = "\n".join(r["body"]["messages"][0]["content"] for r in stub.requests)
    assert len(stub.requests) == 1
    assert hashlib.sha256(sent.encode()).hexdigest() == prompt_fingerprint()


def test_a_score_counts_only_if_its_quote_is_really_in_the_note(stub: Stub) -> None:
    stub.answer(
        reply(
            mood=("Slept   BADLY.", 3),  # the same words, in another case and spacing
            stress=("had a terrible meeting", 5),  # invented evidence
            energy=("", 2),
            motivation=(None, 2),
        )
    )
    model = OllamaSuggestionModel(stub.url, "some-model")
    asked = (Dimension.MOOD, Dimension.STRESS, Dimension.ENERGY, Dimension.MOTIVATION)

    assert model.suggest(TEXT, asked, ()) == Suggestion(scores={Dimension.MOOD: 3})


def test_scores_written_as_text_are_read_as_numbers(stub: Stub) -> None:
    """Smaller models write "score": "3". Reading only numbers cost them almost every score."""
    stub.answer(
        reply(
            mood=("slept badly", "3"),
            stress=("slept badly", "null"),
            energy=("slept badly", "9"),
            motivation=("slept badly", "three"),
            concentration=("slept badly", "2.5"),
        )
    )
    model = OllamaSuggestionModel(stub.url, "some-model")

    assert model.suggest(TEXT, tuple(Dimension), ()) == Suggestion(scores={Dimension.MOOD: 3})


def test_a_quote_matches_however_its_accents_are_encoded(stub: Stub) -> None:
    note = unicodedata.normalize("NFC", "noite péssima")
    stub.answer(reply(sleep_quality=(unicodedata.normalize("NFD", note), 1)))
    model = OllamaSuggestionModel(stub.url, "some-model")

    assert model.suggest(note, [Dimension.SLEEP_QUALITY], ()) == Suggestion(
        scores={Dimension.SLEEP_QUALITY: 1}
    )


def test_a_trailing_slash_on_the_url_is_fine(stub: Stub) -> None:
    stub.answer(reply())
    OllamaSuggestionModel(f"{stub.url}/", "some-model").suggest(TEXT, ASKED, TAGS)
    assert stub.requests[0]["path"] == "/api/chat"


@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param("```json\n{}\n```", id="in a code fence"),
        pytest.param('{}\n{{"dimensions": {{}}, "tags": []}}', id="followed by another object"),
        pytest.param("Here it is: {} Hope that helps.", id="with words around it"),
    ],
)
def test_only_the_first_json_object_is_read(stub: Stub, wrap: str) -> None:
    stub.answer(wrap.format(reply(mood=("slept badly", 2))))
    assert suggest(stub) == Suggestion(scores={Dimension.MOOD: 2})


def test_ac6_values_outside_what_was_asked_are_dropped(stub: Stub) -> None:
    quote = "slept badly"
    stub.answer(
        reply(
            ["exercise", "not_listed", 7],
            mood=(quote, 9),
            stress=(quote, True),
            energy=(quote, 3),  # a real dimension, but not asked
            invented=(quote, 3),
        )
    )
    assert suggest(stub) == Suggestion(scores={}, tags=frozenset({"exercise"}))


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(lambda s: s.send(404, '{"error":"model not found"}'), id="no such model"),
        pytest.param(lambda s: s.send(500, TEXT), id="server error"),
        pytest.param(lambda s: s.send(200, "not json " + TEXT), id="reply isn't JSON"),
        pytest.param(lambda s: s.answer("not json " + TEXT), id="content isn't JSON"),
        pytest.param(lambda s: s.answer('{"scores": {"mood"'), id="content cut off"),
        pytest.param(lambda s: s.send(200, "[1, 2]"), id="reply has the wrong shape"),
        pytest.param(lambda s: s.answer("[1, 2]"), id="content has no object"),
        pytest.param(lambda s: s.answer(None), id="content is null"),
        pytest.param(lambda s: s.answer(7), id="content is a number"),
        pytest.param(lambda s: s.answer('{"a":' + "[" * 100_000), id="nested too deeply"),
        pytest.param(lambda s: s.answer('{"tags": []}'), id="no dimensions"),
        pytest.param(lambda s: s.answer('{"dimensions": {}}'), id="no tags"),
        pytest.param(lambda s: s.answer(json.dumps({"dimensions": [1], "tags": []})), id="a list"),
        pytest.param(lambda s: s.answer(reply("x")), id="tags are a string"),
        pytest.param(
            # A valid answer, so only the status can refuse it.
            lambda s: s.send(
                302,
                json.dumps({"message": {"content": reply(mood=("slept badly", 3))}}),
                {"Location": "http://127.0.0.1:9/"},
            ),
            id="a redirect",
        ),
    ],
)
def test_ac2_a_bad_reply_raises_one_error_without_the_text(
    stub: Stub, arrange: Callable[[Stub], None]
) -> None:
    arrange(stub)

    with pytest.raises(SuggestionsUnavailableError) as caught:
        suggest(stub)

    assert "marker_private_text" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_ac2_an_unreachable_server_raises_the_same_error() -> None:
    with pytest.raises(SuggestionsUnavailableError):
        OllamaSuggestionModel("http://127.0.0.1:9", "some-model").suggest(TEXT, ASKED, TAGS)


def test_ac2_a_slow_model_times_out(stub: Stub) -> None:
    stub.reply = lambda handler: time.sleep(1)

    started = time.monotonic()
    with pytest.raises(SuggestionsUnavailableError):
        suggest(stub, timeout=0.1)
    assert time.monotonic() - started < 0.9


def test_a_redirect_is_never_followed_even_to_a_valid_answer(stub: Stub) -> None:
    """A 307 repeats the POST, so following it would send the text wherever it pointed."""
    answer = json.dumps({"message": {"content": reply(mood=("slept badly", 3))}}).encode()

    def redirect_once(handler: BaseHTTPRequestHandler) -> None:
        moved = handler.path == "/api/chat"
        handler.send_response(307 if moved else 200)
        if moved:
            handler.send_header("Location", f"{stub.url}/elsewhere")
        handler.send_header("Content-Length", "0" if moved else str(len(answer)))
        handler.end_headers()
        if not moved:
            handler.wfile.write(answer)

    stub.reply = redirect_once

    with pytest.raises(SuggestionsUnavailableError):
        suggest(stub)
    assert [request["path"] for request in stub.requests] == ["/api/chat"]


def test_a_proxy_setting_cannot_carry_the_text_away(
    stub: Stub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proxy would see the raw text, and it may be on another machine."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    stub.answer(reply(mood=("slept badly", 2)))

    assert suggest(stub) == Suggestion(scores={Dimension.MOOD: 2})


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://127.8.8.8:11434",
        "http://localhost:11434",
        "http://[::1]:11434",
        "https://localhost",
    ],
)
def test_ac3_loopback_addresses_are_allowed(url: str) -> None:
    check_local_only(url, "qwen3:8b")


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.5:11434",
        "http://example.com",
        "http://0.0.0.0:11434",  # every interface, not this machine
        "http://localhost.example.com",
        "http://127.0.0.1.example.com",
        "http://127.0.0.1@example.com",  # the host here is example.com
        "http://2130706433",  # 127.0.0.1 as a number, but nothing should need this form
        "ftp://localhost",
        "localhost:11434",
        "",
    ],
)
def test_ac3_anything_else_is_refused(url: str) -> None:
    with pytest.raises(ValueError, match="OLLAMA_URL"):
        check_local_only(url, "qwen3:8b")


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "kimi-k2:cloud", "SOME-MODEL:1T-CLOUD"])
def test_ac3_cloud_models_are_refused(model: str) -> None:
    with pytest.raises(ValueError, match="OLLAMA_MODEL"):
        check_local_only("http://127.0.0.1:11434", model)


@pytest.mark.parametrize("model", ["qwen3:8b", "gemma4:e4b", "cloudy-model:8b", None])
def test_ac3_local_models_and_no_model_are_allowed(model: str | None) -> None:
    check_local_only("http://127.0.0.1:11434", model)


@pytest.mark.parametrize(
    "changes",
    [{"ollama_url": "http://192.168.1.5:11434"}, {"ollama_model": "gpt-oss:120b-cloud"}],
)
def test_ac3_the_app_refuses_to_start_with_settings_that_leave_the_machine(
    changes: dict[str, str],
) -> None:
    settings = Settings(_env_file=None, secret_key=SecretStr("x" * 32), **changes)
    with pytest.raises(ValueError, match="OLLAMA_"):
        create_app(settings)
