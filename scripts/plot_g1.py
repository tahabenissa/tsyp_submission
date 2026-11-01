"""G1 check: plot a station series against NASA POWER on clean data.

Example (Kansas site):
    python scripts/plot_g1.py --site-id site_c --network kansas \
        --station "Manhattan" --lat 39.20857 --lon -96.59169 \
        --start 2023-01-01 --end 2024-12-31

Output: results/figures/g1_<site-id>.png and a small table in the terminal
(mean gap and correlation per variable). Titles use the neutral site id,
never the real station name (anonymity, Q5).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window needed, we only save a file
import matplotlib.pyplot as plt
import pandas as pd

from sensorguard import schema
from sensorguard.data.power import fetch_power_daily
from sensorguard.data.stations import (
    fetch_azmet_daily,
    fetch_fawn_daily,
    fetch_kansas_daily,
)

LOADERS = {
    "kansas": fetch_kansas_daily,
    "azmet": fetch_azmet_daily,
    "fawn": lambda station, start, end: fetch_fawn_daily(int(station), start, end),
}


def compare(station: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    """Per variable: mean gap (station - reference) and correlation."""
    rows = []
    for col in schema.COLUMNS:
        both = pd.concat([station[col], ref[col]], axis=1, keys=["s", "r"]).dropna()
        rows.append(
            {
                "variable": col,
                "days": len(both),
                "mean_gap": (both.s - both.r).mean(),
                "correlation": both.s.corr(both.r),
            }
        )
    return pd.DataFrame(rows).set_index("variable")


def make_figure(station: pd.DataFrame, ref: pd.DataFrame, site_id: str, out: Path):
    fig, axes = plt.subplots(
        len(schema.COLUMNS), 1, sharex=True, figsize=(11, 12), constrained_layout=True
    )
    for ax, col in zip(axes, schema.COLUMNS):
        ax.plot(ref.index, ref[col], label="NASA POWER (witness)", lw=0.9, alpha=0.8)
        ax.plot(station.index, station[col], label="station", lw=0.9, alpha=0.8)
        ax.set_ylabel(col)
        ax.grid(alpha=0.3)
    axes[0].legend(loc="upper right")
    axes[0].set_title(f"{site_id}: station against reference, clean data")
    axes[-1].set_xlabel("date")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site-id", required=True)
    p.add_argument("--network", required=True, choices=sorted(LOADERS))
    p.add_argument("--station", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--out-dir", default="results/figures")
    a = p.parse_args()

    station = LOADERS[a.network](a.station, a.start, a.end)
    ref = fetch_power_daily(a.lat, a.lon, a.start, a.end)

    out = Path(a.out_dir) / f"g1_{a.site_id}.png"
    make_figure(station, ref, a.site_id, out)
    print(compare(station, ref).round(2).to_string())
    print(f"Figure saved: {out}")


if __name__ == "__main__":
    main()