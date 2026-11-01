"""Trend detector: rolling Mann-Kendall test on prewhitened residuals.

A drift attack moves the reading a little more each day.  The Mann-Kendall test
asks whether the values in a window tend to rise (or fall) over time, using
only the order of the values, so a few extreme days do not dominate it.

How it works:

1. Prewhitening.  Mann-Kendall assumes independent days, but the residuals
   are autocorrelated (each day resembles the one before), which inflates z
   and causes false alarms.  Each residual is replaced by its AR(1) prediction
   error from the train model, as in the CUSUM.  A real drift survives this:
   for x_t = a*t, the prediction error is (1 - phi)*a*t + phi*a, still a trend.
2. For each day, the Mann-Kendall z over the last ``window_days`` days, per
   variable.  The day's score is the largest |z| across variables, so an
   upward and a downward drift count the same.
3. Threshold.  ``trend.threshold`` is a number or ``auto``.  With ``auto``, it
   is the larger of two values:
   * the theoretical Mann-Kendall critical value at ``significance_level``
     (two-sided, z ~ N(0, 1) under no trend, Bonferroni-corrected for the
     number of variables because the score is their maximum), which protects
     against a short
     train period: overlapping windows make even three years worth only a
     handful of independent windows;
   * the lowest value giving at most ``target_false_alarms_per_year`` separate
     alarms per year on the clean train years (a run of flagged days counts
     once), on the same combined score used at scoring, which protects against
     real residuals that are noisier than the theory assumes.
4. A window with more than ``max_missing_share`` missing days is not scored.
   With ``use_train_history`` the scoring period starts with the last
   ``window_days`` of train, so early days get a full window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from sensorguard.processing.detector_s import stats
from sensorguard.processing.detector_s.base import Detector, monitored_variables

__all__ = ["TrendDetector"]


class TrendDetector(Detector):
    name = "trend"

    @staticmethod
    def _rolling(x: np.ndarray, window: int, min_days: int, max_missing: float,
                 with_slope: bool = False) -> tuple[np.ndarray, np.ndarray]:
        n = x.size
        z = np.full(n, np.nan)
        slope = np.full(n, np.nan)
        for t in range(n):
            y = x[max(0, t - window + 1) : t + 1]
            if y.size < min_days or np.isnan(y).mean() > max_missing:
                continue
            _, _, z[t] = stats.mann_kendall(y)
            if with_slope:
                slope[t] = stats.sen_slope(y)
        return z, slope

    def _prewhiten(self, x: pd.Series, params: dict, v: str) -> np.ndarray:
        if not params["prewhiten"]:
            return x.to_numpy(dtype=float)
        return stats.whiten(x, np.asarray(params["coef"][v], dtype=float), params["sigma"][v], 1).to_numpy(dtype=float)

    def _combined(self, frame: pd.DataFrame, params: dict, history: dict | None = None) -> np.ndarray:
        per_var = []
        for v, col in zip(params["variables"], params["columns"]):
            x = frame[col].astype(float)
            h = 0
            if history is not None:
                x = pd.concat([pd.Series(history[v]), x.reset_index(drop=True)], ignore_index=True)
                h = len(history[v])
            w = self._prewhiten(x.reset_index(drop=True), params, v)
            z, _ = self._rolling(w, params["window_days"], params["min_train_days"], params["max_missing"])
            per_var.append(np.abs(z[h:]))
        return np.max(np.vstack(per_var), axis=0)

    def fit(self, train: pd.DataFrame, cfg: dict) -> dict:
        c = cfg.get("trend", {})
        variables = list(monitored_variables(cfg))
        params: dict = {
            "variables": variables,
            "columns": [cfg["residual_variables"][v] for v in variables],
            "window_days": int(c.get("window_days", 150)),
            "min_train_days": int(c.get("min_train_days", 100)),
            "max_missing": float(c.get("max_missing_share", 0.2)),
            "prewhiten": bool(c.get("prewhiten", True)),
            "coef": {}, "sigma": {},
            "train_days": int(train.shape[0]),
        }
        for v, col in zip(variables, params["columns"]):
            coef, sigma = stats.fit_ar(train[col].astype(float), 1)
            params["coef"][v] = [float(a) for a in coef]
            params["sigma"][v] = float(sigma)
        threshold = c.get("threshold", "auto")
        if str(threshold).lower() == "auto":
            combined = self._combined(train, params)
            calibrated, reached = stats.threshold_for_events(combined, float(c.get("target_false_alarms_per_year", 1.0)))
            # Bonferroni: the score is the max over len(variables) tests
            alpha = float(c.get("significance_level", 0.001)) / len(variables)
            theory = float(norm.ppf(1.0 - alpha / 2.0))
            params.update(threshold=max(theory, calibrated), threshold_theory=theory,
                          threshold_calibrated=calibrated, threshold_source="auto",
                          train_alarms_per_year=reached)
        else:
            params.update(threshold=float(threshold), threshold_source="config")
        if bool(c.get("use_train_history", False)):
            w = params["window_days"]
            params["train_history"] = {v: train[col].astype(float).to_numpy()[-w:].copy()
                                       for v, col in zip(variables, params["columns"])}
        return params

    def score(self, test: pd.DataFrame, params: dict, cfg: dict) -> pd.DataFrame:
        z = self._combined(test, params, params.get("train_history"))
        any_nan = test[params["columns"]].isna().any(axis=1).to_numpy()
        z = np.where(any_nan, np.nan, z)
        flag = np.isfinite(z) & (z > params["threshold"])
        return pd.DataFrame({"score": z, "flag": flag.astype(int)}, index=test.index)

    def per_variable(self, test: pd.DataFrame, params: dict, cfg: dict) -> dict[str, pd.DataFrame]:
        out = {}
        for v, col in zip(params["variables"], params["columns"]):
            w = self._prewhiten(test[col].astype(float), params, v)
            z, slope = self._rolling(w, params["window_days"], params["min_train_days"], params["max_missing"],
                                     with_slope=True)
            frame = pd.DataFrame({"z": z, "slope": slope}, index=test.index)
            frame["flag"] = (np.abs(frame["z"]) > params["threshold"]).astype(int)
            out[v] = frame
        return out
