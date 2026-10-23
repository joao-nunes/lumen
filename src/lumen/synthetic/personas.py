"""Synthetic personas for tests, evaluation, and development (PROJECT.MD §13).

Each persona defines, per dimension, a *latent level* that changes over the
study period, plus autocorrelated day-to-day noise and tag effects. The
latent value is rounded and clipped to the 1-5 scale, and only the
dimensions scheduled for that day are recorded, exactly as a real user's
check-ins would be.

Generation is fully deterministic for a given seed.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from lumen.domain.checkin import Checkin, CheckinMode
from lumen.domain.dimensions import SCALE_MAX, SCALE_MIN, Dimension, dimensions_for

# A level curve maps study progress t ∈ [0, 1] to a latent score.
LevelCurve = Callable[[float], float]
# Tag probability as a function of study progress and calendar day.
TagProbability = Callable[[float, date], float]

DEFAULT_TIMEZONE = ZoneInfo("Europe/Lisbon")


def constant(level: float) -> LevelCurve:
    return lambda _t: level


def linear(start: float, end: float) -> LevelCurve:
    return lambda t: start + (end - start) * t


def dip(base: float, depth: float, center: float = 0.5, width: float = 0.2) -> LevelCurve:
    """Gaussian-shaped temporary dip below `base`, deepest at `center`."""
    return lambda t: base - depth * math.exp(-(((t - center) / width) ** 2))


def fixed(p: float) -> TagProbability:
    return lambda _t, _day: p


def weekdays_only(_t: float, day: date) -> float:
    return 1.0 if day.weekday() < 5 else 0.0


@dataclass(frozen=True, slots=True)
class DimensionModel:
    level: LevelCurve
    noise_sd: float = 0.5
    # AR(1) coefficient: how much of yesterday's deviation carries into today.
    autocorrelation: float = 0.5


@dataclass(frozen=True, slots=True)
class TagModel:
    probability: TagProbability
    effects: dict[Dimension, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Persona:
    name: str
    description: str
    dimensions: dict[Dimension, DimensionModel]
    tags: dict[str, TagModel] = field(default_factory=dict)
    skip_probability: float = 0.15
    checkin_time: time = time(21, 0)


def generate(
    persona: Persona,
    start: date,
    days: int = 90,
    seed: int = 0,
    tz: ZoneInfo = DEFAULT_TIMEZONE,
) -> list[Checkin]:
    if days < 1:
        raise ValueError("days must be at least 1")
    rng = np.random.default_rng(seed)
    noise = dict.fromkeys(persona.dimensions, 0.0)
    checkins: list[Checkin] = []

    for offset in range(days):
        day = start + timedelta(days=offset)
        t = offset / (days - 1) if days > 1 else 0.0

        # Noise and tags evolve every day, even on skipped days, so skipping
        # doesn't change the underlying trajectory.
        for dim, model in persona.dimensions.items():
            innovation_sd = model.noise_sd * math.sqrt(1 - model.autocorrelation**2)
            noise[dim] = model.autocorrelation * noise[dim] + rng.normal(0.0, innovation_sd)
        tags = frozenset(
            name for name, tag in persona.tags.items() if rng.random() < tag.probability(t, day)
        )
        if rng.random() < persona.skip_probability:
            continue

        scores: dict[Dimension, int] = {}
        for dim in dimensions_for(day):
            dim_model = persona.dimensions.get(dim)
            if dim_model is None:
                continue
            latent = dim_model.level(t) + noise[dim]
            latent += sum(persona.tags[name].effects.get(dim, 0.0) for name in tags)
            scores[dim] = int(np.clip(round(latent), SCALE_MIN, SCALE_MAX))

        checkins.append(
            Checkin(
                recorded_at=datetime.combine(day, persona.checkin_time, tzinfo=tz),
                local_date=day,
                scores=scores,
                tags=tags,
                mode=CheckinMode.STRUCTURED,
            )
        )
    return checkins


BURNOUT = Persona(
    name="burnout",
    description="Gradual burnout: rising stress, falling energy and mood, workload themes.",
    dimensions={
        Dimension.MOOD: DimensionModel(linear(3.7, 2.4)),
        Dimension.ENERGY: DimensionModel(linear(3.8, 2.1)),
        Dimension.STRESS: DimensionModel(linear(2.6, 4.3)),
        Dimension.SLEEP_QUALITY: DimensionModel(linear(3.6, 2.3)),
        Dimension.MOTIVATION: DimensionModel(linear(3.8, 2.3)),
        Dimension.CONCENTRATION: DimensionModel(linear(3.7, 2.5)),
        Dimension.SOCIAL_CONNECTION: DimensionModel(linear(3.5, 2.6)),
    },
    tags={
        "workday": TagModel(weekdays_only),
        "late_work": TagModel(
            lambda t, day: (0.1 + 0.6 * t) * weekdays_only(t, day),
            {Dimension.STRESS: 0.5, Dimension.SLEEP_QUALITY: -0.4},
        ),
        "exercise": TagModel(
            lambda t, _day: 0.5 - 0.4 * t,
            {Dimension.MOOD: 0.3, Dimension.ENERGY: 0.3},
        ),
    },
)

STABLE = Persona(
    name="stable",
    description="Stable: noisy but flat metrics around a moderate level.",
    dimensions={
        Dimension.MOOD: DimensionModel(constant(3.5)),
        Dimension.ENERGY: DimensionModel(constant(3.3)),
        Dimension.STRESS: DimensionModel(constant(2.7)),
        Dimension.SLEEP_QUALITY: DimensionModel(constant(3.4)),
        Dimension.MOTIVATION: DimensionModel(constant(3.4)),
        Dimension.CONCENTRATION: DimensionModel(constant(3.5)),
        Dimension.SOCIAL_CONNECTION: DimensionModel(constant(3.6)),
    },
    tags={
        "workday": TagModel(weekdays_only),
        "exercise": TagModel(fixed(0.4), {Dimension.MOOD: 0.3, Dimension.ENERGY: 0.3}),
        "alcohol": TagModel(fixed(0.15), {Dimension.SLEEP_QUALITY: -0.6}),
        "social_time": TagModel(fixed(0.3), {Dimension.SOCIAL_CONNECTION: 0.6}),
    },
)

SEASONAL_DIP = Persona(
    name="seasonal_dip",
    description="Seasonal dip: a slow decline in mood and energy, then recovery.",
    dimensions={
        Dimension.MOOD: DimensionModel(dip(3.7, 1.4)),
        Dimension.ENERGY: DimensionModel(dip(3.6, 1.3)),
        Dimension.STRESS: DimensionModel(constant(2.8)),
        Dimension.SLEEP_QUALITY: DimensionModel(dip(3.5, 0.9)),
        Dimension.MOTIVATION: DimensionModel(dip(3.6, 1.2)),
        Dimension.CONCENTRATION: DimensionModel(constant(3.4)),
        Dimension.SOCIAL_CONNECTION: DimensionModel(dip(3.5, 0.8)),
    },
    tags={
        "workday": TagModel(weekdays_only),
        "time_outdoors": TagModel(
            lambda t, _day: 0.6 - 0.4 * math.exp(-(((t - 0.5) / 0.2) ** 2)),
            {Dimension.MOOD: 0.3},
        ),
    },
)

PERSONAS: dict[str, Persona] = {p.name: p for p in (BURNOUT, STABLE, SEASONAL_DIP)}
