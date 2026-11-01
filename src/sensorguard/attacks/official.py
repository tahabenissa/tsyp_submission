"""The three attacks of the official standard test: 12 % step, drift to 15 %, 7-day replay.

Each attack takes a clean daily table and returns a new table plus exact
labels; the input is never changed. ``apply_scenario`` places the attack
with a seeded random generator, so the same seed always gives the same
series and the same labels.

Command line (one scenario file, one input series):

    python -m sensorguard.attacks.official \
        --scenario scenarios/standard/step_12pct.yaml \
        --input data/raw/semiarid.csv --out results/attacks/semiarid/step --clean

Add --only "T2M,up,value" to run some settings only, --list to see their names.
"""

from __future__ import annotations

import argparse
import itertools
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from sensorguard.attacks.labels import (
    Episode,
    base_quantity,
    check_daily,
    empty_labels,
    episodes_table,
    mark,
)


@dataclass
class AttackResult:
    series: pd.DataFrame
    labels: pd.DataFrame
    episodes: list[Episode]


# --------------------------------------------------------------------------- helpers


def _window(index: pd.DatetimeIndex, onset: pd.Timestamp, length_days: int | None) -> pd.DatetimeIndex:
    """The attacked days: ``length_days`` days from ``onset`` (None = to the end)."""
    onset = pd.Timestamp(onset)
    if onset not in index:
        raise ValueError(f"onset {onset.date()} is not in the series")
    start = index.get_loc(onset)
    stop = len(index) if length_days is None else start + length_days
    if stop > len(index):
        raise ValueError(f"the attack runs past the end of the series ({length_days} days from {onset.date()})")
    return index[start:stop]


def _origin(value_origin: float | dict | None, variable: str) -> float:
    if isinstance(value_origin, dict):
        return float(value_origin.get(variable, 0.0))
    return float(value_origin or 0.0)


def _apply_offset(
    df: pd.DataFrame,
    variables: list[str],
    days: pd.DatetimeIndex,
    fraction: np.ndarray,
    relative_to: str,
    value_origin: float | dict | None,
    limits: dict | None,
) -> tuple[pd.DataFrame, np.ndarray]:
    """x' = x + fraction * base, then cut back to physical limits if given."""
    out = df.copy()
    clipped = np.zeros(len(days), dtype=bool)
    for var in variables:
        if var not in df.columns:
            raise KeyError(f"variable {var!r} is not in the series")
        base = base_quantity(df[var], relative_to, days[0], _origin(value_origin, var))
        new = df.loc[days, var].to_numpy(dtype=float) + fraction * base.loc[days].to_numpy(dtype=float)
        lo, hi = (limits or {}).get(var, (None, None))
        if lo is not None or hi is not None:
            cut = np.clip(new, lo if lo is not None else -np.inf, hi if hi is not None else np.inf)
            clipped |= ~np.isnan(new) & (cut != new)
            new = cut
        out.loc[days, var] = new
    return out, clipped


# --------------------------------------------------------------------------- the three attacks


def step_bias(
    df: pd.DataFrame,
    variables: list[str],
    onset,
    magnitude: float = 0.12,
    sign: int = 1,
    relative_to: str = "value",
    length_days: int | None = None,
    value_origin: float | dict | None = None,
    limits: dict | None = None,
    episode_id: int = 0,
    seed: int | None = None,
    labels: pd.DataFrame | None = None,
) -> AttackResult:
    """F1. From ``onset`` on, every value is moved by the same fraction."""
    check_daily(df.index)
    days = _window(df.index, onset, length_days)
    fraction = np.full(len(days), sign * magnitude)
    out, clipped = _apply_offset(df, variables, days, fraction, relative_to, value_origin, limits)
    ep = Episode(episode_id, "step", tuple(variables), days[0], days[-1], magnitude, sign, relative_to, seed,
                 {"length_days": length_days})
    labels = mark(labels if labels is not None else empty_labels(df.index), days, ep, fraction, clipped=clipped)
    return AttackResult(out, labels, [ep])


