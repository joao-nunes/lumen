"""Acceptance criteria AC-1 to AC-8 of spec 002 (docs/specs/002-checkin-vertical-slice.md)."""

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from lumen.analytics.metrics import PeriodStat, rolling_mean
from lumen.analytics.series import DateRange, daily_means, restrict
from lumen.analytics.summary import summarize_all
from lumen.db.repository import save_checkin
from lumen.domain.dimensions import DIMENSIONS, dimensions_for
from lumen.domain.observation import Observation
from lumen.synthetic.personas import PERSONAS, generate
from tests.api.client import NewClient, csrf, error_code, register
from tests.api.conftest import FakeClock

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
TODAY = NOW.date()


@pytest.fixture
def user(new_client: NewClient, clock: FakeClock) -> TestClient:
    clock.now = NOW
    client = new_client()
    register(client)
    return client


def save(
    client: TestClient, day: date, scores: dict[str, Any], tags: Iterable[str] = ()
) -> httpx2.Response:
    return client.put(
        f"/api/checkins/{day}", json={"scores": scores, "tags": list(tags)}, headers=csrf(client)
    )


def overview(client: TestClient, end: date = TODAY) -> dict[str, dict[str, Any]]:
    response = client.get("/api/overview", params={"end": str(end)})
    assert response.status_code == 200
    body = response.json()
    assert body["end"] == str(end)
    return {d["dimension"]: d for d in body["dimensions"]}


CORE = {"mood": 3, "energy": 3, "stress": 3}


# --- check-ins ----------------------------------------------------------------------


def test_ac1_a_saved_checkin_reads_back_normalized(user: TestClient) -> None:
    response = save(
        user, TODAY, {"mood": 4, "energy": 3, "stress": 2, "sleep_quality": 5},
        ["Time outdoors", "exercise"],
    )  # fmt: skip

    expected = {
        "local_date": "2026-10-31",
        "prompted": [d.value for d in dimensions_for(TODAY)],
        "checkin": {
            "scores": {"mood": 4, "energy": 3, "stress": 2, "sleep_quality": 5},
            "tags": ["exercise", "time_outdoors"],
            "recorded_at": "2026-10-31T12:00:00Z",
        },
    }
    assert (response.status_code, response.json()) == (200, expected)
    assert user.get(f"/api/checkins/{TODAY}").json() == expected


def test_ac2_saving_a_day_again_replaces_its_checkin(user: TestClient) -> None:
    save(user, TODAY, {"mood": 4, "energy": 3, "stress": 2, "sleep_quality": 5}, ["exercise"])
    response = save(user, TODAY, {"mood": 2, "energy": 2, "stress": 4})

    assert response.status_code == 200
    # Read back: the PUT response alone would not show what was stored.
    assert user.get(f"/api/checkins/{TODAY}").json()["checkin"] == {
        "scores": {"mood": 2, "energy": 2, "stress": 4},
        "tags": [],
        "recorded_at": "2026-10-31T12:00:00Z",
    }
    mood = overview(user)["mood"]
    assert mood["daily"] == [{"date": "2026-10-31", "mean": 2.0}]
    assert mood["change"]["current"]["n"] == 1


@pytest.mark.parametrize(
    ("scores", "tags", "code"),
    [
        ({"mood": 3, "energy": 3}, [], "missing_core_dimension"),
        ({**CORE, "mood": 6}, [], "invalid_score"),
        ({**CORE, "happiness": 3}, [], "unknown_dimension"),
        (CORE, ["!!"], "invalid_tag"),
        (CORE, [f"tag_{i}" for i in range(21)], "too_many_tags"),
    ],
)
def test_ac3_invalid_checkins_are_rejected_and_nothing_is_stored(
    user: TestClient, scores: dict[str, int], tags: list[str], code: str
) -> None:
    assert error_code(save(user, TODAY, scores, tags)) == (422, code)
    assert user.get(f"/api/checkins/{TODAY}").json()["checkin"] is None


def test_ac4_only_dates_inside_the_backfill_window_can_be_saved(user: TestClient) -> None:
    for day in (date(2026, 11, 1), date(2026, 10, 23)):
        assert save(user, day, CORE).status_code == 200, day
    for day in (date(2026, 11, 2), date(2026, 10, 22)):
        assert error_code(save(user, day, CORE)) == (422, "date_out_of_range"), day


