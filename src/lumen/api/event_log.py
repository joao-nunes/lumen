"""The application's log (spec 005): one JSON object per line, and only the fields named here.

The allowlist is this class's interface. Every value comes from Lumen's own code or a fixed
list, and no method takes free text, a dictionary or an exception message.
"""

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import suppress
from datetime import UTC
from types import TracebackType

from lumen.api.clock import Clock

METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_MIDDLEWARE = "lumen.api.middleware"  # the frames that catch every crash, so they add nothing


def _to_stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )


def _lumen_frames(tb: TracebackType | None) -> list[str]:
    """Lumen's own frames, innermost first: where it failed, without any values."""
    frames: list[str] = []
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "")
        if module.startswith("lumen.") and module != _MIDDLEWARE:
            frames.append(f"{module}:{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}")
        tb = tb.tb_next
    return frames[::-1]


class EventLog:
    def __init__(self, clock: Clock, write: Callable[[str], None] = _to_stderr) -> None:
        self._clock, self._write = clock, write

    def request(
        self,
        *,
        request_id: str,
        method: str,
        route: str | None,
        status: int,
        duration_ms: int,
        error: str | None,
    ) -> None:
        # Logging must never change a response (spec 005 §2.5).
        with suppress(Exception):
            self._write(
                self._line(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "method": method if method in METHODS else "OTHER",
                        "route": route,
                        "status": status,
                        "duration_ms": duration_ms,
                        "error": error,
                    }
                )
            )

    def crash(self, request_id: str, exc: Exception) -> None:
        with suppress(Exception):
            self._write(
                self._line(
                    {
                        "event": "crash",
                        "request_id": request_id,
                        "exceptions": [
                            f"{type(e).__module__}.{type(e).__qualname__}"
                            for e in _exception_chain(exc)
                        ],
                        "frames": _lumen_frames(exc.__traceback__),
                    }
                )
            )

    def _line(self, fields: dict[str, object]) -> str:
        ts = self._clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return json.dumps({"ts": ts, **fields}, separators=(",", ":"))
