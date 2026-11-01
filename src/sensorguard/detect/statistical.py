"""Detector S on a pipeline run: fit every statistical test on the train years, score the rest.

The detectors themselves live in ``sensorguard.processing.detector_s``; this
module only feeds them.  It takes the two things a run produces,

    reference   standardised reference residuals, one column per variable
    received    the station values that got through layer 1

puts them in the column layout of ``config/detector_s.yaml`` (``reference_<var>``
for residuals, ``station_<var>`` for station values), fits each detector on the
train period only and scores the scoring period (the validation year by
default).

Before fitting, the slow year-to-year shift is removed from the residuals
(``baseline`` section of the config, see ``detector_s/baseline.py``).

The combined flag is a plain OR of the flags of ``combined_flag_detectors``
(config); the others are still computed and reported.  Fusing them into a
compromise probability is the job of the trust score, not of detector S.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from sensorguard.processing.detector_s import baseline
from sensorguard.processing.detector_s.base import load_detector_config, monitored_variables
from sensorguard.processing.detector_s.cusum import CusumDetector
from sensorguard.processing.detector_s.mahalanobis import MahalanobisDetector
from sensorguard.processing.detector_s.replay import ReplayDetector
from sensorguard.processing.detector_s.trend import TrendDetector

# Change-point dating comes from CusumDetector.episodes, so ChangePointDetector is not run separately.
DETECTORS = (CusumDetector, TrendDetector, ReplayDetector, MahalanobisDetector)


@dataclass
class DetectorSResult:
    daily: pd.DataFrame                  # scoring period: <name>_score, <name>_flag, flag (OR of combined_flag_detectors)
    episodes: list[dict]                 # CUSUM episodes with estimated onset date and type
    params: dict[str, Any]               # fitted parameters per detector (thresholds etc.)
    seconds: dict[str, float] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [c[: -len("_flag")] for c in self.daily.columns if c.endswith("_flag")]


def detector_frame(reference: pd.DataFrame, received: pd.DataFrame) -> pd.DataFrame:
    """One table in the detector S column layout."""
    frame = pd.concat([reference.add_prefix("reference_"), received.add_prefix("station_")], axis=1)
    frame.index.name = "date"
    return frame.sort_index()


def _prepared(reference: pd.DataFrame, received: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    frame = detector_frame(reference, received)
    # Slow-shift removal runs on the whole history, before the split, so the
    # scoring period starts with a full window of past days.  Residual columns
    # only: the replay matcher needs the raw station values.
    residual_cols = [cfg["residual_variables"][v] for v in monitored_variables(cfg)]
    return baseline.remove_baseline(frame, residual_cols, cfg)


@dataclass
class FittedDetectorS:
    """Every detector fitted on the train years of one site; score many series with it."""
    cfg: dict[str, Any]
    split: dict[str, str]
    fitted: list[tuple[Any, dict[str, Any]]]     # (detector, params)
    train_index: pd.DatetimeIndex
    seconds: dict[str, float] = field(default_factory=dict)


def fit(reference: pd.DataFrame, received: pd.DataFrame, split: dict[str, str],
        cfg: dict[str, Any] | None = None, detectors=DETECTORS) -> FittedDetectorS:
    """Fit every detector on [train_start, train_end] only."""
    cfg = cfg or load_detector_config()
    train = _prepared(reference, received, cfg).loc[split["train_start"] : split["train_end"]]
    fitted, seconds = [], {}
    for cls in detectors:
        det = cls()
        t = time.perf_counter()
        fitted.append((det, det.fit(train, cfg)))
        seconds[det.name] = time.perf_counter() - t
    return FittedDetectorS(cfg, split, fitted, train.index, seconds)


def score(model: FittedDetectorS, reference: pd.DataFrame, received: pd.DataFrame) -> DetectorSResult:
    """Score [validation_start, validation_end] with detectors fitted earlier.

    The series may differ from the one used in ``fit`` only inside the
    scoring period (an attack in the validation year): the fitted parameters
    describe the train years, so they stay valid.
    """
    cfg, split = model.cfg, model.split
    test = _prepared(reference, received, cfg).loc[split["validation_start"] : split["validation_end"]]
    columns: dict[str, pd.Series] = {}
    params: dict[str, Any] = {}
    seconds: dict[str, float] = {}
    episodes: list[dict] = []
    for det, p in model.fitted:
        t = time.perf_counter()
        out = det.score(test, p, cfg)
        if isinstance(det, CusumDetector):
            episodes = det.episodes(test, p, cfg)
        seconds[det.name] = time.perf_counter() - t
        columns[f"{det.name}_score"] = out["score"].astype(float)
        columns[f"{det.name}_flag"] = out["flag"].astype(int)
        params[det.name] = {k: v for k, v in p.items() if k not in ("history", "train_history", "train_blocks")}
    daily = pd.DataFrame(columns, index=test.index)
    combined = cfg.get("combined_flag_detectors") or [det.name for det, _ in model.fitted]
    daily["flag"] = daily[[f"{n}_flag" for n in combined if f"{n}_flag" in daily]].max(axis=1).astype(int)
    return DetectorSResult(daily, episodes, params, seconds)


def run(reference: pd.DataFrame, received: pd.DataFrame, split: dict[str, str],
        cfg: dict[str, Any] | None = None, detectors=DETECTORS) -> DetectorSResult:
    """Fit on [train_start, train_end], score [validation_start, validation_end]."""
    model = fit(reference, received, split, cfg, detectors)
    result = score(model, reference, received)
    result.seconds = {k: model.seconds[k] + result.seconds[k] for k in result.seconds}
    return result


def alarm_events(flags: pd.Series) -> int:
    """Number of separate alarms: runs of consecutive flagged days count once."""
    f = flags.astype(bool).to_numpy()
    return int(f[0] + np.sum(f[1:] & ~f[:-1])) if f.size else 0


def evaluate(daily: pd.DataFrame, attacked: pd.Series) -> pd.DataFrame:
    """Per detector: detected or not, delay to first flag, false alarms.

    ``attacked`` is the per-day label (True on attacked days that reached the
    pipeline).  Days with no score count as not flagged.  False alarms are
    given two ways: the share of clean days flagged, and separate alarm events
    per year on clean days (a run of flagged days counts once).
    """
    attacked = attacked.reindex(daily.index).fillna(False).astype(bool)
    att_days = daily.index[attacked]
    rows = []
    for name in [c[: -len("_flag")] for c in daily.columns if c.endswith("_flag")] + ["flag"]:
        col = name if name == "flag" else f"{name}_flag"
        flags = daily[col].astype(bool)
        hits = flags[attacked]
        first = hits[hits].index.min() if hits.any() else pd.NaT
        rows.append({
            "detector": "any" if name == "flag" else name,
            "detected": bool(hits.any()),
            "flagged_in_attack": float(hits.mean()) if len(att_days) else np.nan,
            "days_to_first_flag": float((first - att_days[0]).days) if pd.notna(first) else np.nan,
            "false_alarm_rate": float(flags[~attacked].mean()) if (~attacked).any() else np.nan,
            "false_alarms_per_year": (alarm_events(flags[~attacked]) / ((~attacked).sum() / 365.25)
                                      if (~attacked).any() else np.nan),
        })
    return pd.DataFrame(rows).set_index("detector")
