"""Composition root for the HTTP API (spec 001): the only place that builds engines and services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lumen.api.clock import Clock, system_clock
from lumen.api.cookies import CookieManager
from lumen.api.dependencies import Container
from lumen.api.errors import install_error_handlers
from lumen.api.middleware import RequestGuardMiddleware
from lumen.api.routes.auth import router as auth_router
from lumen.auth.policy import SessionPolicy
from lumen.auth.rate_limit import LoginRateLimiter
from lumen.auth.service import AuthService
from lumen.config import Settings
from lumen.db.session import make_engine, make_session_factory

MIN_SECRET_KEY_BYTES = 32


def create_app(settings: Settings, clock: Clock = system_clock) -> FastAPI:
    secret = settings.secret_key.get_secret_value().encode() if settings.secret_key else b""
    if len(secret) < MIN_SECRET_KEY_BYTES:
        raise ValueError(f"SECRET_KEY must be set to at least {MIN_SECRET_KEY_BYTES} bytes")

    policy = SessionPolicy.from_settings(settings)
    app_engine = make_engine(settings.database_url)
    auth_engine = make_engine(settings.auth_database_url)
    container = Container(
        clock=clock,
        auth=AuthService(policy=policy),
        limiter=LoginRateLimiter(),
        cookies=CookieManager(
            secret, secure=settings.cookie_secure, max_age=policy.absolute_timeout
        ),
        app_sessions=make_session_factory(app_engine),
        auth_sessions=make_session_factory(auth_engine),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app_engine.dispose()
        auth_engine.dispose()

    app = FastAPI(title="Lumen", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(RequestGuardMiddleware, allowed_origins=settings.allowed_origins)
    install_error_handlers(app)
    app.include_router(auth_router)
    return app
