"""Building blocks for analytics: observations, date ranges, daily series."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from math import fsum

from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation

# A daily series maps each day that has data to that day's value. Days without
# data are absent, never filled in: missing data is reported, not imputed.
DailySeries = dict[date, float]


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive range of calendar days."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) is before start ({self.start})")

    @classmethod
    def ending_on(cls, end: date, days: int) -> "DateRange":
        if days < 1:
            raise ValueError("days must be at least 1")
        return cls(end - timedelta(days=days - 1), end)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "DateRange":
        """The range of equal length immediately before this one."""
        return DateRange.ending_on(self.start - timedelta(days=1), self.days)

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.start <= day <= self.end

    def __iter__(self) -> Iterator[date]:
        for offset in range(self.days):
            yield self.start + timedelta(days=offset)


def daily_means(observations: Iterable[Observation], dimension: Dimension) -> DailySeries:
    """Average each day's observations for one dimension.

    A day with several check-ins contributes a single value, so heavily
    tracked days don't outweigh lightly tracked ones in later aggregates.
    """
    by_day: defaultdict[date, list[int]] = defaultdict(list)
    for obs in observations:
        if obs.dimension is dimension:
            by_day[obs.day].append(obs.value)
    return {day: fsum(values) / len(values) for day, values in sorted(by_day.items())}


def restrict(series: DailySeries, period: DateRange) -> DailySeries:
    return {day: value for day, value in series.items() if day in period}
