"""Middleware: request guards (spec 001 §2.4) and security headers (spec 003)."""

import json
import time
import uuid
from collections.abc import Awaitable, Callable, Collection
from contextlib import suppress

from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lumen.api.errors import ERROR_CODES, error_response
from lumen.api.event_log import EventLog

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_ERROR_BODY = 4096  # the API's errors are far smaller; a cut-off body fails to parse

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
}


class SecurityHeadersMiddleware:
    """Adds the security headers to every response, and keeps API data out of browser caches."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(SECURITY_HEADERS)
                if scope["path"].startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self._app(scope, receive, send_with_headers)


class RequestLogMiddleware:
    """Gives each request an ID, logs it, and turns a crash into a JSON 500 (spec 005).

    Catching the crash here is what keeps it from uvicorn, which would print the exception's
    message, and PostgreSQL's messages repeat the values they were given.
    """

    def __init__(self, app: ASGIApp, *, log: EventLog) -> None:
        self._app, self._log = app, log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        status: int | None = None
        error_body = bytearray()
        crashed = False

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            elif status is not None and status >= 400:
                error_body.extend(message.get("body", b"")[: MAX_ERROR_BODY - len(error_body)])
            await send(message)

        try:
            await self._app(scope, receive, send_with_id)
        except Exception as exc:
            crashed = True
            self._log.crash(request_id, exc)
            if status is None:
                # The client may be gone, and this mustn't reach uvicorn either.
                with suppress(Exception):
                    await error_response(500, "internal_error", "Something went wrong")(
                        scope, receive, send_with_id
                    )

        if scope["path"] == "/api" or scope["path"].startswith("/api/"):
            final = 500 if status is None else status
            route = scope.get("route")
            self._log.request(
                request_id=request_id,
                method=scope["method"],
                route=route.path if isinstance(route, APIRoute) else None,
                status=final,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error="internal_error"
                if crashed
                else _listed_error_code(error_body)
                if final >= 400
                else None,
            )


class RequestGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, allowed_origins: Collection[str]) -> None:
        super().__init__(app)
        self._allowed_origins = frozenset(allowed_origins)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            own_origin = f"{request.url.scheme}://{request.url.netloc}"
            # Browsers send Origin on cross-origin requests; it may be absent on
            # same-origin ones and from non-browser clients.
            if origin is not None and origin not in self._allowed_origins | {own_origin}:
                return error_response(403, "forbidden_origin", "Origin not allowed")
            # JSON only: HTML forms on other sites can't produce it.
            if _has_body(request) and _media_type(request) != "application/json":
                return error_response(415, "unsupported_media_type", "Use application/json")
        return await call_next(request)


def _has_body(request: Request) -> bool:
    length = request.headers.get("content-length")
    return "transfer-encoding" in request.headers or (length is not None and length != "0")


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _listed_error_code(body: bytes | bytearray) -> str:
    """The response's error code if it's on the fixed list, so nothing else can reach the log."""
    try:
        code = json.loads(body)["error"]["code"]
    except (ValueError, KeyError, TypeError, RecursionError):
        return "unknown"
    return code if isinstance(code, str) and code in ERROR_CODES else "unknown"
