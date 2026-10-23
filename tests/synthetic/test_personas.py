"""Personas must be deterministic, valid, and actually exhibit their intended shape.

The shape tests run the personas through the real analytics, which doubles as
an end-to-end check that analytics detects the patterns we care about.
"""

from datetime import date, timedelta

import pytest

from lumen.analytics.metrics import period_stat
from lumen.analytics.series import DateRange, daily_means
from lumen.analytics.summary import summarize
from lumen.analytics.trends import Outlook, TrendDirection
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
    stress = summarize(obs, Dimension.STRESS, PERIOD)
    energy = summarize(obs, Dimension.ENERGY, PERIOD)
    assert stress.trend.direction is TrendDirection.INCREASING
    assert stress.outlook is Outlook.WORSENING
    assert energy.trend.direction is TrendDirection.DECREASING


@pytest.mark.parametrize("seed", SEEDS)
def test_stable_persona_has_flat_core_trends(seed: int) -> None:
    obs = observations(generate(STABLE, START, DAYS, seed=seed))
    for dim in CORE_DIMENSIONS:
        assert summarize(obs, dim, PERIOD).trend.direction is TrendDirection.FLAT


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