def drift(
    df: pd.DataFrame,
    variables: list[str],
    onset,
    magnitude: float = 0.15,
    ramp_days: int = 30,
    hold_days: int = 0,
    sign: int = 1,
    relative_to: str = "value",
    value_origin: float | dict | None = None,
    limits: dict | None = None,
    episode_id: int = 0,
    seed: int | None = None,
    labels: pd.DataFrame | None = None,
) -> AttackResult:
    """F2. The offset grows in a straight line and reaches ``magnitude`` on the
    last day of the ramp, then stays there for ``hold_days`` days.

    Day k of the ramp (k = 0, 1, ...) gets magnitude * (k + 1) / ramp_days, so
    the first attacked day is already slightly off and day ``ramp_days`` is at
    the full 15 %.
    """
    check_daily(df.index)
    if ramp_days < 1:
        raise ValueError("ramp_days must be at least 1")
    days = _window(df.index, onset, ramp_days + hold_days)
    k = np.arange(len(days))
    fraction = sign * magnitude * np.minimum((k + 1) / ramp_days, 1.0)
    out, clipped = _apply_offset(df, variables, days, fraction, relative_to, value_origin, limits)
    ep = Episode(episode_id, "drift", tuple(variables), days[0], days[-1], magnitude, sign, relative_to, seed,
                 {"ramp_days": ramp_days, "hold_days": hold_days})
    labels = mark(labels if labels is not None else empty_labels(df.index), days, ep, fraction, clipped=clipped)
    return AttackResult(out, labels, [ep])


def replay(
    df: pd.DataFrame,
    onset,
    length_days: int = 7,
    source_offset_days: int = 7,
    variables: list[str] | None = None,
    episode_id: int = 0,
    seed: int | None = None,
    labels: pd.DataFrame | None = None,
) -> AttackResult:
    """F3. ``length_days`` days are replaced by the same number of genuine days
    copied from ``source_offset_days`` earlier.

    By default every variable is replayed: an attacker who replays a record
    replays the whole record, which keeps the variables consistent with each
    other and defeats the physical checks.
    """
    check_daily(df.index)
    if source_offset_days < length_days:
        raise ValueError("source_offset_days must be >= length_days so the copied days are genuine, not attacked")
    variables = list(df.columns) if variables is None else list(variables)
    days = _window(df.index, onset, length_days)
    start = df.index.get_loc(days[0]) - source_offset_days
    if start < 0:
        raise ValueError(f"no data {source_offset_days} days before {days[0].date()} to replay")
    src = df.index[start:start + length_days]
    out = df.copy()
    out.loc[days, variables] = df.loc[src, variables].to_numpy()
    ep = Episode(episode_id, "replay", tuple(variables), days[0], days[-1], seed=seed,
                 params={"length_days": length_days, "source_offset_days": source_offset_days})
    labels = mark(labels if labels is not None else empty_labels(df.index), days, ep, 0.0, source_dates=src)
    return AttackResult(out, labels, [ep])


# --------------------------------------------------------------------------- scenarios


def draw_onset(index: pd.DatetimeIndex, rng: np.random.Generator, episode_days: int, earliest: int) -> pd.Timestamp:
    """A random onset that leaves ``earliest`` clean days before it and room for the episode after it."""
    latest = len(index) - episode_days
    if latest < earliest:
        raise ValueError(f"series too short: need {earliest} days of history plus {episode_days} attacked days")
    return index[int(rng.integers(earliest, latest + 1))]


def _tag(key: str, value) -> str:
    """How one swept setting appears in a run name."""
    if key == "sign":
        return "up" if value > 0 else "down"
    if key == "ramp_days":
        return f"ramp{value}"
    if key == "source_offset_days":
        return f"back{value}"
    return str(value)


def expand(cfg: dict) -> list[dict]:
    """Turn one scenario file into the list of runs it describes.

    Every key under ``sweep`` holds a list; each combination, for each seed, is one run.
    The run name lists its settings, e.g. ``T2M-up-value-ramp30-seed0`` or ``back7-seed0``.
    """
    sweep = cfg.get("sweep", {})
    keys = list(sweep)
    runs = []
    for combo in itertools.product(*(sweep[k] for k in keys)):
        for seed in cfg.get("seeds", [0]):
            run = {k: v for k, v in cfg.items() if k not in ("sweep", "seeds")}
            run.update(dict(zip(keys, combo)))
            run["seed"] = int(seed)
            run["run_id"] = "-".join([*(_tag(k, v) for k, v in zip(keys, combo)), f"seed{seed}"])
            runs.append(run)
    return runs


