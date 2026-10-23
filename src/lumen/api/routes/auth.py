"""Authentication endpoints (spec 001 §2.2). Orchestration only: logic lives in lumen.auth."""

import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from lumen.api.dependencies import AuthDb, ContainerDep, CurrentUser, OptionalUser
from lumen.auth.login import login_with_rate_limit
from lumen.auth.service import InvalidCredentialsError
from lumen.db.models import User

router = APIRouter(prefix="/api/auth")

# Bounds the Argon2 work a single request can force (policy max is 256 characters).
MAX_PASSWORD_INPUT = 1024


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=MAX_PASSWORD_INPUT)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=MAX_PASSWORD_INPUT)
    new_password: str = Field(max_length=MAX_PASSWORD_INPUT)


class Registered(BaseModel):
    user_id: uuid.UUID


class Me(BaseModel):
    user_id: uuid.UUID
    email: str


@router.post("/register", status_code=201)
def register(
    body: Credentials, response: Response, container: ContainerDep, db: AuthDb
) -> Registered:
    user_id = container.auth.register(db, body.email, body.password)
    issued = container.auth.login(db, body.email, body.password, container.clock())
    db.commit()
    container.cookies.set(response, issued.token)
    return Registered(user_id=user_id)


@router.post("/login", status_code=204)
def login(body: Credentials, request: Request, container: ContainerDep, db: AuthDb) -> Response:
    try:
        issued = login_with_rate_limit(
            db, container.auth, container.limiter, body.email, body.password, container.clock()
        )
    except InvalidCredentialsError:
        db.commit()  # the failed attempt must persist, or the rate limit never triggers
        raise
    # Session rotation: whatever session this browser had is ended.
    previous = request.cookies.get(container.cookies.session_name)
    if previous is not None:
        container.auth.logout(db, previous)
    db.commit()
    response = Response(status_code=204)
    container.cookies.set(response, issued.token)
    return response


@router.post("/logout", status_code=204)
def logout(user: OptionalUser, container: ContainerDep, db: AuthDb) -> Response:
    if user is not None:
        container.auth.logout(db, user.session_token)
        db.commit()
    response = Response(status_code=204)
    container.cookies.clear(response)
    return response


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChange, user: CurrentUser, container: ContainerDep, db: AuthDb
) -> Response:
    issued = container.auth.change_password(
        db, user.user_id, body.current_password, body.new_password, container.clock()
    )
    db.commit()
    response = Response(status_code=204)
    container.cookies.set(response, issued.token)
    return response


@router.get("/me")
def me(user: CurrentUser, db: AuthDb) -> Me:
    email = db.scalar(select(User.email).where(User.id == user.user_id))
    return Me(user_id=user.user_id, email=email or "")
