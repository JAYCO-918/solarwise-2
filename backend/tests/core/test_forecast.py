"""Reference projections: simple, transparent, and never presented as validated."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from solarwise.core.forecast import (
    MIN_HISTORY_DAYS,
    VALIDATION_STATUS,
    ForecastMethod,
    forecast_performance_index,
)

START = date(2026, 5, 1)


def days(count: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(count)]


def by_method(values: list[float | None], horizon: int = 5) -> dict[ForecastMethod, list[float]]:
    forecast = forecast_performance_index(days(len(values)), values, horizon)
    return {m.method: [p.value for p in m.points] for m in forecast.methods}


def test_a_flat_series_is_projected_flat_by_every_method() -> None:
    projections = by_method([95.0] * 20)
    assert set(projections) == set(ForecastMethod)
    for values in projections.values():
        assert values == [pytest.approx(95.0)] * 5


def test_a_linear_decline_is_continued_only_by_the_trend_method() -> None:
    series: list[float | None] = [100.0 - 0.5 * i for i in range(20)]  # last value 90.5
    projections = by_method(series, horizon=4)
    assert projections[ForecastMethod.PERSISTENCE] == [pytest.approx(90.5)] * 4
    assert projections[ForecastMethod.MOVING_AVERAGE] == [pytest.approx(92.0)] * 4  # mean of the last seven
    assert projections[ForecastMethod.LINEAR_TREND] == [pytest.approx(90.0 - 0.5 * i) for i in range(4)]


def test_projection_dates_follow_the_last_observed_day() -> None:
    forecast = forecast_performance_index(days(15), [96.0] * 15, 3)
    assert forecast.last_observed_day == START + timedelta(days=14)
    assert [p.day for p in forecast.methods[0].points] == [START + timedelta(days=d) for d in (15, 16, 17)]


@pytest.mark.safety
def test_missing_days_are_skipped_not_filled() -> None:
    series: list[float | None] = [100.0 - 0.5 * i for i in range(20)]
    for gap in (5, 6, 7, 12):
        series[gap] = None
    forecast = forecast_performance_index(days(20), series, 2)
    assert forecast.history_days == 16
    trend = next(m for m in forecast.methods if m.method is ForecastMethod.LINEAR_TREND)
    # The line is fitted on the true day numbers, so the gaps do not bend it.
    assert [p.value for p in trend.points] == [pytest.approx(90.0), pytest.approx(89.5)]


def test_too_little_history_gives_no_projection_and_says_why() -> None:
    forecast = forecast_performance_index(days(MIN_HISTORY_DAYS - 1), [95.0] * (MIN_HISTORY_DAYS - 1), 5)
    assert forecast.evaluable is False and forecast.methods == []
    assert forecast.reason is not None and str(MIN_HISTORY_DAYS) in forecast.reason
    mostly_missing: list[float | None] = [95.0 if i % 3 == 0 else None for i in range(21)]
    assert forecast_performance_index(days(21), mostly_missing, 5).evaluable is False


def test_backtest_reports_the_error_of_each_method_on_the_same_data() -> None:
    series: list[float | None] = [100.0 - 0.5 * i for i in range(30)]
    forecast = forecast_performance_index(days(30), series, 7)
    backtests = {m.method: m.backtest for m in forecast.methods}
    trend, persistence = backtests[ForecastMethod.LINEAR_TREND], backtests[ForecastMethod.PERSISTENCE]
    assert trend is not None and persistence is not None
    assert trend.mean_absolute_error == pytest.approx(0.0, abs=1e-9)
    assert persistence.mean_absolute_error == pytest.approx(3.5) and persistence.bias == pytest.approx(3.5)
    assert persistence.horizon_days == 7 and persistence.samples == 14


def test_projection_never_goes_below_zero() -> None:
    series: list[float | None] = [20.0 - 2.0 * i for i in range(10)]
    trend = by_method(series, horizon=5)[ForecastMethod.LINEAR_TREND]
    assert trend == [pytest.approx(0.0)] * 5


@pytest.mark.safety
def test_every_projection_is_labelled_unvalidated_and_unusable_for_decisions() -> None:
    for values in ([95.0] * 30, [95.0] * 3):
        forecast = forecast_performance_index(days(len(values)), list(values), 14)
        assert forecast.validation_status == VALIDATION_STATUS == "UNVALIDATED"
        assert forecast.usable_for_decision is False
        assert any("UNVALIDATED" in note for note in forecast.notes)
        assert any("not forecasts of soiling" in note for note in forecast.notes)
        assert all(m.validation_status == "UNVALIDATED" for m in forecast.methods)


@pytest.mark.parametrize("horizon", [0, -1, 31])
def test_horizon_is_bounded(horizon: int) -> None:
    with pytest.raises(ValueError, match="horizon"):
        forecast_performance_index(days(20), [95.0] * 20, horizon)


def test_mismatched_inputs_are_refused() -> None:
    with pytest.raises(ValueError, match="differ in length"):
        forecast_performance_index(days(20), [95.0] * 19, 5)
