"""Suggestions from a model running on this machine, through Ollama (spec 006).

The text is Tier 0 and must never leave the machine, so this only talks to a loopback address,
refuses cloud models, ignores proxy settings and doesn't follow redirects.
"""

import ipaddress
import json
import re
import unicodedata
from collections.abc import Collection
from urllib.parse import urlsplit

import httpx2

from lumen.domain.dimensions import Dimension
from lumen.suggestions.model import Suggestion, SuggestionsUnavailableError, keep_valid
from lumen.suggestions.prompt import checkin_extraction_prompt

_CLOUD_MODEL = re.compile(r"[:-]cloud$", re.IGNORECASE)


def _is_loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_local_only(url: str, model: str | None) -> None:
    """Raises unless the settings keep text on this machine."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not _is_loopback(parts.hostname):
        raise ValueError("OLLAMA_URL must be a loopback address: text must stay on this machine")
    if model is not None and _CLOUD_MODEL.search(model):
        raise ValueError("OLLAMA_MODEL must not be a cloud model: text must stay on this machine")


def _normalized(text: str) -> str:
    folded = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return folded.strip(" .,!?;:\"'")


def _evidenced_scores(dimensions: object, text: str) -> dict[str, object]:
    """Keeps a score only if its quote really is in the note: models invent scores otherwise."""
    if not isinstance(dimensions, dict):
        raise TypeError("Unexpected shape")
    note = _normalized(text)
    scores: dict[str, object] = {}
    for key, item in dimensions.items():
        quote = item.get("quote") if isinstance(item, dict) else None
        if isinstance(quote, str) and (found := _normalized(quote)) and found in note:
            score = item.get("score")
            # Smaller models write "score": "3". keep_valid applies the real limits.
            scores[key] = int(score) if isinstance(score, str) and score.isdecimal() else score
    return scores


def _first_json_object(content: str) -> dict[str, object]:
    """Without a schema, models may wrap the object in a code fence or write more after it."""
    reply, _ = json.JSONDecoder().raw_decode(content, content.index("{"))
    if not isinstance(reply, dict):
        raise TypeError("Unexpected shape")
    return reply


class OllamaSuggestionModel:
    def __init__(self, url: str, model: str, *, timeout_seconds: float = 60) -> None:
        check_local_only(url, model)
        self._url, self._model, self._timeout = url, model, timeout_seconds

    def suggest(
        self, text: str, dimensions: Collection[Dimension], tags: Collection[str]
    ) -> Suggestion:
        # Outside the try: a broken template is a bug to see, not "the model is unavailable".
        system = checkin_extraction_prompt(dimensions, tags)
        try:
            # trust_env=False: a proxy setting would carry the text to another machine.
            response = httpx2.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "seed": 0},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                },
                timeout=self._timeout,
                trust_env=False,
                follow_redirects=False,
            )
            response.raise_for_status()
            reply = _first_json_object(response.json()["message"]["content"])
            scores, chosen = _evidenced_scores(reply["dimensions"], text), reply["tags"]
            if not isinstance(chosen, list):
                raise TypeError("Unexpected shape")
        except (
            httpx2.HTTPError,
            ValueError,
            LookupError,
            TypeError,
            AttributeError,
            RecursionError,
        ):
            # from None: these can quote the reply, or the request's text.
            raise SuggestionsUnavailableError from None
        return keep_valid(scores, chosen, dimensions, tags)
