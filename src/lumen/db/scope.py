"""Tell PostgreSQL which user the current transaction acts for.

Row-level security policies compare each row's owner with
current_app_user_id(), which reads the transaction-local setting written
here. Being transaction-local, it cannot leak to another request through a
pooled connection: it disappears at commit or rollback.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

USER_SETTING = "lumen.user_id"


def scope_to_user(session: Session, user_id: uuid.UUID) -> None:
    """Act as `user_id` until the session's current transaction ends."""
    session.execute(select(func.set_config(USER_SETTING, str(user_id), True)))


@contextmanager
def user_transaction(factory: sessionmaker[Session], user_id: uuid.UUID) -> Iterator[Session]:
    """A transaction scoped to `user_id`, committed on success, rolled back on error."""
    with factory.begin() as session:
        scope_to_user(session, user_id)
        yield session
