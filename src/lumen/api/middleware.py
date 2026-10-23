"""Request guards applied to every unsafe request, before any endpoint runs (spec 001 §2.4)."""

from collections.abc import Awaitable, Callable, Collection

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from lumen.api.errors import error_response

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


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
