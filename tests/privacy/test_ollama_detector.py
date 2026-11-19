"""Spec 011 AC-11: the Ollama detector keeps text on this machine, and returns the raw reply."""

import json
import time
from collections.abc import Callable
from importlib.resources import files

import pytest

from lumen.privacy.local_model import LocalModelError
from lumen.privacy.ollama import PROMPT_NAME, OllamaDetector
from lumen.privacy.redaction import RedactionUnavailableError, Redactor
from tests.ollama_stub import Stub

TEXT = "marker_private_text Ana called from Porto."


def detect(stub: Stub, *, timeout: float = 5) -> str:
    return OllamaDetector(stub.url, "some-model", timeout_seconds=timeout).detect(TEXT)


def test_ac11_the_request_sends_the_prompt_and_the_note_and_returns_the_raw_reply(
    stub: Stub,
) -> None:
    stub.answer("whatever the model wrote")

    assert detect(stub) == "whatever the model wrote"  # raw: the redactor parses it

    [request] = stub.requests
    body = request["body"]
    assert request["path"] == "/api/chat"
    assert (body["model"], body["stream"], body["think"]) == ("some-model", False, False)
    assert body["options"]["temperature"] == 0
    assert "format" not in body  # this Ollama refuses structured output, failing every call
    prompt = files("lumen.privacy").joinpath("prompts", f"{PROMPT_NAME}.txt").read_text("utf-8")
    assert body["messages"] == [
        {"role": "system", "content": prompt},
        {"role": "user", "content": TEXT},
    ]


def test_ac11_the_reply_goes_through_the_redactor_s_checks(stub: Stub) -> None:
    stub.answer(json.dumps({"findings": [{"text": "Ana", "type": "PERSON"}]}))
    redactor = Redactor(OllamaDetector(stub.url, "some-model"))

    assert redactor.pseudonymize(TEXT, owner="u1", context="").text == (
        "marker_private_text [PERSON_1] called from Porto."
    )

    stub.answer(json.dumps({"findings": [{"text": "Ana", "type": "PERSONS"}]}))
    with pytest.raises(RedactionUnavailableError):
        redactor.pseudonymize(TEXT, owner="u1", context="")


@pytest.mark.parametrize(
    ("url", "model", "setting"),
    [
        ("http://192.168.1.5:11434", "some-model", "OLLAMA_URL"),
        ("http://127.0.0.1:11434", "gpt-oss:120b-cloud", "OLLAMA_MODEL"),
    ],
)
def test_ac11_a_detector_that_would_send_text_away_can_t_be_made(
    url: str, model: str, setting: str
) -> None:
    with pytest.raises(ValueError, match=setting):
        OllamaDetector(url, model)


def test_ac11_a_proxy_setting_cannot_carry_the_text_away(
    stub: Stub, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    stub.answer('{"findings": []}')

    assert detect(stub) == '{"findings": []}'


def test_ac11_a_redirect_is_never_followed_even_to_a_valid_answer(stub: Stub) -> None:
    stub.redirect_once(json.dumps({"message": {"content": '{"findings": []}'}}))

    with pytest.raises(LocalModelError):
        detect(stub)
    assert [request["path"] for request in stub.requests] == ["/api/chat"]


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(lambda s: s.send(500, TEXT), id="server error"),
        pytest.param(lambda s: s.send(200, "not json " + TEXT), id="reply isn't JSON"),
        pytest.param(lambda s: s.send(200, "[1, 2]"), id="reply has the wrong shape"),
        pytest.param(lambda s: s.answer(None), id="content isn't text"),
        pytest.param(lambda s: s.answer(7), id="content is a number"),
    ],
)
def test_a_failed_call_raises_without_the_text(stub: Stub, arrange: Callable[[Stub], None]) -> None:
    arrange(stub)

    with pytest.raises(LocalModelError) as caught:
        detect(stub)

    assert "marker_private_text" not in str(caught.value)
    # Neither chained nor kept as context: the original error can quote the reply or the text.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_a_slow_model_times_out(stub: Stub) -> None:
    stub.reply = lambda handler: time.sleep(1)

    started = time.monotonic()
    with pytest.raises(LocalModelError):
        detect(stub, timeout=0.1)
    assert time.monotonic() - started < 0.9
