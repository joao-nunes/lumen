"""Finds identifiers with a model running on this machine, through Ollama (spec 011 §2.5).

The detector only asks: it returns the model's raw reply, and `Redactor` checks it. The wording
lives in `prompts/`, one file per version, and `evals/redaction/measured_prompt.json` records which
one met the bar.
"""

import hashlib
from importlib.resources import files

from lumen.privacy.local_model import chat, check_local_only

PROMPT_NAME = "redaction_v3"

# Read at import, so that a missing file stops the app from starting rather than failing later.
_PROMPT = files("lumen.privacy").joinpath("prompts", f"{PROMPT_NAME}.txt").read_text("utf-8")


def prompt_fingerprint() -> str:
    """The hash of what the model is sent besides the note."""
    return hashlib.sha256(_PROMPT.encode()).hexdigest()


class OllamaDetector:
    def __init__(self, url: str, model: str, *, timeout_seconds: float = 60) -> None:
        check_local_only(url, model)
        self._url, self._model, self._timeout = url, model, timeout_seconds

    def detect(self, text: str) -> str:
        # No JSON schema: this Ollama refuses structured output ("structured output is
        # unavailable"), so the prompt asks for the shape and the redactor's parser enforces it.
        return chat(self._url, self._model, system=_PROMPT, user=text, timeout=self._timeout)
