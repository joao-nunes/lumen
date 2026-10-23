"""Act as a production database role inside the test transaction.

Tests connect as the owner (a superuser, which bypasses RLS) so they can set
up data freely, then switch with SET LOCAL ROLE to exercise the exact
privileges and policies the application runs under. The switch ends with the
test's transaction.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from lumen.db.scope import scope_to_user

APP = "lumen_app"
AUTH = "lumen_auth"


def act_as(session: Session, role: str, user_id: uuid.UUID | None = None) -> None:
    session.execute(text(f"SET LOCAL ROLE {role}"))
    if user_id is not None:
        scope_to_user(session, user_id)


def act_as_owner(session: Session) -> None:
    session.execute(text("RESET ROLE"))
