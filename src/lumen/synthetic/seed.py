"""Seed a database with a synthetic persona.

Usage:
    uv run python -m lumen.synthetic.seed burnout --days 90 --seed 42
"""

import argparse
from datetime import date, timedelta

from lumen.db.repository import create_user, save_checkin
from lumen.db.session import make_engine, make_session_factory
from lumen.synthetic.personas import PERSONAS, generate


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
    start = end - timedelta(days=args.days - 1)
    checkins = generate(PERSONAS[args.persona], start, args.days, args.seed)

    session_factory = make_session_factory(make_engine())
    with session_factory.begin() as session:
        user_id = create_user(session)
        for checkin in checkins:
            save_checkin(session, user_id, checkin)

    print(f"Created user {user_id} with {len(checkins)} check-ins ({start} to {end}).")


if __name__ == "__main__":
    main()
