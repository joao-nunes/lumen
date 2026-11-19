"""Suggestions from a model running on this machine, through Ollama (spec 006).

The text is Tier 0 and must never leave the machine. The controls that keep it here live in
`lumen.privacy.local_model`, which redaction shares (spec 011 §2.5).
"""

import json
import unicodedata
from collections.abc import Collection

from lumen.domain.dimensions import Dimension
from lumen.privacy.local_model import LocalModelError, chat, check_local_only
from lumen.suggestions.model import Suggestion, SuggestionsUnavailableError, keep_valid
from lumen.suggestions.prompt import checkin_extraction_prompt


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
        self,
        text: str,
        dimensions: Collection[Dimension],
        tags: Collection[str],
        context: str = "",
    ) -> Suggestion:
        # Outside the try: a broken template is a bug to see, not "the model is unavailable".
        system = checkin_extraction_prompt(dimensions, tags, context)
        try:
            content = chat(self._url, self._model, system=system, user=text, timeout=self._timeout)
            reply = _first_json_object(content)
            scores, chosen = _evidenced_scores(reply["dimensions"], text), reply["tags"]
            if not isinstance(chosen, list):
                raise TypeError("Unexpected shape")
        except (
            LocalModelError,
            ValueError,
            LookupError,
            TypeError,
            AttributeError,
            RecursionError,
        ):
            # from None: these can quote the reply, or the request's text.
            raise SuggestionsUnavailableError from None
        return keep_valid(scores, chosen, dimensions, tags)