def test_ac5_tags_are_listed_by_how_often_they_are_used(user: TestClient) -> None:
    for offset, tags in enumerate(
        [["exercise"], ["exercise", "alcohol"], ["alcohol", "exercise", "workday"]]
    ):
        save(user, TODAY - timedelta(days=offset), CORE, tags)

    assert user.get("/api/tags").json() == [
        {"name": "exercise", "count": 3},
        {"name": "alcohol", "count": 2},
        {"name": "workday", "count": 1},
    ]


# --- overview -----------------------------------------------------------------------


def _period(period: DateRange, stat: PeriodStat) -> dict[str, Any]:
    return {"start": str(period.start), "end": str(period.end), "mean": stat.mean, "n": stat.n}


def expected_overview(observations: Sequence[Observation], end: date) -> dict[str, Any]:
    """The overview computed directly with lumen.analytics: the API must add nothing."""
    summaries = summarize_all(observations, end)
    result: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        s = summaries[dimension]
        series = daily_means(observations, dimension)
        rolling = rolling_mean(series, s.trend_period)
        result[dimension.value] = {
            "dimension": dimension.value,
            "change": {
                "current": _period(s.change_period, s.change.current),
                "previous": _period(s.change_period.previous(), s.change.previous),
                "delta": s.change.delta,
                "ci_low": s.change.ci_low,
                "ci_high": s.change.ci_high,
                "direction": s.change.direction.value,
                "outlook": s.change_outlook.value,
            },
            "trend": {
                "start": str(s.trend_period.start),
                "end": str(s.trend_period.end),
                "slope_per_week": s.trend.slope_per_week,
                "ci_low": s.trend.ci_low_per_week,
                "ci_high": s.trend.ci_high_per_week,
                "direction": s.trend.direction.value,
                "outlook": s.trend_outlook.value,
                "n": s.trend.n,
                "n_effective": s.trend.n_effective,
            },
            "daily": [
                {"date": str(day), "mean": mean}
                for day, mean in restrict(series, s.trend_period).items()
            ],
            "rolling_7": [
                {"date": str(day), "mean": stat.mean, "n": stat.n}
                for day, stat in rolling.items()
                if stat.mean is not None
            ],
        }
    return result


def test_ac6_overview_is_exactly_what_analytics_computes(
    user: TestClient, clean_db: Engine
) -> None:
    user_id = uuid.UUID(user.get("/api/auth/me").json()["user_id"])
    checkins = generate(PERSONAS["burnout"], TODAY - timedelta(days=111), days=112, seed=42)
    with Session(clean_db) as owner, owner.begin():
        for checkin in checkins:
            save_checkin(owner, user_id, checkin)
    observations = [
        Observation(c.local_date, dimension, value)
        for c in checkins
        for dimension, value in c.scores.items()
    ]

    actual = overview(user)
    assert list(actual) == [d.value for d in DIMENSIONS]
    assert actual == expected_overview(observations, TODAY)
    # Spot-check that polarity flows through: rising stress is "worsening".
    stress_trend = actual["stress"]["trend"]
    assert (stress_trend["direction"], stress_trend["outlook"]) == ("increasing", "worsening")


def test_ac7_a_new_user_gets_an_empty_overview(user: TestClient) -> None:
    for dimension in overview(user).values():
        assert (dimension["change"]["direction"], dimension["change"]["outlook"]) == (
            "insufficient_data",
            "unknown",
        )
        assert (dimension["trend"]["direction"], dimension["trend"]["outlook"]) == (
            "insufficient_data",
            "unknown",
        )
        assert dimension["change"]["current"]["n"] == dimension["trend"]["n"] == 0
        assert dimension["daily"] == dimension["rolling_7"] == []


# --- isolation ----------------------------------------------------------------------


def test_ac8_each_user_sees_only_their_own_data(user: TestClient, new_client: NewClient) -> None:
    other = new_client()
    register(other, "other@example.com")
    save(user, TODAY, {"mood": 5, "energy": 5, "stress": 1}, ["exercise"])
    save(other, TODAY, {"mood": 1, "energy": 1, "stress": 5}, ["alcohol"])

    assert other.get(f"/api/checkins/{TODAY}").json()["checkin"]["scores"] == {
        "mood": 1,
        "energy": 1,
        "stress": 5,
    }
    assert other.get("/api/tags").json() == [{"name": "alcohol", "count": 1}]
    assert overview(other)["mood"]["daily"] == [{"date": "2026-10-31", "mean": 1.0}]
    assert user.get(f"/api/checkins/{TODAY}").json()["checkin"]["scores"] == {
        "mood": 5,
        "energy": 5,
        "stress": 1,
    }
