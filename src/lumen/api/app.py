"""Composition root for the HTTP API (spec 001): the only place that builds engines and services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lumen.api.clock import Clock, system_clock
from lumen.api.cookies import CookieManager
from lumen.api.dependencies import Container
from lumen.api.errors import install_error_handlers
from lumen.api.event_log import EventLog
from lumen.api.middleware import (
    RequestGuardMiddleware,
    RequestLogMiddleware,
    SecurityHeadersMiddleware,
)
from lumen.api.routes.auth import router as auth_router
from lumen.api.routes.checkins import router as checkins_router
from lumen.api.routes.context import router as context_router
from lumen.api.routes.overview import router as overview_router
from lumen.api.web import WebApp
from lumen.auth.policy import SessionPolicy
from lumen.auth.rate_limit import LoginRateLimiter, PasswordChangeRateLimiter
from lumen.auth.service import AuthService
from lumen.config import Settings
from lumen.db.session import make_engine, make_session_factory
from lumen.suggestions.model import SuggestionModel
from lumen.suggestions.ollama import OllamaSuggestionModel, check_local_only

MIN_SECRET_KEY_BYTES = 32


def _configured_model(settings: Settings) -> SuggestionModel | None:
    if settings.ollama_model is None:
        return None
    return OllamaSuggestionModel(settings.ollama_url, settings.ollama_model)


def create_app(
    settings: Settings,
    clock: Clock = system_clock,
    log: EventLog | None = None,
    suggestions: SuggestionModel | None = None,
) -> FastAPI:
    secret = settings.secret_key.get_secret_value().encode() if settings.secret_key else b""
    if len(secret) < MIN_SECRET_KEY_BYTES:
        raise ValueError(f"SECRET_KEY must be set to at least {MIN_SECRET_KEY_BYTES} bytes")

    check_local_only(settings.ollama_url, settings.ollama_model)

    policy = SessionPolicy.from_settings(settings)
    app_engine = make_engine(settings.database_url)
    auth_engine = make_engine(settings.auth_database_url)
    container = Container(
        clock=clock,
        auth=AuthService(policy=policy),
        limiter=LoginRateLimiter(),
        password_change_limiter=PasswordChangeRateLimiter(),
        cookies=CookieManager(
            secret, secure=settings.cookie_secure, max_age=policy.absolute_timeout
        ),
        app_sessions=make_session_factory(app_engine),
        auth_sessions=make_session_factory(auth_engine),
        suggestions=_configured_model(settings) if suggestions is None else suggestions,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app_engine.dispose()
        auth_engine.dispose()

    # No API docs routes: they load a third-party script, which the CSP forbids (spec 003 Q1).
    app = FastAPI(title="Lumen", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.container = container
    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)
    # Outside the guard, to log what it refuses; inside the headers, so a crash's 500 gets them.
    app.add_middleware(RequestLogMiddleware, log=EventLog(clock) if log is None else log)
    # Added last, so it runs outermost: requests the guard refuses get the headers too.
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(checkins_router)
    app.include_router(overview_router)
    app.include_router(context_router)
    if settings.web_dist is not None:
        # An empty WEB_DIST means the current directory, which must never be published.
        if not (settings.web_dist / "index.html").is_file():
            raise ValueError(f"WEB_DIST has no index.html: {settings.web_dist.resolve()}")
        # Last: routes are matched in order, so the API always comes first.
        app.mount("/", WebApp(directory=settings.web_dist, html=True))
    return app
