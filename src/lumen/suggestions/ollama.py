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

from lumen.domain.dimensions import (
    DIMENSIONS,
    SCALE_MAX,
    SCALE_MIN,
    Dimension,
    Polarity,
)
from lumen.suggestions.model import Suggestion, SuggestionsUnavailableError, keep_valid

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


def _describe(dimension: Dimension) -> str:
    spec = DIMENSIONS[dimension]
    direction = (
        "Higher means MORE of it, which is worse."
        if spec.polarity is Polarity.HIGHER_IS_WORSE
        else "Higher is better."
    )
    anchors = "\n".join(
        f"  {SCALE_MIN + i} = {anchor.label}: {anchor.description}"
        for i, anchor in enumerate(spec.anchors)
    )
    return f"{dimension.value} ({spec.display_name}). {direction}\n{anchors}"


def _system_prompt(dimensions: Collection[Dimension], tags: Collection[str]) -> str:
    described = "\n\n".join(_describe(d) for d in dimensions)
    offered = ", ".join(tags) if tags else "(none)"
    shape = json.dumps(
        {
            "dimensions": {
                d.value: {"quote": "... or null", "score": "1-5 or null"} for d in dimensions
            },
            "tags": ["..."],
        }
    )
    return f"""\
You turn a person's short note about their day into check-in scores. The note may be in English \
or Portuguese. Never give advice.

Dimensions, each scored {SCALE_MIN} to {SCALE_MAX}:

{described}

For every dimension, first copy into "quote" the exact words from the note that directly describe \
THAT dimension, and then give "score". If no words in the note directly describe that dimension, \
"quote" and "score" must both be null. Do not infer one dimension from another: an event or a mood \
is not evidence of energy, motivation, stress or concentration. Most notes address only one to \
three dimensions.
Read negation carefully: "not stressed at all" means stress is 1.
Choose a tag only if the note states it outright. Allowed tags: {offered}.

Examples:
Note: "dentist at 3, got the car washed" -> every quote and score is null.
Note: "felt great after seeing my cousin" -> mood: quote "felt great", score 5. Every other \
dimension null.
Note: "dormi bem, mas o trabalho deu-me nervos" -> sleep_quality: quote "dormi bem", score 4. \
stress: quote "deu-me nervos", score 4. Every other dimension null.

Reply with only one JSON object and nothing else, in this exact form:
{shape}
"""


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
            scores[key] = item.get("score")
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
        try:
            # trust_env=False: a proxy setting would carry the text to another machine.
            response = httpx2.post(
                f"{self._url.rstrip('/')}/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "seed": 0},
                    "messages": [
                        {"role": "system", "content": _system_prompt(dimensions, tags)},
                        {"role": "user", "content": text},
                    ],
                },
                timeout=self._timeout,
                trust_env=False,
                follow_redirects=False,
            )
            response.raise_for_status()
            if response.status_code != 200:  # raise_for_status allows a redirect
                raise ValueError("Unexpected status")
            reply = _first_json_object(response.json()["message"]["content"])
            scores, chosen = _evidenced_scores(reply["dimensions"], text), reply["tags"]
            if not isinstance(chosen, list):
                raise TypeError("Unexpected shape")
        except (httpx2.HTTPError, ValueError, KeyError, TypeError):
            # from None: these can quote the reply, or the request's text.
            raise SuggestionsUnavailableError from None
        return keep_valid(scores, chosen, dimensions, tags)
