"""The one way Lumen talks to a model on this machine, through Ollama (specs 006 and 011).

Everything sent here is Tier 0 and must never leave the machine, so this only talks to a loopback
address, refuses cloud models, ignores proxy settings and doesn't follow redirects. Suggestions and
redaction both send through `chat`, so a change can't weaken one copy of these controls.
"""

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

import httpx2

_CLOUD_MODEL = re.compile(r"[:-]cloud$", re.IGNORECASE)


class LocalModelError(Exception):
    """The model gave no usable reply. The message never repeats the request."""

    def __init__(self) -> None:
        super().__init__("The local model gave no usable reply")


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


def chat(
    url: str,
    model: str,
    *,
    system: str,
    user: str,
    timeout: float,
) -> str:
    """The model's reply to one exchange, as text. Callers check `url` and `model` when built."""
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        # trust_env=False: a proxy setting would carry the text to another machine.
        response = httpx2.post(
            f"{url.rstrip('/')}/api/chat",
            json=body,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("Unexpected shape")
    except (httpx2.HTTPError, ValueError, LookupError, TypeError, AttributeError, RecursionError):
        # from None: these can quote the reply, or the request's text.
        raise LocalModelError from None
    return content
