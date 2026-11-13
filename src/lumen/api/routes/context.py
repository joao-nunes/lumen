"""Personal context (spec 010): one short text per person, Tier 0, never logged."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints

from lumen.api.dependencies import ContainerDep, CurrentUser, UserDb
from lumen.api.errors import error_responses
from lumen.db.repository import get_context, save_context
from lumen.domain.context import MAX_CONTEXT_LENGTH

router = APIRouter(prefix="/api")

ContextText = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_CONTEXT_LENGTH)
]


class ContextIn(BaseModel):
    text: ContextText


class ContextOut(BaseModel):
    # "" when the person has none.
    text: str


@router.get("/context", responses=error_responses(401))
def read_context(user: CurrentUser, db: UserDb) -> ContextOut:
    return ContextOut(text=get_context(db, user.user_id))


@router.put("/context", responses=error_responses(401, 403, 415, 422))
def write_context(
    body: ContextIn, user: CurrentUser, db: UserDb, container: ContainerDep
) -> ContextOut:
    """Replaces the person's context. Empty text deletes it."""
    save_context(db, user.user_id, body.text, container.clock())
    return ContextOut(text=body.text)