def select(runs: list[dict], only: str | None) -> list[dict]:
    """Keep the runs whose name contains every comma-separated tag, e.g. "T2M,up,value"."""
    if not only:
        return runs
    wanted = {t.strip() for t in only.split(",") if t.strip()}
    return [r for r in runs if wanted <= set(r["run_id"].split("-"))]


def apply_scenario(df: pd.DataFrame, run: dict) -> AttackResult:
    """Apply one run (one element of ``expand``) to a clean series."""
    check_daily(df.index)
    rng = np.random.default_rng(run["seed"])
    history = int(run.get("min_history_days", 365))
    attack = run["attack"]
    variables = run.get("variables")
    if isinstance(variables, str):
        variables = [variables]

    if attack == "step":
        length = run.get("length_days")
        onset = draw_onset(df.index, rng, length or 1, history)
        return step_bias(df, variables, onset, run.get("magnitude", 0.12), run.get("sign", 1),
                         run.get("relative_to", "value"), length, run.get("value_origin"),
                         run.get("limits"), seed=run["seed"])
    if attack == "drift":
        ramp, hold = int(run.get("ramp_days", 30)), int(run.get("hold_days", 0))
        onset = draw_onset(df.index, rng, ramp + hold, history)
        return drift(df, variables, onset, run.get("magnitude", 0.15), ramp, hold, run.get("sign", 1),
                     run.get("relative_to", "value"), run.get("value_origin"), run.get("limits"),
                     seed=run["seed"])
    if attack == "replay":
        length, offset = int(run.get("length_days", 7)), int(run.get("source_offset_days", 7))
        onset = draw_onset(df.index, rng, length, max(history, offset))
        return replay(df, onset, length, offset, variables, seed=run["seed"])
    raise ValueError(f"unknown attack {attack!r}")


# --------------------------------------------------------------------------- command line


def load_series(path: str | Path) -> pd.DataFrame:
    """A CSV whose first column is the date and the others are variables."""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "date"
    return df


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inject an official attack scenario into a clean daily series.")
    p.add_argument("--scenario", required=True, help="YAML file in scenarios/")
    p.add_argument("--input", help="clean daily CSV, first column = date")
    p.add_argument("--out", help="output folder")
    p.add_argument("--list", action="store_true", help="only print the setting names in the scenario and stop")
    p.add_argument("--only", help='run only the settings whose name has all these tags, e.g. "T2M,up,value"')
    p.add_argument("--clean", action="store_true", help="delete the output folder first, so no old runs are left")
    a = p.parse_args(argv)

    cfg = yaml.safe_load(Path(a.scenario).read_text(encoding="utf-8"))
    if a.list:
        names = [r["run_id"] for r in select(expand(cfg), a.only)]
        print("\n".join(names))
        print(f"({len(names)} settings)")
        return 0
    if not a.input or not a.out:
        p.error("--input and --out are needed to run (or use --list)")
    df = load_series(a.input)
    out = Path(a.out)
    if a.clean and out.exists():
        shutil.rmtree(out)
    runs = select(expand(cfg), a.only)
    if not runs:
        print(f"no run matches --only {a.only!r}", file=sys.stderr)
        return 1
    rows = []
    for run in runs:
        wanted = run.get("variables")
        wanted = [wanted] if isinstance(wanted, str) else (wanted or [])
        missing = [v for v in wanted if v not in df.columns]
        if missing:
            print(f"skip {run['run_id']}: {', '.join(missing)} not in {a.input}", file=sys.stderr)
            continue
        res = apply_scenario(df, run)
        run_dir = out / run["run_id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        res.series.to_csv(run_dir / "attacked.csv")
        res.labels.to_csv(run_dir / "labels.csv")
        ep = episodes_table(res.episodes)
        ep.insert(0, "run_id", run["run_id"])
        rows.append(ep)
    if rows:
        pd.concat(rows, ignore_index=True).to_csv(out / "episodes.csv", index=False)
    print(f"{len(rows)} runs written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
