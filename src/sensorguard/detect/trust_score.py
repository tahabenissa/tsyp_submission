"""Station trust score and trust bands.

The trust score is a number between 0 and 1 per station, updated once a day
from the compromise probability p_t:

    risk_t  = risk_{t-1} + a * (p_t - risk_{t-1})       trust_t = 1 - risk_t
    a = fall_rate      when p_t > risk_{t-1}   (bad evidence: trust falls fast)
    a = recovery_rate  otherwise               (good evidence: trust comes back slowly)

With fall_rate 0.5, one day at p = 0.9 takes trust from 1 to 0.55.  With
recovery_rate 0.05, half of the lost trust comes back in about 14 quiet days.
That asymmetry is the point: one calm day must not restore a station that has
just been caught, and an attacker cannot reset trust by pausing for a day.

Bands.  The limits are set from the trust reached on CLEAN days of the
fitting sites, then frozen:

    deweight limit    clean days are below it ``deweight_clean_share`` of the time (5 %)
    quarantine limit  clean days are below it ``quarantine_clean_share`` of the time (0.5 %)

so the cost on honest stations is stated before the attack results are seen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRUSTED, DEWEIGHTED, QUARANTINED = "trusted", "de-weighted", "quarantined"


def trust_series(p: pd.Series, fall_rate: float = 0.5, recovery_rate: float = 0.05) -> pd.Series:
    risk = 0.0
    out = np.empty(len(p))
    for i, pt in enumerate(np.nan_to_num(p.to_numpy(dtype=float), nan=0.0)):
        a = fall_rate if pt > risk else recovery_rate
        risk += a * (pt - risk)
        out[i] = 1.0 - risk
    return pd.Series(out, index=p.index, name="trust")


@dataclass
class Bands:
    deweight: float      # below this: de-weighted
    quarantine: float    # below this: quarantined

    def as_dict(self) -> dict[str, float]:
        return {"deweight_below": self.deweight, "quarantine_below": self.quarantine}


def fit_bands(clean_trust: pd.Series, deweight_share: float = 0.05, quarantine_share: float = 0.005) -> Bands:
    t = clean_trust.dropna().to_numpy()
    return Bands(float(np.quantile(t, deweight_share)), float(np.quantile(t, quarantine_share)))


def band_series(trust: pd.Series, bands: Bands) -> pd.Series:
    """Band per day, with hysteresis: a quarantined station is released only once trust is
    back above the de-weight limit, not just above the quarantine limit."""
    out = []
    state = TRUSTED
    for t in trust.to_numpy():
        if t < bands.quarantine:
            state = QUARANTINED
        elif state == QUARANTINED and t < bands.deweight:
            state = QUARANTINED
        elif t < bands.deweight:
            state = DEWEIGHTED
        else:
            state = TRUSTED
        out.append(state)
    return pd.Series(out, index=trust.index, name="band")
