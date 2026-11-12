"""Robust statistics used by the diagnostic and predictive engines.

All estimators are non-parametric and resistant to outliers, which matters for
plant telemetry.  Where an interval is returned it follows from the stated
method - no confidence figure is produced without a mathematical basis.

References
----------
* Sen, P. K. (1968). Estimates of the regression coefficient based on
  Kendall's tau. *J. Am. Stat. Assoc.* 63, 1379-1389.
* Iglewicz, B. & Hoaglin, D. (1993). *How to Detect and Handle Outliers*.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

#: Consistency constant: 1.4826 * MAD estimates sigma for normal data.
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class TheilSenResult:
    slope: float
    intercept: float
    slope_low: float
    slope_high: float
    confidence_level: float
    n_points: int
    n_slopes: int

    @property
    def slope_is_negative(self) -> bool:
        """True when the whole confidence interval lies below zero."""
        return self.slope_high < 0.0

    @property
    def slope_is_positive(self) -> bool:
        return self.slope_low > 0.0


def theil_sen(
    x: Sequence[float], y: Sequence[float], confidence_level: float = 0.95, min_points: int = 8
) -> TheilSenResult | None:
    """Theil-Sen slope with Sen's distribution-free confidence interval.

    Pairs containing a non-finite value are dropped.  Returns ``None`` when
    fewer than ``min_points`` valid pairs remain or when all ``x`` are equal.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence level must be within (0, 1)")
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    n = int(xa.size)
    if n < max(3, min_points):
        return None

    i, j = np.triu_indices(n, k=1)
    dx = xa[j] - xa[i]
    valid = dx != 0
    if not np.any(valid):
        return None
    slopes = np.sort((ya[j][valid] - ya[i][valid]) / dx[valid])
    n_slopes = int(slopes.size)
    slope = float(np.median(slopes))
    intercept = float(np.median(ya - slope * xa))

    # Variance of Kendall's S statistic (no tie correction), Sen (1968).
    sigma = math.sqrt(n * (n - 1) * (2 * n + 5) / 18.0)
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    idx_low = max(round((n_slopes - z * sigma) / 2.0) - 1, 0)
    idx_high = min(round((n_slopes + z * sigma) / 2.0), n_slopes - 1)
    return TheilSenResult(
        slope=slope,
        intercept=intercept,
        slope_low=float(slopes[idx_low]),
        slope_high=float(slopes[idx_high]),
        confidence_level=confidence_level,
        n_points=n,
        n_slopes=n_slopes,
    )


def median_abs_deviation(values: Sequence[float]) -> float | None:
    """Median absolute deviation of the finite entries (``None`` if there are none)."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.median(np.abs(arr - np.median(arr))))


def modified_z_scores(values: Sequence[float]) -> list[float | None]:
    """Iglewicz-Hoaglin modified z-scores; ``None`` for non-finite inputs.

    ``M_i = 0.6745 * (x_i - median) / MAD``.  When the MAD is zero the mean
    absolute deviation is used instead (``M_i = (x_i - median) / (1.253314 * MeanAD)``).
    If the data have no spread at all, every score is zero.
    """
    arr = np.asarray(values, dtype=float)
    finite = np.isfinite(arr)
    if not np.any(finite):
        return [None] * len(values)
    data = arr[finite]
    med = float(np.median(data))
    mad = float(np.median(np.abs(data - med)))
    if mad > 0:
        scale = mad / 0.6745
    else:
        mean_ad = float(np.mean(np.abs(data - med)))
        scale = 1.253314 * mean_ad
    out: list[float | None] = []
    for value, ok in zip(arr, finite, strict=True):
        if not ok:
            out.append(None)
        elif scale <= 0:
            out.append(0.0)
        else:
            out.append(float((value - med) / scale))
    return out


def robust_noise_sigma(values: Sequence[float] | np.ndarray) -> float | None:
    """Robust estimate of point-to-point noise from first differences.

    ``sigma ~= 1.4826 * MAD(diff) / sqrt(2)``.  Insensitive to slow trends and
    to a single level shift.  Only differences between *adjacent* finite
    samples are used.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size < 3:
        return None
    diffs = np.diff(arr)
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size < 2:
        return None
    mad = float(np.median(np.abs(diffs - np.median(diffs))))
    return MAD_TO_SIGMA * mad / math.sqrt(2.0)


@dataclass(frozen=True)
class StepChange:
    index: int            # first sample of the new level
    before: float         # median level before the change
    after: float          # median level after the change
    drop: float           # before - after (positive for a loss of performance)
    noise_sigma: float | None


def detect_largest_drop(
    values: Sequence[float], window: int = 5, min_valid: int = 3
) -> StepChange | None:
    """Largest downward level shift between adjacent windows of ``window`` samples.

    The function only *locates and sizes* the largest drop; deciding whether it
    is material is left to the caller, who knows the engineering thresholds.
    """
    if window < 2:
        raise ValueError("window must be at least 2")
    arr = np.asarray(values, dtype=float)
    n = int(arr.size)
    noise = robust_noise_sigma(arr)
    # (boundary, median before, median after, median drop, mean drop)
    candidates: list[tuple[int, float, float, float, float]] = []
    for b in range(window, n - window + 1):
        before = arr[b - window : b]
        after = arr[b : b + window]
        before = before[np.isfinite(before)]
        after = after[np.isfinite(after)]
        if before.size < min_valid or after.size < min_valid:
            continue
        level_before = float(np.median(before))
        level_after = float(np.median(after))
        candidates.append(
            (b, level_before, level_after, level_before - level_after, float(np.mean(before) - np.mean(after)))
        )
    if not candidates:
        return None
    largest = max(c[3] for c in candidates)
    # The median drop is equally large for every boundary within half a window of the true
    # change (a median flips once most of its window has moved to the new level).  Among those
    # near-ties, the boundary with the largest difference of *means* is the change point itself.
    if largest > 0:
        near = [c for c in candidates if c[3] >= 0.8 * largest]
        b, level_before, level_after, drop, _ = max(near, key=lambda c: (c[4], -c[0]))
    else:
        b, level_before, level_after, drop, _ = max(candidates, key=lambda c: c[3])
    return StepChange(index=b, before=level_before, after=level_after, drop=drop, noise_sigma=noise)


def finite_median(values: Sequence[float | None]) -> float | None:
    data = [v for v in values if v is not None and math.isfinite(v)]
    if not data:
        return None
    return float(np.median(np.asarray(data, dtype=float)))
