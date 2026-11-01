"""Fusion: the daily detector outputs become one compromise probability.

Each detector speaks its own unit (a CUSUM sum, a squared distance, a copy
distance, an LOF score).  Fusion puts them on a common footing and learns how
much each one says about "this reading is falsified".

Features for each day (all causal: they use that day and earlier days only):

    cusum_ratio      CUSUM statistic / its threshold      (1 = at the alarm level)
    cusum_recent     CUSUM alarms in the last N days      (persistence: a lasting
                                                          attack keeps re-alarming)
    maha_log         log(1 + Mahalanobis d2 / threshold)  (one unusual day)
    replay_log       log(tolerance / copy distance)       (> 0 when closer than the
                                                          tolerance, i.e. a copy)
    trend_ratio      trend |z| / its threshold
    m_flag           detector M alarm today
    m_recent         detector M alarms in the last N days
    gap7, gap30      largest |7-day| and |30-day| mean of the standardised
                     station-minus-witness residual over the variables (rain
                     left out: too noisy), divided by that station's own 95th
                     percentile of the same quantity on the days before the
                     scored period (its training years).  A drift is invisible
                     day by day but clear as a month-long average; these give
                     the fusion that average directly.  The per-station scale
                     matters: month-long gaps are naturally larger at some
                     stations (FAWN: 1.68 sigma at the 95th percentile, against
                     about 1.03 at AZMET and Kansas), and without it the
                     feature quarantined 47 clean FAWN days in 2024.

A logistic regression maps the features to the probability that the day is
attacked.  It is fitted on labelled runs (attacked days = 1, every other day =
0) of OTHER sites only, so the probability at a site never saw that site.

Calibration: logistic regression is fitted by maximum likelihood, so on data
like its training data the probabilities are calibrated.  That is checked on the
held-out site with a reliability table and the Brier score.  The probability
is relative to the share of attacked days in the evaluation runs (about 15 %);
a deployment with rarer attacks would shift it down by the prior ratio
(``prior_shift``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

FEATURES = ["cusum_ratio", "cusum_recent", "maha_log", "replay_log", "trend_ratio", "gap7", "gap30",
            "m_flag", "m_recent"]
GAP_EXCLUDED = ("precip_mm",)


def rolling_gaps(residuals: pd.DataFrame | None, index: pd.DatetimeIndex,
                 scale_before: pd.Timestamp | None = None, quantile: float = 0.95,
                 minimum_days: int = 180) -> pd.DataFrame:
    """gap7 / gap30: largest absolute rolling mean residual across the variables (causal).

    With ``scale_before``, each is divided by its ``quantile`` over the residual
    days strictly before that date (the training years), so 1 means "as large
    as this station's 95th percentile on clean training data".
    """
    out = pd.DataFrame(0.0, index=index, columns=["gap7", "gap30"])
    if residuals is None:
        return out
    r = residuals[[c for c in residuals.columns if c not in GAP_EXCLUDED]].astype(float)
    for name, days, need in (("gap7", 7, 5), ("gap30", 30, 20)):
        gap = r.rolling(days, min_periods=need).mean().abs().max(axis=1)
        scale = 1.0
        if scale_before is not None:
            history = gap.loc[gap.index < pd.Timestamp(scale_before)].dropna()
            if len(history) >= minimum_days:
                scale = max(float(history.quantile(quantile)), 1e-6)
        out[name] = (gap / scale).reindex(index).clip(0, 5)
    return out.fillna(0.0)


def features(daily: pd.DataFrame, params: dict[str, Any], m_flags: pd.Series | None,
             persistence_days: int = 30, residuals: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily features from a detector S result (``DetectorSResult.daily`` and ``.params``), M flags
    and the standardised reference residuals the detectors were run on."""
    p = params
    out = pd.DataFrame(index=daily.index)
    out["cusum_ratio"] = (daily["cusum_score"] / p["cusum"]["threshold"]).clip(0, 3)
    out["cusum_recent"] = daily["cusum_flag"].rolling(persistence_days, min_periods=1).sum()
    out["maha_log"] = np.log1p(daily["mahalanobis_score"] / p["mahalanobis"]["threshold"])
    dist = daily["replay_score"].clip(lower=1e-3)
    out["replay_log"] = np.log(p["replay"]["threshold"] / dist).clip(-5, 5)
    out["trend_ratio"] = (daily["trend_score"] / p["trend"]["threshold"]).clip(0, 3)
    out[["gap7", "gap30"]] = rolling_gaps(residuals, daily.index, scale_before=daily.index.min())
    if m_flags is None:
        m_flags = pd.Series(0, index=daily.index)
    m = m_flags.reindex(daily.index).fillna(0).astype(float)
    out["m_flag"] = m
    out["m_recent"] = m.rolling(persistence_days, min_periods=1).sum()
    # A missing score (a day with a missing variable) carries no evidence.
    defaults = {"replay_log": -5.0}
    return out.fillna({c: defaults.get(c, 0.0) for c in out.columns})[FEATURES]


@dataclass
class FusionModel:
    model: LogisticRegression
    feature_names: list[str]
    train_attacked_share: float

    def probability(self, x: pd.DataFrame) -> pd.Series:
        return pd.Series(self.model.predict_proba(x[self.feature_names].to_numpy())[:, 1], index=x.index)

    def contributions(self, x: pd.DataFrame) -> pd.DataFrame:
        """coefficient x value per feature: which evidence drove the probability (for alert reasons)."""
        return x[self.feature_names] * self.model.coef_[0]

    def coefficients(self) -> dict[str, float]:
        return {"intercept": float(self.model.intercept_[0]),
                **{f: float(c) for f, c in zip(self.feature_names, self.model.coef_[0])}}


def fit(x: pd.DataFrame, y: pd.Series, c: float = 1.0, feature_names: list[str] | None = None) -> FusionModel:
    names = feature_names or FEATURES
    model = LogisticRegression(C=c, max_iter=1000)
    model.fit(x[names].to_numpy(), y.astype(int).to_numpy())
    return FusionModel(model, names, float(y.mean()))


def prior_shift(p: pd.Series, train_prior: float, new_prior: float) -> pd.Series:
    """Move probabilities from the training share of attacked days to another prior (Bayes on the odds)."""
    odds = p / (1 - p) * (new_prior / (1 - new_prior)) / (train_prior / (1 - train_prior))
    return odds / (1 + odds)


def reliability(p: pd.Series, y: pd.Series, bins: int = 10) -> pd.DataFrame:
    """Per probability bin: mean predicted probability against the observed attacked share."""
    edges = np.linspace(0, 1, bins + 1)
    b = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    frame = pd.DataFrame({"bin": b, "p": p.to_numpy(), "y": y.astype(int).to_numpy()})
    table = frame.groupby("bin").agg(days=("y", "size"), mean_probability=("p", "mean"), attacked_share=("y", "mean"))
    table.index = [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in table.index]
    return table


def scores(p: pd.Series, y: pd.Series) -> dict[str, float]:
    y = y.astype(int)
    return {"brier": float(brier_score_loss(y, p)),
            "brier_no_skill": float(brier_score_loss(y, np.full(len(y), y.mean()))),
            "roc_auc": float(roc_auc_score(y, p)) if y.nunique() > 1 else float("nan")}
