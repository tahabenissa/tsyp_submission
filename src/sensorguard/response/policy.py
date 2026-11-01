"""The four graded responses: de-weighting, verification request, quarantine, alert.

Given the daily trust score and its band:

* **De-weighting.**  The value used downstream is a blend of the station and
  the calibrated reference (NASA POWER moved to the station's scale by the
  per-season calibration offset):
      used = w * station + (1 - w) * reference_calibrated
  w = 1 when trusted, falls linearly from 1 to 0 across the de-weight band,
  and is 0 in quarantine.  Only implicated variables are blended.
* **Verification request.**  Trust in the de-weight band and falling: ask for
  independent evidence (the next clear Sentinel-2 view, a neighbouring
  station, a technician's visit).  At most once per ``verification_every_days``.
* **Quarantine.**  The implicated variables are replaced by the calibrated
  reference (``implicated``: a variable whose residual against NASA POWER has
  been large recently; the whole record for a replay).  Rain is not replaced
  unless a replay is detected: substituting a 50 km grid's rain for a point
  gauge changes decisions on its own.
* **Alert.**  On entering quarantine: the operator is told why (the evidence
  that pushed the probability up), which variable, and since when (the
  estimated onset of the CUSUM episode, if there is one).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from sensorguard.detect.trust_score import DEWEIGHTED, QUARANTINED, Bands
from sensorguard.processing.calibrate import season_labels

REASONS = {
    "cusum_ratio": "lasting offset against NASA POWER (CUSUM)",
    "cusum_recent": "repeated CUSUM alarms",
    "maha_log": "unusual combination of variables against NASA POWER",
    "replay_log": "copy of an earlier week of the station's own values (replay)",
    "trend_ratio": "steady trend against NASA POWER",
    "gap7": "week-long gap against NASA POWER",
    "gap30": "month-long gap against NASA POWER",
    "m_flag": "learned detector M alarm",
    "m_recent": "repeated detector M alarms",
}


def calibrated_reference(power: pd.DataFrame, calibration: dict[str, Any], config: dict[str, Any]) -> pd.DataFrame:
    """NASA POWER moved to the station's scale with the per-season offsets (inverse of the residual transform)."""
    from sensorguard.processing.calibrate import witness
    power = witness(power, calibration)
    labels = season_labels(power.index, config["season_definition"])
    out = pd.DataFrame(index=power.index)
    pc = config["log_ratio_pseudocount"]
    for var, settings in config["variables"].items():
        col = pd.Series(np.nan, index=power.index)
        for season in config["season_definition"]:
            offset = calibration["variables"][var]["seasons"][season]["offset"]
            if offset is None:
                continue
            m = labels.eq(season)
            if settings["transform"] == "difference":
                col.loc[m] = power.loc[m, var] + offset
            else:
                col.loc[m] = (power.loc[m, var] + pc) * np.exp(offset) - pc
        out[var] = col.clip(lower=0) if var != "temp_c" else col
    if "rh_pct" in out:
        out["rh_pct"] = out["rh_pct"].clip(upper=100)
    return out


def weights(trust: pd.Series, band: pd.Series, bands: Bands) -> pd.Series:
    span = max(bands.deweight - bands.quarantine, 1e-9)
    w = ((trust - bands.quarantine) / span).clip(0, 1)
    w = w.where(band == DEWEIGHTED, 1.0)
    return w.where(band != QUARANTINED, 0.0).rename("weight")


def implicated(reference_residuals: pd.DataFrame, replay_detected: pd.Series | None = None,
               days: int = 14, sd: float = 1.0, rain: str = "precip_mm") -> pd.DataFrame:
    """Per day and variable: is this variable implicated in the disagreement?

    A variable is implicated when its standardized residual against NASA POWER
    has a mean beyond ``sd`` over the last ``days`` days (causal window).  A
    detected replay implicates every variable, rain included (the whole record
    is copied).  Otherwise rain is never implicated.
    """
    mean = reference_residuals.rolling(days, min_periods=max(1, days // 2)).mean()
    out = mean.abs() > sd
    if rain in out:
        out[rain] = False
    if replay_detected is not None:
        r = replay_detected.reindex(out.index).fillna(False).astype(bool)
        out = out.apply(lambda col: col | r)
    return out


def apply(station: pd.DataFrame, reference_cal: pd.DataFrame, w: pd.Series,
          implicated_vars: pd.DataFrame | None = None) -> pd.DataFrame:
    """The series used downstream after de-weighting and quarantine.

    Only the implicated variables are blended toward the calibrated reference
    (all variables if ``implicated_vars`` is None).
    """
    ww = pd.DataFrame({c: w.reindex(station.index).fillna(1.0) for c in station.columns})
    if implicated_vars is not None:
        imp = implicated_vars.reindex(index=station.index, columns=station.columns).fillna(False).astype(bool)
        ww = ww.where(imp, 1.0)
    ref = reference_cal.reindex(index=station.index, columns=station.columns)
    used = station * ww + ref * (1 - ww)
    # where the reference is missing, keep the station value
    return used.where(ref.notna(), station)


def actions(trust: pd.Series, band: pd.Series, contributions: pd.DataFrame | None = None,
            episodes: list[dict] | None = None, verification_every_days: int = 14,
            replay_flags: pd.Series | None = None) -> pd.DataFrame:
    """One row per action: date, action, reason.

    A replay found by the replay matcher in the last 7 days is always named
    in the reason: an exact copy of an earlier week is evidence on its own,
    whatever weight the fusion gives it.
    """
    rows = []
    last_request = None
    prev_band, prev_trust = None, None
    for day in trust.index:
        b, t = band.loc[day], trust.loc[day]
        if b == DEWEIGHTED and prev_trust is not None and t < prev_trust:
            if last_request is None or (day - last_request).days >= verification_every_days:
                rows.append({"date": day, "action": "verification request", "trust": t,
                             "reason": _reason(day, contributions, episodes, replay_flags)})
                last_request = day
        if b == QUARANTINED and prev_band != QUARANTINED:
            reason = _reason(day, contributions, episodes, replay_flags)
            rows.append({"date": day, "action": "quarantine", "trust": t, "reason": reason})
            rows.append({"date": day, "action": "alert", "trust": t, "reason": reason})
        if prev_band == QUARANTINED and b != QUARANTINED:
            rows.append({"date": day, "action": "release", "trust": t, "reason": "agrees with its context again"})
        prev_band, prev_trust = b, t
    return pd.DataFrame(rows, columns=["date", "action", "trust", "reason"])


def _reason(day, contributions, episodes, replay_flags=None) -> str:
    parts = []
    if replay_flags is not None:
        recent = replay_flags.loc[day - pd.Timedelta(days=6) : day]
        if recent.astype(bool).any():
            first = recent[recent.astype(bool)].index.min()
            parts.append(f"replay: the week from {first.date()} copies an earlier week of the station's own values")
    if contributions is not None and day in contributions.index:
        top = contributions.loc[day].idxmax()
        parts.append(REASONS.get(top, top))
    # cite a CUSUM episode only while it is current: its last alarm at most 14 days ago
    current = [e for e in episodes or []
               if pd.Timestamp(e["first_alarm"]) <= day <= pd.Timestamp(e["end"]) + pd.Timedelta(days=14)]
    if current:
        e = current[-1]
        parts.append(f"{e['variable']} {e['direction']}, {e['type']} since about {e['start']}")
    return "; ".join(parts)
