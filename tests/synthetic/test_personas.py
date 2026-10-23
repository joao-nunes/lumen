"""Personas must be deterministic, valid, and actually exhibit their intended shape.

Shape tests run the personas through the real analytics, which doubles as an
end-to-end check that analytics detects the patterns we care about.
"""

from datetime import date, timedelta

from lumen.analytics.direction import Direction, Outlook
from lumen.analytics.metrics import period_stat
from lumen.analytics.series import DateRange, daily_means
from lumen.analytics.summary import DimensionSummary, summarize
from lumen.domain.checkin import Checkin
from lumen.domain.dimensions import CORE_DIMENSIONS, SCALE_MAX, SCALE_MIN, Dimension
from lumen.domain.observation import Observation
from lumen.synthetic.personas import BURNOUT, PERSONAS, SEASONAL_DIP, STABLE, generate

START = date(2026, 1, 5)
DAYS = 90
END = START + timedelta(days=DAYS - 1)
SEEDS = range(3)


def observations(checkins: list[Checkin]) -> list[Observation]:
    return [Observation(c.local_date, d, v) for c in checkins for d, v in c.scores.items()]


def full_period_summary(obs: list[Observation], dim: Dimension) -> DimensionSummary:
    return summarize(obs, dim, end=END, trend_days=DAYS)


def test_generation_is_deterministic_per_seed() -> None:
    assert generate(BURNOUT, START, DAYS, seed=7) == generate(BURNOUT, START, DAYS, seed=7)
    assert generate(BURNOUT, START, DAYS, seed=7) != generate(BURNOUT, START, DAYS, seed=8)


def test_every_persona_produces_valid_checkins_with_core_dimensions() -> None:
    for persona in PERSONAS.values():
        for c in generate(persona, START, DAYS, seed=1):
            assert set(CORE_DIMENSIONS) <= set(c.scores)
            assert all(SCALE_MIN <= v <= SCALE_MAX for v in c.scores.values())


def test_burnout_shows_rising_stress_and_falling_energy() -> None:
    for seed in SEEDS:
        obs = observations(generate(BURNOUT, START, DAYS, seed=seed))
        assert full_period_summary(obs, Dimension.STRESS).trend_outlook is Outlook.WORSENING
        assert full_period_summary(obs, Dimension.ENERGY).trend.direction is Direction.DECREASING


def test_stable_persona_is_mostly_flat_and_rarely_flagged() -> None:
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
    core = [s for s in summaries if s.dimension in CORE_DIMENSIONS]
    assert sum(s.trend.direction is Direction.FLAT for s in core) >= 0.8 * len(core)


def test_seasonal_dip_is_lowest_in_the_middle() -> None:
    third = DAYS // 3
    for seed in SEEDS:
        mood = daily_means(
            observations(generate(SEASONAL_DIP, START, DAYS, seed=seed)), Dimension.MOOD
        )
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
