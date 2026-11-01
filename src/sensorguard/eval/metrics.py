"""Metrics for the evaluation: episode detection, latency, onset error, false alarms.

Fair detection.  A detector that raises one or two false alarms a year will,
by chance, sometimes alarm inside an attack window.  Counting that as a
detection makes every detector look good.  So every attacked run is compared
with the clean run of the same site and detector: an alarm counts for the
attack only if the clean run has no alarm on that day.

    new_alarm[d] = flag_attacked[d] and not flag_clean[d]

An episode is detected if there is at least one new alarm between its first
and its last attacked day (detected before it ends, as in docs/05).  Latency
is the first new alarm minus the onset, in days (daily data: 0 means the
attack was flagged on its first day).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson interval for a proportion (stays inside [0, 1] for small n)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def alarm_events(flags: pd.Series | np.ndarray) -> int:
    """Separate alarms: a run of consecutive flagged days counts once."""
    f = np.asarray(flags, dtype=bool)
    return int(f[0] + np.sum(f[1:] & ~f[:-1])) if f.size else 0


def false_alarms(flags: pd.Series) -> dict[str, float]:
    """On a clean run: alarm events per year and share of days flagged."""
    f = flags.astype(bool)
    years = len(f) / 365.25
    return {"false_alarms_per_year": alarm_events(f) / years if years else float("nan"),
            "false_alarm_day_share": float(f.mean()) if len(f) else float("nan")}


def episode_outcome(attacked_flags: pd.Series, clean_flags: pd.Series,
                    onset: pd.Timestamp, end: pd.Timestamp) -> dict[str, float | bool]:
    """Was the episode [onset, end] detected by a new alarm, and how fast."""
    new = attacked_flags.astype(bool) & ~clean_flags.reindex(attacked_flags.index).fillna(0).astype(bool)
    window = new.loc[onset:end]
    hits = window[window]
    first = hits.index.min() if len(hits) else pd.NaT
    return {
        "detected": bool(len(hits)),
        "latency_days": float((first - onset).days) if pd.notna(first) else float("nan"),
        "first_alarm": first,
        "attacked_days_flagged": float(window.mean()) if len(window) else float("nan"),
    }


def onset_error(episodes: list[dict], onset: pd.Timestamp, end: pd.Timestamp,
                clean_episodes: list[dict] | None = None) -> float:
    """Estimated minus true onset (days) for the first CUSUM episode alarming inside the attack.

    Episodes whose first alarm also exists in the clean run are skipped.
    NaN if no such episode.
    """
    clean_firsts = {e["first_alarm"] for e in (clean_episodes or [])}
    for e in episodes:
        first = pd.Timestamp(e["first_alarm"])
        if onset <= first <= end and e["first_alarm"] not in clean_firsts:
            return float((pd.Timestamp(e["start"]) - onset).days)
    return float("nan")
