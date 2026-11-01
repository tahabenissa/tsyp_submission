"""Mahalanobis detector over standardized reference residuals."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2

from sensorguard.processing.detector_s.base import (
    Detector,
    get,
    monitored_variables,
)


class MahalanobisDetector(Detector):
    """Distance of the daily residual vector across variables.

    Centre and per-variable scale are robust (median and MAD).  Covariance is
    regularized on the train period only.  The score is the squared distance
    d2; the threshold is the chi-square quantile from config, not fitted on
    2024.  A day with any NaN variable gets
    score NaN and flag 0 (observability gap, not an attack).
    """

    name = "mahalanobis"

    def fit(self, train: pd.DataFrame, cfg: dict) -> dict:
        variables = list(monitored_variables(cfg))
        columns = [cfg["residual_variables"][v] for v in variables]
        x = train[columns].to_numpy(dtype=float)
        min_days = int(cfg.get("mahalanobis", {}).get("train_min_complete_days", 50))
        good = np.isfinite(x).all(axis=1)
        if int(good.sum()) < min_days:
            raise ValueError(
                f"Mahalanobis requires {min_days} complete train days, got {int(good.sum())}"
            )
        center = np.median(x[good], axis=0)
        spread = 1.4826 * np.median(np.abs(x[good] - center), axis=0)
        spread = np.where(np.isfinite(spread) & (spread > 1e-12), spread, 1e-12)
        z = (x[good] - center) / spread
        cov = np.cov(z, rowvar=False, ddof=1)
        p = z.shape[1]
        shrink = float(get(cfg, "mahalanobis.shrinkage", 0.10))
        n = z.shape[0]
        if n > p + 1:
            trace = float(np.trace(cov))
            cov = (1.0 - shrink) * cov + shrink * trace / p * np.eye(p)
        threshold = float(
            chi2.ppf(
                float(get(cfg, "mahalanobis.quantile", 0.999)),
                df=p,
            )
        )
        return {
            "columns": columns,
            "center": center,
            "scale": spread,
            "cov": cov,
            "threshold": threshold,
            "train_days": int(good.sum()),
        }

    def score(self, test: pd.DataFrame, params: dict, cfg: dict) -> pd.DataFrame:
        columns = params["columns"]
        missing = [c for c in columns if c not in test.columns]
        if missing:
            raise ValueError(f"Test residual file is missing columns: {missing}")
        x = test[columns].to_numpy(dtype=float)
        out = pd.DataFrame(index=test.index, columns=["score", "flag"])
        out["score"] = np.nan
        out["flag"] = 0
        good = np.isfinite(x).all(axis=1)
        if good.any():
            # Same robust scaling as in fit, then the squared distance, which
            # follows a chi-square law with p degrees of freedom on clean days.
            z = (x[good] - params["center"]) / params["scale"]
            d2 = np.maximum(np.sum(np.linalg.solve(params["cov"], z.T).T * z, axis=1), 0.0)
            out.loc[test.index[good], "score"] = d2
            out.loc[test.index[good], "flag"] = (d2 > params["threshold"]).astype(int)
        return out
