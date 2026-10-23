"""FastAPI dependencies: the container, database sessions, and who is calling."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from lumen.api.clock import Clock
from lumen.api.cookies import CookieManager
from lumen.api.errors import ApiError
from lumen.api.middleware import UNSAFE_METHODS
from lumen.auth.rate_limit import LoginRateLimiter
from lumen.auth.service import AuthService
from lumen.db.scope import user_transaction


@dataclass(frozen=True, slots=True)
class Container:
    """Everything endpoints need, built once by create_app (the composition root)."""

    clock: Clock
    auth: AuthService
    limiter: LoginRateLimiter
    cookies: CookieManager
    app_sessions: sessionmaker[Session]  # lumen_app: user data through RLS
    auth_sessions: sessionmaker[Session]  # lumen_auth: users and the auth schema


@dataclass(frozen=True, slots=True)
class Authenticated:
    user_id: uuid.UUID
    session_token: str


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def auth_db(container: ContainerDep) -> Iterator[Session]:
    """A lumen_auth session. Endpoints commit explicitly; anything uncommitted rolls back."""
    with container.auth_sessions() as db:
        yield db


AuthDb = Annotated[Session, Depends(auth_db)]


def optional_user(request: Request, container: ContainerDep, db: AuthDb) -> Authenticated | None:
    """The caller's valid session, if any. Unsafe requests must also carry a matching CSRF token,
    so every authenticated state change is protected without per-endpoint code."""
    token = request.cookies.get(container.cookies.session_name)
    if token is None:
        return None
    user_id = container.auth.resolve(db, token, container.clock())
    db.commit()  # persists last_seen_at updates and deletion of expired sessions
    if user_id is None:
        return None
    if request.method in UNSAFE_METHODS and not container.cookies.csrf_matches(
        token, request.headers.get("x-csrf-token")
    ):
        raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token")
    return Authenticated(user_id=user_id, session_token=token)


OptionalUser = Annotated[Authenticated | None, Depends(optional_user)]


def current_user(user: OptionalUser) -> Authenticated:
    if user is None:
        raise ApiError(401, "not_authenticated", "Not logged in", clear_session=True)
    return user


CurrentUser = Annotated[Authenticated, Depends(current_user)]


def user_session(container: ContainerDep, user: CurrentUser) -> Iterator[Session]:
    """A lumen_app session scoped (via RLS) to the logged-in user, committed on success."""
    with user_transaction(container.app_sessions, user.user_id) as db:
        yield db
