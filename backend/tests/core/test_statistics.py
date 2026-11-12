"""Robust statistics used for trends and anomalies."""

from __future__ import annotations

import math

import pytest

from solarwise.core.statistics import (
    detect_largest_drop,
    finite_median,
    median_abs_deviation,
    modified_z_scores,
    robust_noise_sigma,
    theil_sen,
)


def test_theil_sen_recovers_a_known_slope() -> None:
    x = [float(i) for i in range(30)]
    y = [100.0 - 0.15 * i for i in x]
    result = theil_sen(x, y)
    assert result is not None
    assert result.slope == pytest.approx(-0.15)
    assert result.intercept == pytest.approx(100.0)
    assert result.slope_low <= result.slope <= result.slope_high


def test_theil_sen_is_robust_to_outliers() -> None:
    x = [float(i) for i in range(30)]
    y = [100.0 - 0.15 * i for i in x]
    y[5], y[17] = 20.0, 180.0
    result = theil_sen(x, y)
    assert result is not None
    assert result.slope == pytest.approx(-0.15, abs=0.02)


def test_theil_sen_needs_enough_points_and_ignores_non_finite() -> None:
    assert theil_sen([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]) is None
    x = [float(i) for i in range(12)]
    y = [2.0 * i for i in x]
    y[3] = math.nan
    result = theil_sen(x, y)
    assert result is not None
    assert result.n_points == 11
    assert result.slope == pytest.approx(2.0)


def test_theil_sen_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        theil_sen([0.0, 1.0], [1.0])


def test_median_abs_deviation() -> None:
    assert median_abs_deviation([1.0, 2.0, 3.0, 4.0, 100.0]) == pytest.approx(1.0)
    assert median_abs_deviation([]) is None


def test_modified_z_scores_flag_the_outlier_only() -> None:
    values = [10.0, 10.2, 9.9, 10.1, 9.8, 10.0, 25.0]
    scores = modified_z_scores(values)
    assert scores[-1] is not None and abs(scores[-1]) > 3.5
    assert all(s is not None and abs(s) < 3.5 for s in scores[:-1])


def test_modified_z_scores_of_a_constant_series_are_zero() -> None:
    assert modified_z_scores([5.0, 5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0, 0.0]


def test_modified_z_scores_keep_missing_values_missing() -> None:
    scores = modified_z_scores([10.0, math.nan, 10.5, 9.5, 10.2])
    assert scores[1] is None
    assert all(s is not None for i, s in enumerate(scores) if i != 1)


def test_noise_estimate_ignores_a_slow_trend() -> None:
    trend = [100.0 - 0.2 * i for i in range(40)]
    sigma = robust_noise_sigma(trend)
    assert sigma is not None and sigma < 1e-9


def test_largest_drop_is_located() -> None:
    values = [100.0] * 15 + [90.0] * 15
    step = detect_largest_drop(values)
    assert step is not None
    assert step.index == 15
    assert step.drop == pytest.approx(10.0)
    assert step.before == pytest.approx(100.0)
    assert step.after == pytest.approx(90.0)


def test_largest_drop_is_located_in_noisy_data() -> None:
    noise = [0.4, -0.3, 0.1, -0.5, 0.2, 0.3, -0.2, 0.0, -0.1, 0.5]
    values = [100.0 + noise[i % 10] for i in range(22)] + [92.0 + noise[i % 10] for i in range(18)]
    step = detect_largest_drop(values)
    assert step is not None
    assert step.index == 22
    assert step.drop == pytest.approx(8.0, abs=0.6)


def test_no_drop_in_a_flat_series() -> None:
    step = detect_largest_drop([100.0] * 30)
    assert step is None or step.drop == pytest.approx(0.0)


def test_finite_median_skips_missing() -> None:
    assert finite_median([1.0, None, 3.0, math.nan]) == pytest.approx(2.0)
    assert finite_median([None, math.nan]) is None
