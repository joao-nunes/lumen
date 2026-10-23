"""FastAPI dependencies shared by endpoints. Walking skeleton."""

from collections.abc import Iterator

from sqlalchemy.orm import Session


def user_session() -> Iterator[Session]:
    """A database session scoped (via RLS) to the logged-in user."""
    raise NotImplementedError
