"""Personas must be deterministic, valid, and actually exhibit their intended shape.

The shape tests run the personas through the real analytics, which doubles as
an end-to-end check that analytics detects the patterns we care about.
"""

from datetime import date, timedelta

import pytest

from lumen.analytics.direction import Direction, Outlook
from lumen.analytics.metrics import period_stat
from lumen.analytics.series import DateRange, daily_means
from lumen.analytics.summary import DimensionSummary, summarize
from lumen.domain.checkin import Checkin
from lumen.domain.dimensions import CORE_DIMENSIONS, SCALE_MAX, SCALE_MIN, Dimension
from lumen.domain.observation import Observation
from lumen.synthetic.personas import BURNOUT, PERSONAS, SEASONAL_DIP, STABLE, Persona, generate

START = date(2026, 1, 5)
DAYS = 90
PERIOD = DateRange(START, START + timedelta(days=DAYS - 1))
SEEDS = range(5)


def observations(checkins: list[Checkin]) -> list[Observation]:
    return [Observation(c.local_date, d, v) for c in checkins for d, v in c.scores.items()]


def full_period_summary(obs: list[Observation], dim: Dimension) -> DimensionSummary:
    return summarize(obs, dim, end=PERIOD.end, trend_days=DAYS)


@pytest.mark.parametrize("persona", PERSONAS.values(), ids=PERSONAS)
def test_generation_is_deterministic_for_a_seed(persona: Persona) -> None:
    assert generate(persona, START, DAYS, seed=7) == generate(persona, START, DAYS, seed=7)
    assert generate(persona, START, DAYS, seed=7) != generate(persona, START, DAYS, seed=8)


@pytest.mark.parametrize("persona", PERSONAS.values(), ids=PERSONAS)
def test_checkins_are_valid_and_include_core_dimensions(persona: Persona) -> None:
    checkins = generate(persona, START, DAYS, seed=1)
    for c in checkins:
        assert START <= c.local_date < START + timedelta(days=DAYS)
        assert set(CORE_DIMENSIONS) <= set(c.scores)
        assert all(SCALE_MIN <= v <= SCALE_MAX for v in c.scores.values())


@pytest.mark.parametrize("persona", PERSONAS.values(), ids=PERSONAS)
def test_some_days_are_skipped_like_a_real_user(persona: Persona) -> None:
    n = len(generate(persona, START, DAYS, seed=1))
    assert DAYS * 0.7 < n < DAYS


@pytest.mark.parametrize("seed", SEEDS)
def test_burnout_shows_rising_stress_and_falling_energy(seed: int) -> None:
    obs = observations(generate(BURNOUT, START, DAYS, seed=seed))
    stress = full_period_summary(obs, Dimension.STRESS)
    energy = full_period_summary(obs, Dimension.ENERGY)
    assert stress.trend.direction is Direction.INCREASING
    assert stress.trend_outlook is Outlook.WORSENING
    assert energy.trend.direction is Direction.DECREASING


def test_stable_persona_rarely_shows_a_false_change_or_trend() -> None:
    # With 95% intervals, chance alone flags roughly 1 in 20 comparisons of
    # unchanging data; the practical threshold should keep it at or below that.
    summaries = [
        full_period_summary(observations(generate(STABLE, START, DAYS, seed=seed)), dim)
        for seed in SEEDS
        for dim in Dimension
    ]
    flagged = (Outlook.IMPROVING, Outlook.WORSENING)
    assert sum(s.trend_outlook in flagged for s in summaries) <= 0.1 * len(summaries)
    assert sum(s.change_outlook in flagged for s in summaries) <= 0.1 * len(summaries)


def test_stable_persona_is_mostly_confidently_flat() -> None:
    directions = [
        full_period_summary(
            observations(generate(STABLE, START, DAYS, seed=seed)), dim
        ).trend.direction
        for seed in SEEDS
        for dim in CORE_DIMENSIONS
    ]
    assert directions.count(Direction.FLAT) >= 0.8 * len(directions)


@pytest.mark.parametrize("seed", SEEDS)
def test_seasonal_dip_is_lowest_in_the_middle(seed: int) -> None:
    mood = daily_means(observations(generate(SEASONAL_DIP, START, DAYS, seed=seed)), Dimension.MOOD)
    third = DAYS // 3
    first, middle, last = (
        period_stat(
            mood,
            DateRange(
                START + timedelta(days=i * third), START + timedelta(days=(i + 1) * third - 1)
            ),
        ).mean
        for i in range(3)
    )
    assert first is not None and middle is not None and last is not None
    assert middle < first - 0.5
    assert middle < last - 0.5
