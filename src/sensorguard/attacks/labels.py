"""Exact per-day labels for every injection.

Two outputs describe an attack:

* **Per-day labels**: one row per day, same index as the series.
    attacked      True on every day inside an attack episode
    attack        "none", "step", "drift", "replay", ...
    episode_id    -1 on clean days
    variables     the attacked variables, joined with ";" ("" on clean days)
    fraction      the signed size of the change that day, as a fraction of the
                  base quantity (0.12 for a +12 % step, -0.075 half-way through
                  a -15 % drift, 0 for replay)
    source_date   replay only: the day whose values were copied here
    clipped       True if a value was cut back to a physical limit that day

* **Episode table**: one row per episode, with the onset, the end and the
  parameters, so a detector's alarm can be matched to the attack it caught.

The reading table the attacks act on is a pandas DataFrame with a regular
daily DatetimeIndex (one row per day; a missing day is a row of NaN, never a
skipped row) and one column per variable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LABEL_COLUMNS = ["attacked", "attack", "episode_id", "variables", "fraction", "source_date", "clipped"]

# The three readings of "12 %" until the organizers say which one they mean.
RELATIVE_TO = ("value", "range", "std")


@dataclass(frozen=True)
class Episode:
    """One injected attack: what, where, when and with which parameters."""

    episode_id: int
    attack: str
    variables: tuple[str, ...]
    onset: pd.Timestamp
    end: pd.Timestamp  # last attacked day, inclusive
    magnitude: float = 0.0
    sign: int = 0
    relative_to: str = ""
    seed: int | None = None
    params: dict = field(default_factory=dict)


def check_daily(index: pd.Index) -> None:
    """Refuse anything that is not one row per consecutive day.

    The attacks count in rows, so a skipped day would silently turn
    "seven days" into "seven rows".
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("the series needs a DatetimeIndex")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("dates must be unique and increasing")
    if len(index) > 1 and not (np.diff(index.values) == np.timedelta64(1, "D")).all():
        raise ValueError("dates must be consecutive days; insert NaN rows for missing days")


def empty_labels(index: pd.DatetimeIndex) -> pd.DataFrame:
    """All days clean."""
    return pd.DataFrame(
        {
            "attacked": np.zeros(len(index), dtype=bool),
            "attack": pd.Series("none", index=index, dtype=object),
            "episode_id": np.full(len(index), -1, dtype=np.int64),
            "variables": pd.Series("", index=index, dtype=object),
            "fraction": np.zeros(len(index), dtype=float),
            "source_date": pd.Series(pd.NaT, index=index, dtype="datetime64[ns]"),
            "clipped": np.zeros(len(index), dtype=bool),
        },
        index=index,
    )


def mark(
    labels: pd.DataFrame,
    days: pd.DatetimeIndex,
    episode: Episode,
    fraction: np.ndarray | float = 0.0,
    source_dates: pd.DatetimeIndex | None = None,
    clipped: np.ndarray | None = None,
) -> pd.DataFrame:
    """Return a copy of ``labels`` with ``days`` marked as part of ``episode``."""
    out = labels.copy()
    if out.loc[days, "attacked"].any():
        raise ValueError(f"episode {episode.episode_id} overlaps an earlier episode")
    out.loc[days, "attacked"] = True
    out.loc[days, "attack"] = episode.attack
    out.loc[days, "episode_id"] = episode.episode_id
    out.loc[days, "variables"] = ";".join(episode.variables)
    out.loc[days, "fraction"] = fraction
    if source_dates is not None:
        out.loc[days, "source_date"] = source_dates.values
    if clipped is not None:
        out.loc[days, "clipped"] = clipped
    return out


def episodes_table(episodes: list[Episode]) -> pd.DataFrame:
    """One row per episode, ready to write to CSV."""
    rows = [
        {
            "episode_id": e.episode_id,
            "attack": e.attack,
            "variables": ";".join(e.variables),
            "onset": e.onset,
            "end": e.end,
            "magnitude": e.magnitude,
            "sign": e.sign,
            "relative_to": e.relative_to,
            "seed": e.seed,
            "params": json.dumps(e.params, sort_keys=True),
        }
        for e in episodes
    ]
    return pd.DataFrame(rows, columns=["episode_id", "attack", "variables", "onset", "end",
                                       "magnitude", "sign", "relative_to", "seed", "params"])


def base_quantity(
    series: pd.Series,
    relative_to: str,
    onset: pd.Timestamp,
    value_origin: float = 0.0,
) -> pd.Series:
    """What "12 %" is a percentage *of*, for every day.

    value  12 % of the reading itself: x -> x * 1.12. ``value_origin`` sets
           where zero is. For temperature in degrees C, 12 % of 20 C is 2.4 C,
           but 12 % of 293.15 K is 35 C, so pass value_origin=-273.15 to
           mean "12 % of the value in kelvin".
    range  12 % of the variable's normal span, measured on the clean days
           before onset (1st to 99th percentile, so one bad day does not set it).
    std    12 % of the variable's standard deviation before onset.

    ``range`` and ``std`` only look at days before the onset: the attacker's
    own values must not decide how big the attack is.
    """
    if relative_to == "value":
        return series - value_origin
    if relative_to not in RELATIVE_TO:
        raise ValueError(f"relative_to must be one of {RELATIVE_TO}, got {relative_to!r}")
    history = series.loc[: onset - pd.Timedelta(days=1)].dropna()
    if len(history) < 2:
        raise ValueError(f"{series.name}: not enough clean history before {onset.date()} for relative_to={relative_to!r}")
    if relative_to == "range":
        size = float(history.quantile(0.99) - history.quantile(0.01))
    else:
        size = float(history.std())
    return pd.Series(size, index=series.index, name=series.name)
