"""The overview endpoint (spec 002 §2.3): lumen.analytics results, reshaped for JSON.

Nothing is computed here (PROJECT.MD §2.2); every number travels with the
number of data points it is based on.
"""

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from lumen.analytics.direction import Direction, Outlook
from lumen.analytics.metrics import PeriodStat
from lumen.analytics.overview import DimensionOverview, overview, overview_start
from lumen.analytics.series import DateRange
from lumen.api.dependencies import CurrentUser, UserDb
from lumen.db.repository import list_observations
from lumen.domain.dimensions import Dimension

router = APIRouter(prefix="/api")


class PeriodOut(BaseModel):
    start: date
    end: date
    mean: float | None
    n: int


class ChangeOut(BaseModel):
    current: PeriodOut
    previous: PeriodOut
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    direction: Direction
    outlook: Outlook


class TrendOut(BaseModel):
    start: date
    end: date
    slope_per_week: float | None
    ci_low: float | None
    ci_high: float | None
    direction: Direction
    outlook: Outlook
    n: int
    n_effective: float | None


class DailyPoint(BaseModel):
    date: date
    mean: float


class RollingPoint(BaseModel):
    date: date
    mean: float
    n: int


class DimensionOverviewOut(BaseModel):
    dimension: Dimension
    change: ChangeOut
    trend: TrendOut
    daily: list[DailyPoint]
    rolling_7: list[RollingPoint]


class OverviewOut(BaseModel):
    end: date
    dimensions: list[DimensionOverviewOut]


def _period(period: DateRange, stat: PeriodStat) -> PeriodOut:
    return PeriodOut(start=period.start, end=period.end, mean=stat.mean, n=stat.n)


def _dimension(dimension: Dimension, o: DimensionOverview) -> DimensionOverviewOut:
    s = o.summary
    return DimensionOverviewOut(
        dimension=dimension,
        change=ChangeOut(
            current=_period(s.change_period, s.change.current),
            previous=_period(s.change_period.previous(), s.change.previous),
            delta=s.change.delta,
            ci_low=s.change.ci_low,
            ci_high=s.change.ci_high,
            direction=s.change.direction,
            outlook=s.change_outlook,
        ),
        trend=TrendOut(
            start=s.trend_period.start,
            end=s.trend_period.end,
            slope_per_week=s.trend.slope_per_week,
            ci_low=s.trend.ci_low_per_week,
            ci_high=s.trend.ci_high_per_week,
            direction=s.trend.direction,
            outlook=s.trend_outlook,
            n=s.trend.n,
            n_effective=s.trend.n_effective,
        ),
        daily=[DailyPoint(date=day, mean=mean) for day, mean in o.daily.items()],
        # Days without a rolling mean are left out; the chart shows them as gaps.
        rolling_7=[
            RollingPoint(date=day, mean=stat.mean, n=stat.n)
            for day, stat in o.rolling.items()
            if stat.mean is not None
        ],
    )


@router.get("/overview")
def read_overview(end: date, user: CurrentUser, db: UserDb) -> OverviewOut:
    observations = list_observations(db, user.user_id, overview_start(end), end)
    return OverviewOut(
        end=end,
        dimensions=[_dimension(d, o) for d, o in overview(observations, end).items()],
    )
