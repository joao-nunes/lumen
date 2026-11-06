"""A seeded persona is a real account: it can log in and see its data (`make dev` with charts)."""

from datetime import date

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from lumen.synthetic.seed import seed_persona
from tests.api.client import NewClient, login

END = date(2026, 10, 23)


def test_a_seeded_user_can_log_in_and_read_their_checkins(
    new_client: NewClient, clean_db: Engine
) -> None:
    with Session(clean_db) as db, db.begin():
        seeded = seed_persona(db, "burnout", days=3, seed=42, end=END)

    assert seeded.checkins == 3
    client = new_client()
    assert login(client, seeded.email, seeded.password).status_code == 204
    assert client.get("/api/auth/me").json()["email"] == seeded.email
    day = client.get(f"/api/checkins/{END.isoformat()}").json()
    assert day["checkin"] is not None
