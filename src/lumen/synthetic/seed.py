"""Seed a database with a synthetic persona that can log in.

Usage:
    uv run python -m lumen.synthetic.seed burnout --days 90 --seed 42
"""

import argparse
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from lumen.auth.models import PasswordCredential
from lumen.auth.passwords import Passwords
from lumen.config import get_settings
from lumen.db.repository import create_user, save_checkin
from lumen.db.session import make_engine, make_session_factory
from lumen.synthetic.personas import PERSONAS, generate


@dataclass(frozen=True, slots=True)
class SeededUser:
    user_id: uuid.UUID
    email: str
    password: str
    start: date
    checkins: int


def seed_persona(db: Session, persona: str, *, days: int, seed: int, end: date) -> SeededUser:
    start = end - timedelta(days=days - 1)
    checkins = generate(PERSONAS[persona], start, days, seed)
    # Synthetic users get addresses on the reserved .invalid TLD (RFC 2606).
    email = f"{persona}-{uuid.uuid4().hex[:8]}@example.invalid"
    password = secrets.token_urlsafe(18)
    user_id = create_user(db, email)
    db.add(PasswordCredential(user_id=user_id, password_hash=Passwords().hash(password)))
    for checkin in checkins:
        save_checkin(db, user_id, checkin)
    return SeededUser(user_id, email, password, start, len(checkins))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("persona", choices=sorted(PERSONAS))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="Last day of generated data (default: today)",
    )
    args = parser.parse_args()

    end: date = args.end or date.today()  # noqa: DTZ011 - local calendar day is intended

    # Dev tooling: runs as the owner, which bypasses row-level security.
    session_factory = make_session_factory(make_engine(get_settings().admin_database_url))
    with session_factory.begin() as session:
        user = seed_persona(session, args.persona, days=args.days, seed=args.seed, end=end)

    print(f"Created {user.email} with {user.checkins} check-ins ({user.start} to {end}).")
    print(f"Password: {user.password}")


if __name__ == "__main__":
    main()
