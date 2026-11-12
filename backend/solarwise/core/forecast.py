"""Baseline projections of the daily performance index.

These are *reference* forecasting methods - persistence, a moving average and a
robust linear trend - of the kind any forecast must beat to be worth using.
They are **not validated**: the back-test printed with each method is computed
on the very dataset being analysed, covers a few weeks at most, and says nothing
about other seasons or other plants.  The projections are shown for orientation
only and never enter a decision; in particular they are not soiling forecasts.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel

from solarwise.core.statistics import theil_sen

VALIDATION_STATUS = "UNVALIDATED"
MIN_HISTORY_DAYS = 10
BACKTEST_HORIZON_DAYS = 7
MOVING_AVERAGE_DAYS = 7
MAX_HORIZON_DAYS = 30


class ForecastMethod(StrEnum):
    PERSISTENCE = "PERSISTENCE"
    MOVING_AVERAGE = "MOVING_AVERAGE"
    LINEAR_TREND = "LINEAR_TREND"


class ForecastPoint(BaseModel):
    day: date
    value: float


class Backtest(BaseModel):
    horizon_days: int
    samples: int
    #: Mean absolute error [% points of the performance index].
    mean_absolute_error: float
    #: Mean of (forecast - observed) [% points].
    bias: float


class MethodForecast(BaseModel):
    method: ForecastMethod
    label: str
    description: str
    points: list[ForecastPoint]
    backtest: Backtest | None
    validation_status: str = VALIDATION_STATUS


class PerformanceForecast(BaseModel):
    quantity: str = "performance_index_pct"
    evaluable: bool
    reason: str | None = None
    history_days: int
    horizon_days: int
    last_observed_day: date | None = None
    methods: list[MethodForecast]
    validation_status: str = VALIDATION_STATUS
    usable_for_decision: bool = False
    notes: list[str]


_NOTES = [
    "UNVALIDATED reference projections. They extend the recent behaviour of the performance index and know "
    "nothing about weather, cleaning, rain or repairs to come.",
    "The back-test is computed on this dataset only; it is an indication of fit, not a validation.",
    "These projections are not used by the decision engine and are not forecasts of soiling.",
]

_LABELS = {
    ForecastMethod.PERSISTENCE: ("Persistence", "The last observed value is held constant."),
    ForecastMethod.MOVING_AVERAGE: (
        f"{MOVING_AVERAGE_DAYS}-day moving average", f"The mean of the last {MOVING_AVERAGE_DAYS} observed days is held constant."
    ),
    ForecastMethod.LINEAR_TREND: (
        "Robust linear trend", "Theil-Sen line through the observed days, extended forward."
    ),
}


def _predict(method: ForecastMethod, xs: Sequence[float], ys: Sequence[float], target_x: float) -> float | None:
    if not ys:
        return None
    if method is ForecastMethod.PERSISTENCE:
        return ys[-1]
    if method is ForecastMethod.MOVING_AVERAGE:
        recent = ys[-MOVING_AVERAGE_DAYS:]
        return sum(recent) / len(recent)
    fit = theil_sen(list(xs), list(ys), min_points=MIN_HISTORY_DAYS)
    if fit is None:
        return None
    return fit.intercept + fit.slope * target_x


def _backtest(method: ForecastMethod, xs: Sequence[float], ys: Sequence[float]) -> Backtest | None:
    errors: list[float] = []
    index_of = {x: i for i, x in enumerate(xs)}
    for origin in range(MIN_HISTORY_DAYS, len(xs)):
        target = xs[origin - 1] + BACKTEST_HORIZON_DAYS
        position = index_of.get(target)
        if position is None:
            continue
        predicted = _predict(method, xs[:origin], ys[:origin], target)
        if predicted is not None:
            errors.append(predicted - ys[position])
    if len(errors) < 3:
        return None
    return Backtest(
        horizon_days=BACKTEST_HORIZON_DAYS, samples=len(errors),
        mean_absolute_error=sum(abs(e) for e in errors) / len(errors), bias=sum(errors) / len(errors),
    )


def forecast_performance_index(
    days: Sequence[date], values: Sequence[float | None], horizon_days: int = 14
) -> PerformanceForecast:
    """Project the daily performance index ``horizon_days`` ahead with each reference method.

    Days without a value are skipped; nothing is interpolated.
    """
    if len(days) != len(values):
        raise ValueError("days and values differ in length")
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"the horizon must lie between 1 and {MAX_HORIZON_DAYS} days")
    observed = [(d, v) for d, v in zip(days, values, strict=True) if v is not None]
    if len(observed) < MIN_HISTORY_DAYS:
        return PerformanceForecast(
            evaluable=False, history_days=len(observed), horizon_days=horizon_days, methods=[], notes=_NOTES,
            reason=f"At least {MIN_HISTORY_DAYS} days with a performance index are needed; {len(observed)} available.",
        )
    origin = observed[0][0]
    xs = [float((d - origin).days) for d, _ in observed]
    ys = [float(v) for _, v in observed]
    last_day = observed[-1][0]
    methods: list[MethodForecast] = []
    for method in ForecastMethod:
        points: list[ForecastPoint] = []
        for step in range(1, horizon_days + 1):
            day = last_day + timedelta(days=step)
            predicted = _predict(method, xs, ys, float((day - origin).days))
            if predicted is None:
                points = []
                break
            points.append(ForecastPoint(day=day, value=max(0.0, predicted)))
        if not points:
            continue
        label, description = _LABELS[method]
        methods.append(
            MethodForecast(method=method, label=label, description=description, points=points,
                           backtest=_backtest(method, xs, ys))
        )
    return PerformanceForecast(
        evaluable=bool(methods), history_days=len(observed), horizon_days=horizon_days, last_observed_day=last_day,
        methods=methods, notes=_NOTES,
    )
