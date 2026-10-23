"""Test data helpers for integration tests."""

import uuid

from sqlalchemy.orm import Session

from lumen.db.repository import create_user


def new_user(session: Session, email: str | None = None) -> uuid.UUID:
    """Create a user with a unique placeholder email unless one is given."""
    return create_user(session, email or f"user-{uuid.uuid4().hex}@example.invalid")
