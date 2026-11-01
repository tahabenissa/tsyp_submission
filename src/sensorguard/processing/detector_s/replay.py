"""Replay detector: finds a block of days that copies an earlier block of the station's own values.

A replay attack resends real readings from an earlier period.  It is invisible
in a single day's values (they are genuine weather), and it does not repeat in
the residual space either, because the reference for the replayed days has
moved on.  What it does leave is an exact (or near-exact) copy of the station's
own earlier values.  Natural weather never repeats the same multi-variable
pattern for a whole week.

For every window of ``block_days`` days ending on day t, the detector computes
the smallest distance to any earlier window (lag 1 to ``max_lag_days``):

    distance = mean over days and variables of |x[t-k] - x[t-k-lag]| / train std

A day's score is the smallest distance over all windows that contain it.  A day
is flagged when that score is below ``tolerance`` (a value in standard
deviations).  A lag shorter than the block also catches a frozen sensor that
repeats one value.

Earlier windows include the last ``max_lag_days`` of the train period, so a
replay at the start of the scored period still finds its source.  Low score =
suspicious (it is a distance, not an anomaly score).  A day with a missing
value gets score NaN and flag 0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sensorguard.processing.detector_s.base import Detector, monitored_variables

__all__ = ["ReplayDetector"]


def _rolling_mean_strict(x: np.ndarray, window: int) -> np.ndarray:
    """Mean of x[t-window+1 .. t] for each t; NaN if any value in the window is NaN."""
    n = x.size
    out = np.full(n, np.nan)
    if n < window:
        return out
    finite = np.isfinite(x)
    csum = np.concatenate([[0.0], np.cumsum(np.where(finite, x, 0.0))])
    cbad = np.concatenate([[0], np.cumsum(~finite)])
    sums = csum[window:] - csum[:-window]
    bad = cbad[window:] - cbad[:-window]
    out[window - 1 :] = np.where(bad == 0, sums / window, np.nan)
    return out


def window_distances(values: np.ndarray, block_days: int, max_lag: int) -> tuple[np.ndarray, np.ndarray]:
    """For each window end t: (smallest distance to an earlier window, the lag achieving it)."""
    n = values.shape[0]
    best = np.full(n, np.inf)
    best_lag = np.zeros(n, dtype=int)
    for lag in range(1, min(max_lag, n - block_days) + 1):
        diff = np.abs(values[lag:] - values[:-lag])           # day t compared with t - lag
        per_day = diff.mean(axis=1)                            # NaN if any variable is NaN
        dist = np.full(n, np.nan)
        dist[lag:] = _rolling_mean_strict(per_day, block_days)
        better = dist < best
        best[better] = dist[better]
        best_lag[better] = lag
    best[~np.isfinite(best)] = np.nan
    return best, best_lag


def _day_scores(window_best: np.ndarray, block_days: int) -> np.ndarray:
    """Day score = smallest distance over the windows that contain the day."""
    n = window_best.size
    filled = np.where(np.isfinite(window_best), window_best, np.inf)
    out = np.full(n, np.inf)
    for k in range(block_days):  # window ending at t + k contains day t
        out[: n - k] = np.minimum(out[: n - k], filled[k:])
    out[~np.isfinite(out)] = np.nan
    return out


class ReplayDetector(Detector):
    name = "replay"

    @staticmethod
    def columns(cfg: dict) -> list[str]:
        """Columns the replay matcher reads: the station values, not the residuals."""
        mapping = cfg.get("replay", {}).get("columns") or {}
        variables = monitored_variables(cfg)
        if mapping:
            return [mapping[v] for v in variables]
        return [cfg["residual_variables"][v] for v in variables]

    def _blocks(self, x: pd.DataFrame, block_days: int) -> list[tuple[int, np.ndarray]]:
        """(start, chunk) for each complete, non-overlapping block of block_days."""
        n = x.shape[0]
        values = x.to_numpy(dtype=float)
        out = []
        for start in range(0, n - block_days + 1, block_days):
            chunk = values[start : start + block_days]
            if np.isfinite(chunk).all():
                out.append((start, chunk))
        return out

    def fit(self, train: pd.DataFrame, cfg: dict) -> dict:
        rcfg = cfg.get("replay", {})
        cols = self.columns(cfg)
        block_days = int(rcfg.get("block_days", 7))
        max_lag = int(rcfg.get("max_lag_days", 730))
        if train.shape[0] < block_days * 2:
            raise ValueError(f"Replay needs at least {block_days * 2} train days, got {train.shape[0]}")
        scale = train[cols].std(axis=0, ddof=1).to_numpy(dtype=float)
        scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, 1.0)
        scaled = train[cols].to_numpy(dtype=float) / scale
        train_best, _ = window_distances(scaled, block_days, max_lag)
        finite = train_best[np.isfinite(train_best)]
        return {
            "columns": cols,
            "block_days": block_days,
            "max_lag": max_lag,
            "scale": [float(s) for s in scale],
            "threshold": float(rcfg.get("tolerance", 0.05)),
            # smallest natural distance seen in train: the margin between real
            # weather and a copy.  If it is below the tolerance, the train data
            # already contains a repeat (a frozen sensor or a provider fault).
            "train_min_distance": float(finite.min()) if finite.size else float("nan"),
            "history": scaled[-max_lag:].copy(),
        }

    def _scan(self, test: pd.DataFrame, params: dict) -> tuple[np.ndarray, np.ndarray]:
        scale = np.asarray(params["scale"], dtype=float)
        history = np.asarray(params["history"], dtype=float)
        values = np.vstack([history, test[params["columns"]].to_numpy(dtype=float) / scale])
        best, lag = window_distances(values, params["block_days"], params["max_lag"])
        h = history.shape[0]
        return best[h:], lag[h:]

    def score(self, test: pd.DataFrame, params: dict, cfg: dict) -> pd.DataFrame:
        best, _lag = self._scan(test, params)
        day = _day_scores(best, params["block_days"])
        any_nan = test[params["columns"]].isna().any(axis=1).to_numpy()
        day = np.where(any_nan, np.nan, day)
        flag = np.isfinite(day) & (day < params["threshold"])
        return pd.DataFrame({"score": day, "flag": flag.astype(int)}, index=test.index)

    def per_variable(self, test: pd.DataFrame, params: dict, cfg: dict) -> dict[str, pd.DataFrame]:
        """Window-level detail: smallest distance and the lag of the matching earlier window."""
        best, lag = self._scan(test, params)
        frame = pd.DataFrame({"window_distance": best, "lag_days": np.where(np.isfinite(best), lag, 0)},
                             index=test.index)
        return {"all": frame}
