"""Remove the slow year-to-year shift from the residuals before the detectors see them.

Why: on clean data the station-to-reference offset moves by 0.2 to 0.7 standard
deviations from one year to the next (sensor ageing, maintenance, a changed
reference product, real differences between years).  The calibration is fitted
once on the train years, so in a later year the residual sits a little off
zero for months.  A CUSUM adds that offset up day after day and ends up
alarming on clean data.

What: for each day t, the baseline is the median of the residual over the
``window_days`` days that END ``gap_days`` before t:

    baseline[t] = median( x[t - gap - window + 1] ... x[t - gap] )
    corrected[t] = x[t] - baseline[t]

* Only past days are used, so this runs in real time.
* The gap keeps a new attack out of its own baseline: during the first
  ``gap_days`` of a step the baseline still holds only clean days.
* The median (not the mean) barely moves when a few days inside the window are
  extreme or attacked.

What it costs: an attacker who drifts more slowly than the baseline adapts is
partly absorbed.  With a 180-day window and a 60-day gap, the official drifts
(ramp of 30 to 90 days) are much faster than that.  The slowest drift that is
still caught belongs in the evasion section of the report.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    b = cfg.get("baseline", {}) or {}
    window = int(b.get("window_days", 180))
    return {
        "enabled": bool(b.get("enabled", False)),
        "window_days": window,
        "gap_days": int(b.get("gap_days", 60)),
        "min_days": int(b.get("min_days", window // 2)),
    }


def rolling_baseline(x: pd.Series, window_days: int, gap_days: int, min_days: int) -> pd.Series:
    """Median of the window ending gap_days before each day; NaN until min_days are available."""
    med = x.rolling(window_days, min_periods=min_days).median()
    return med.shift(gap_days)


def remove_baseline(frame: pd.DataFrame, columns: list[str], cfg: dict[str, Any]) -> pd.DataFrame:
    """Return a copy of *frame* with the baseline subtracted from *columns*.

    *frame* must hold the whole history in date order (train then scoring
    period), so the scoring period starts with a full window.  Days before the
    first full baseline become NaN, and the detectors treat them as not
    observable.  Columns not listed (the station values the replay matcher
    reads) are left untouched.
    """
    s = settings(cfg)
    out = frame.copy()
    if not s["enabled"]:
        return out
    for col in columns:
        out[col] = frame[col] - rolling_baseline(frame[col].astype(float), s["window_days"], s["gap_days"], s["min_days"])
    return out
