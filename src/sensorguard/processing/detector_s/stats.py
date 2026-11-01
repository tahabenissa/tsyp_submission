"""Shared linear algebra, AR whitening and CUSUM helpers.

Only numpy/scipy, deterministic, no random numbers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def fit_ar(series: pd.Series, order: int) -> tuple[np.ndarray, float]:
    """Fit AR(order) on the train series and return (coefficients, residual std).

    Coefficients are ordered so that the lag-1 coefficient is first.  For
    order=0 the coefficients are empty and the residual std is the std of the
    observed values (the constant model).  No NaN is dropped before the lag
    matrix is built: only rows where the target and every lag are finite and the
    input dates are consecutive daily values contribute to the least squares
    problem.
    """
    order = int(order)
    if order < 0:
        raise ValueError(f"AR order must be >= 0, got {order}")
    x = series.to_numpy(dtype=float)
    n = x.size
    if n < 2:
        return np.array([], dtype=float), 1.0

    # Consecutive daily dates are a requirement for a lag model.
    diffs = series.index.to_series().diff().dropna().dt.days
    if len(diffs) > 0 and bool((diffs != 1).any()):
        raise ValueError("Residual dates are not consecutive daily values")

    valid = np.isfinite(x)
    if order == 0:
        rows = np.arange(n)
        target_ok = valid
    else:
        rows = []
        for t in range(order, n):
            if valid[t] and all(valid[t - i] for i in range(1, order + 1)):
                rows.append(t)
        target_ok = np.zeros(n, dtype=bool)
        if rows:
            target_ok[rows] = True

    if order == 0:
        yy = x[target_ok]
        sigma = float(np.std(yy, ddof=1)) if yy.size > 1 else 1.0
        return np.array([], dtype=float), sigma

    rows_arr = np.asarray(rows, dtype=int)
    lag = np.arange(1, order + 1)
    X = x[rows_arr[:, None] - lag[None, :]]
    yy = x[rows_arr]

    coef, _, _, _ = np.linalg.lstsq(X, yy, rcond=None)
    resid = yy - X @ coef
    sigma = float(np.std(resid, ddof=1)) if resid.size > 1 else 1.0
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = 1.0
    return np.asarray(coef, dtype=float), sigma



def whiten(series: pd.Series, ar_coef: np.ndarray, sigma: float, order: int) -> pd.Series:
    """One-step prediction errors of the train AR model, in units of their train std.

    Dividing by ``sigma`` keeps the CUSUM slack and threshold in standard
    deviations whatever the AR order.  NaN where the prediction is undefined
    (the day itself or one of its lags is missing).  Order 0 returns the
    series divided by ``sigma``.
    """
    x = series.to_numpy(dtype=float)
    n = x.size
    out = np.full(n, np.nan, dtype=float)
    if not np.isfinite(sigma) or sigma <= 0:
        return pd.Series(out, index=series.index, name=series.name)
    if order == 0:
        out[:] = x / sigma
        return pd.Series(out, index=series.index, name=series.name)
    coef = np.asarray(ar_coef, dtype=float)
    # prediction for day t is sum_i coef[i] * x[t - 1 - i]
    pred = np.zeros(n - order, dtype=float)
    for i in range(order):
        pred += coef[i] * x[order - 1 - i : n - 1 - i]
    out[order:] = (x[order:] - pred) / sigma
    return pd.Series(out, index=series.index, name=series.name)


def cusum_up_down(whitened: np.ndarray, slack: float) -> tuple[np.ndarray, np.ndarray]:
    """Return upward and downward CUSUM arrays for a whitened zero-mean series.

    A NaN observation HOLDS the accumulators: up[t] = up[t-1] and
    down[t] = down[t-1].  The state is never reset to zero and the NaN is
    never filled or interpolated; the caller writes NaN score / flag 0 for
    NaN days and lets the held state continue into the next day.
    """
    n = whitened.size
    up = np.zeros(n, dtype=float)
    down = np.zeros(n, dtype=float)
    for t in range(n):
        if not np.isfinite(whitened[t]):
            if t > 0:
                up[t] = up[t - 1]
                down[t] = down[t - 1]
            continue
        prev_up = up[t - 1] if t > 0 else 0.0
        prev_down = down[t - 1] if t > 0 else 0.0
        # up collects positive deviations beyond the slack, down collects
        # negative ones (it stays <= 0).  Both forget at rate `slack` per day.
        up[t] = max(0.0, prev_up + whitened[t] - slack)
        down[t] = min(0.0, prev_down + whitened[t] + slack)
    return up, down


def cusum_restart(whitened: np.ndarray, slack: float, threshold: float) -> dict[str, np.ndarray]:
    """Two-sided CUSUM on several variables at once, restarted after every alarm.

    ``whitened`` has one row per day and one column per variable.  Each
    variable keeps its own up/down sums.  The day's statistic is the largest
    sum over all variables and both sides; when it crosses ``threshold`` the
    day is an alarm and every sum restarts at zero the next day (Page's
    CUSUM).  A NaN value holds that variable's sums for the day.

    Returns ``stat`` (n,), ``alarm`` (n, bool), ``up`` and ``down`` (n, v),
    where up/down are the sums BEFORE the restart, so the onset of an alarm
    can still be read from them.
    """
    w = np.asarray(whitened, dtype=float)
    if w.ndim == 1:
        w = w[:, None]
    n, v = w.shape
    up = np.zeros((n, v))
    down = np.zeros((n, v))
    stat = np.zeros(n)
    alarm = np.zeros(n, dtype=bool)
    cur_up = np.zeros(v)
    cur_down = np.zeros(v)
    for t in range(n):
        x = w[t]
        ok = np.isfinite(x)
        cur_up = np.where(ok, np.maximum(0.0, cur_up + np.where(ok, x, 0.0) - slack), cur_up)
        cur_down = np.where(ok, np.minimum(0.0, cur_down + np.where(ok, x, 0.0) + slack), cur_down)
        up[t], down[t] = cur_up, cur_down
        stat[t] = max(cur_up.max(), (-cur_down).max())
        if stat[t] > threshold:
            alarm[t] = True
            cur_up = np.zeros(v)
            cur_down = np.zeros(v)
    return {"stat": stat, "alarm": alarm, "up": up, "down": down}


def calibrate_threshold(whitened: np.ndarray, slack: float, alarms_per_year: float,
                        low: float = 0.5, high: float = 100.0, tol: float = 0.05) -> tuple[float, float]:
    """Lowest threshold whose alarm count on *whitened* (clean train days) is at most the target.

    The target is ``alarms_per_year`` times the number of years in the data.
    A higher threshold never gives more alarms, so bisection finds it.
    Returns (threshold, alarms per year actually reached on train).
    """
    n = np.asarray(whitened).shape[0]
    years = n / 365.25
    allowed = alarms_per_year * years

    def count(h: float) -> int:
        return int(cusum_restart(whitened, slack, h)["alarm"].sum())

    if count(low) <= allowed:
        high = low
    while high - low > tol:
        mid = 0.5 * (low + high)
        if count(mid) <= allowed:
            high = mid
        else:
            low = mid
    return float(high), float(count(high) / years)


def alarm_events(flags: np.ndarray) -> int:
    """Separate alarms in a flag array: a run of consecutive flagged days counts once."""
    f = np.asarray(flags, dtype=bool)
    return int(f[0] + np.sum(f[1:] & ~f[:-1])) if f.size else 0


def threshold_for_events(stat: np.ndarray, alarms_per_year: float) -> tuple[float, float]:
    """Lowest threshold h such that ``stat > h`` gives at most the target alarm events per year.

    For detectors whose flag is simply ``stat > h`` (trend).  ``stat`` is the
    statistic on the clean train days; NaN days are never flagged.  Returns
    (threshold, alarm events per year reached on train).
    """
    s = np.asarray(stat, dtype=float)
    years = s.size / 365.25
    allowed = alarms_per_year * years
    finite = np.sort(np.unique(s[np.isfinite(s)]))
    if finite.size == 0:
        return float("inf"), 0.0

    def events(h: float) -> int:
        return alarm_events(np.isfinite(s) & (s > h))

    lo, hi = 0, finite.size - 1          # events(finite[hi]) == 0 <= allowed
    while lo < hi:                        # smallest index whose threshold is allowed
        mid = (lo + hi) // 2
        if events(finite[mid]) <= allowed:
            hi = mid
        else:
            lo = mid + 1
    h = float(finite[lo])
    return h, float(events(h) / years)


def cusum_onset(up: np.ndarray, down: np.ndarray, alarm: int) -> int:
    """Estimated change day for an alarm raised at index ``alarm``.

    The classic CUSUM estimate: the day after the alarming accumulator was last
    at zero.  The side (up or down) is the one carrying the larger value at the
    alarm day.
    """
    side = up if up[alarm] >= -down[alarm] else -down
    zero = np.flatnonzero(side[: alarm + 1] <= 0.0)
    return int(zero[-1] + 1) if zero.size else 0


def cusum_stat(up: np.ndarray, down: np.ndarray) -> np.ndarray:
    return np.maximum(up, -down)

def mann_kendall(x: np.ndarray) -> tuple[float, float, float]:
    """Mann-Kendall S, variance and standardized z for an array of values.

    NaNs are removed before calculation.  Returns (S, variance, z), where z is
    the standardized Mann-Kendall statistic (0 when S == 0 or variance == 0).
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 3:
        return 0.0, 0.0, 0.0
    # S = sum over pairs i < j of sign(x[j] - x[i]), from the upper triangle.
    s = float(np.sum(np.triu(np.sign(x[None, :] - x[:, None]), k=1)))
    denominator = n * (n - 1) * (2 * n + 5)
    tie_groups = []
    unique, counts = np.unique(x, return_counts=True)
    for count in counts:
        if count > 1:
            tie_groups.append(count * (count - 1) * (2 * count + 5))
    if tie_groups:
        denominator -= float(sum(tie_groups))
    variance = denominator / 18.0 if denominator > 0 else 0.0
    if s == 0:
        z = 0.0
    elif s > 0:
        z = (s - 1.0) / np.sqrt(variance) if variance > 0 else 0.0
    else:
        z = (s + 1.0) / np.sqrt(variance) if variance > 0 else 0.0
    return float(s), float(variance), float(z)


def sen_slope(x: np.ndarray) -> float:
    """Sen's slope estimator for a 1-D vector."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return 0.0
    i, j = np.triu_indices(n, k=1)
    return float(np.median((x[j] - x[i]) / (j - i)))
