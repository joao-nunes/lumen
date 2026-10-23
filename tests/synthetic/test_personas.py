"""End-to-end analytics on realistic data (rounded scores, rotating dimensions,
skipped days, tag effects): real declines must be detected, and unchanging data
must rarely be flagged.
"""

from datetime import date, timedelta

from lumen.analytics.direction import Direction, Outlook
from lumen.analytics.summary import DimensionSummary, summarize
from lumen.domain.checkin import Checkin
from lumen.domain.dimensions import CORE_DIMENSIONS, Dimension
from lumen.domain.observation import Observation
from lumen.synthetic.personas import BURNOUT, STABLE, generate

START = date(2026, 1, 5)
DAYS = 90
END = START + timedelta(days=DAYS - 1)
SEEDS = range(3)


def observations(checkins: list[Checkin]) -> list[Observation]:
    return [Observation(c.local_date, d, v) for c in checkins for d, v in c.scores.items()]


def full_period_summary(obs: list[Observation], dim: Dimension) -> DimensionSummary:
    return summarize(obs, dim, end=END, trend_days=DAYS)


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
